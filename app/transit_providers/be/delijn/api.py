import os
import json
import httpx
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from typing import Dict, List, Optional, TypedDict, Any, Union, Tuple, Generator
from pathlib import Path
import pandas as pd
import zipfile
import urllib.request
import pytz
import inspect
import logging
from logging.handlers import RotatingFileHandler
import sys
from config import get_config
from logging.config import dictConfig
import asyncio
from transit_providers.config import get_provider_config
import pytz
from dataclasses import asdict
from transit_providers.nearest_stop import (
    ingest_gtfs_stops, get_nearest_stops, cache_stops, 
    get_cached_stops, Stop, get_stop_by_name as generic_get_stop_by_name
)
import fcntl
import time
import csv
from functools import lru_cache
import hashlib

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('delijn')
logger.setLevel(logging.DEBUG)
# Get provider configuration
provider_config = get_provider_config('delijn')
logger.debug(f"Provider config: {provider_config}")

# API configuration
API_URL = provider_config.get('API_URL')
GTFS_URL = provider_config.get('GTFS_URL')


GTFS_DIR = provider_config.get('GTFS_DIR')

GTFS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = provider_config.get('CACHE_DIR')
CACHE_DIR.mkdir(parents=True, exist_ok=True)
try:
    CACHE_DIR.chmod(0o755)
except Exception as e:
    logger.warning(f"Could not set cache directory permissions: {e}")
logger.debug(f"GTFS_DIR: {GTFS_DIR}, CACHE_DIR: {CACHE_DIR}")
RATE_LIMIT_DELAY = provider_config.get('RATE_LIMIT_DELAY')
GTFS_CACHE_DURATION = provider_config.get('GTFS_CACHE_DURATION')
GTFS_USED_FILES = provider_config.get('GTFS_USED_FILES')
BASE_URL = provider_config.get('API_URL')

# API keys
DELIJN_API_KEY = provider_config.get('API_KEY')
DELIJN_GTFS_STATIC_API_KEY = provider_config.get('GTFS_STATIC_API_KEY')
DELIJN_GTFS_REALTIME_API_KEY = provider_config.get('GTFS_REALTIME_API_KEY')

# Configuration
STOP_ID = provider_config.get('STOP_IDS')
MONITORED_LINES = provider_config.get('MONITORED_LINES')
TIMEZONE = pytz.timezone(get_config('TIMEZONE'))
# Cache configuration
CACHE_DIR = get_config('CACHE_DIR') / "delijn"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_CACHE_DURATION = get_config('CACHE_DURATION')

# Add this configuration
SHAPES_CACHE_DIR = get_config('CACHE_DIR') / "delijn/shapes"
SHAPES_CACHE_DIR.mkdir(parents=True, exist_ok=True)

GTFS_CACHE_DURATION = provider_config.get('GTFS_CACHE_DURATION')

# Add this near the top of the file with other global variables
last_api_call = datetime.now(timezone.utc)

# Add this near the top with other constants
SERVICE_MESSAGE_CACHE_DURATION = 300  # 5 minutes in seconds

class CacheEntry(TypedDict):
    data: Any
    timestamp: datetime
    valid_until: Optional[datetime]

class StopInfo(TypedDict):
    name: str
    coordinates: Dict[str, float]
    lines: Dict[str, List[str]]

class PassingTime(TypedDict):
    line: str
    direction: str
    destination: str
    expected_arrival: datetime
    scheduled_arrival: datetime
    realtime: bool
    message: Optional[str]

class ProgressTracker:
    def __init__(self, total_size: int):
        self.total_size = total_size
        self.downloaded = 0
        self.start_time = time.time()
        self.last_update = 0
        
    def update(self, chunk_size: int) -> None:
        self.downloaded += chunk_size
        current_time = time.time()
        
        # Update progress every 0.5 seconds
        if current_time - self.last_update >= 0.5:
            elapsed = current_time - self.start_time
            speed = self.downloaded / (1024 * 1024 * elapsed)  # MB/s
            progress = (self.downloaded / self.total_size) * 100
            estimated_time_remaining = (self.total_size - self.downloaded) / (speed * 1024 * 1024)
            
            print(
                f"Downloaded: {self.downloaded/(1024*1024):.1f}MB / "
                f"{self.total_size/(1024*1024):.1f}MB "
                f"({progress:.1f}%) at {speed:.1f}MB/s, "
                f"ETA: {estimated_time_remaining:.1f}s"
            )
            self.last_update = current_time

async def cache_get(cache_key: str) -> Optional[Any]:
    """Get data from cache if it exists and is valid"""
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    if not cache_file.exists():
        logger.debug(f"Cache miss - file does not exist: {cache_key}")
        return None
        
    try:
        with open(cache_file, 'r') as f:
            cache_entry = json.load(f)
            
        # Convert timestamp and valid_until back to datetime
        timestamp = datetime.fromisoformat(cache_entry['timestamp'])
        valid_until = (datetime.fromisoformat(cache_entry['valid_until']) 
                      if cache_entry.get('valid_until') else 
                      timestamp + DEFAULT_CACHE_DURATION)
        
        # Check if cache is still valid
        if datetime.now(timezone.utc) < valid_until:
            logger.debug(f"Cache hit for {cache_key}")
            return cache_entry['data']
        else:
            logger.debug(f"Cache expired for {cache_key}")
            return None
    except Exception as e:
        logger.error(f"Error reading cache for {cache_key}: {str(e)}", exc_info=True)
        return None

async def cache_set(cache_key: str, data: Any, valid_until: Optional[datetime] = None) -> None:
    """Save data to cache with optional validity period"""
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    try:
        # Ensure the cache directory exists with proper permissions
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Set directory permissions to 755 (rwxr-xr-x)
        CACHE_DIR.chmod(0o755)
        
        cache_entry = {
            'data': data,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'valid_until': valid_until.isoformat() if valid_until else None
        }
        
        # Write the file with 644 permissions (rw-r--r--)
        with open(cache_file, 'w') as f:
            json.dump(cache_entry, f)
        cache_file.chmod(0o644)
            
        logger.debug(f"Successfully cached data for {cache_key}")
    except PermissionError as e:
        logger.error(f"Permission error while caching data for {cache_key}: {str(e)}")
        logger.error(f"Cache directory: {CACHE_DIR}")
        logger.error(f"Current permissions: {oct(CACHE_DIR.stat().st_mode)}")
        logger.error(f"Current user: {os.getuid()}")
        logger.error(f"Current group: {os.getgid()}")
    except Exception as e:
        logger.error(f"Error caching data for {cache_key}: {str(e)}", exc_info=True)

async def parse_stop_info(data: dict) -> StopInfo:
    """Parse the basic stop information into a cleaner format"""
    return {
        "name": data["omschrijvingLang"],
        "coordinates": {
            "lat": data["geoCoordinaat"]["latitude"], # type: ignore
            "lon": data["geoCoordinaat"]["longitude"] # type: ignore
        },
        "lines": {}  # Will be populated from line info
    }

async def parse_passing_times(data: dict) -> List[PassingTime]:
    """Parse the realtime arrivals into a cleaner format"""
    passing_times = []
    logger.debug("Starting to parse passing times")
    
    for halte in data.get("halteDoorkomsten", []):
        for doorkomst in halte.get("doorkomsten", []):
            # Debug print raw doorkomst data
            
            # Parse the timestamps and explicitly set timezone
            scheduled = TIMEZONE.localize(
                datetime.fromisoformat(doorkomst["dienstregelingTijdstip"])
            )
            
            # Use real-time time if available, otherwise use scheduled time
            expected = scheduled
            is_realtime = False
            if "real-timeTijdstip" in doorkomst:
                expected = TIMEZONE.localize(
                    datetime.fromisoformat(doorkomst["real-timeTijdstip"])
                )
                is_realtime = True
            
            passing_time = PassingTime(
                line=str(doorkomst["lijnnummer"]),
                direction=doorkomst["richting"],
                destination=doorkomst["bestemming"], # type: ignore
                expected_arrival=expected,
                scheduled_arrival=scheduled,
                realtime="REALTIME" in doorkomst.get("predictionStatussen", []),
                message=None
            )
            
            # Log detailed arrival information
            logger.debug(
                f"Parsed arrival - Line: {passing_time['line']}, "
                f"To: {passing_time['destination']}, "
                f"Scheduled: {scheduled.strftime('%H:%M:%S')}, "
                f"Expected: {expected.strftime('%H:%M:%S')}, "
                f"Realtime: {is_realtime}"
            )
            
            if is_realtime:
                delay_minutes = round((expected - scheduled).total_seconds() / 60, 1)
                logger.debug(f"Delay: {delay_minutes} minutes")
            
            passing_times.append(passing_time)
    
    # Sort by expected arrival time
    passing_times.sort(key=lambda x: x["expected_arrival"])
    logger.debug(f"Total passing times parsed: {len(passing_times)}")
    return passing_times

async def format_time_until(dt: datetime) -> str:
    """Format a datetime into a minutes-until string, allowing negative values"""
    # Always get fresh "now" time in Brussels timezone
    now = datetime.now(TIMEZONE)
    
    # If dt is naive, assume it's in Brussels time
    if dt.tzinfo is None:
        dt = TIMEZONE.localize(dt)
    else:
        # If dt has a different timezone, convert to Brussels
        dt = dt.astimezone(TIMEZONE)
    
    # Calculate difference directly in minutes
    diff = (dt - now).total_seconds() / 60
    minutes = int(diff)

    return f"{minutes}'"

async def get_line_colors() -> Dict[str, str]:
    """Get line colors from the API with caching"""
    cache_key = "line_colors"
    
    # Try to get from cache first
    cached_data = await cache_get(cache_key)
    if cached_data is not None:
        return cached_data
    
    # If not in cache or expired, fetch from API
    headers = {"Ocp-Apim-Subscription-Key": DELIJN_API_KEY}
    
    async with httpx.AsyncClient() as client:
        await rate_limit()  # Add rate limiting
        response = await client.get(f"{BASE_URL}/kleuren", headers=headers)
        if response.status_code == 200:
            colors_data = response.json()
            
            # Create a mapping of color codes to hex values
            color_map = {}
            for color in colors_data.get("kleuren", []):
                hex_color = f"#{color['hex']}" if 'hex' in color else None
                if hex_color:
                    color_map[color["code"]] = hex_color
            
            # Cache the results
            await cache_set(cache_key, color_map)
            return color_map
        return {}

async def rate_limit() -> None:
    """Enforce rate limiting between API calls"""
    global last_api_call
    now = datetime.now(timezone.utc)
    elapsed = (now - last_api_call).total_seconds()
    if elapsed < RATE_LIMIT_DELAY:
        delay = RATE_LIMIT_DELAY - elapsed
        logger.debug(f"Rate limiting: waiting {delay:.2f} seconds")
        await asyncio.sleep(delay)
    last_api_call = datetime.now(timezone.utc)

async def get_line_color(line_number: str) -> Optional[Dict[str, str]]:
    """Get color information for a specific line with caching"""
    cache_key = f"line_color_{line_number}"
    
    # Try to get from cache first
    cached_data = await cache_get(cache_key)
    if cached_data is not None:
        return cached_data
    
    headers = {"Ocp-Apim-Subscription-Key": DELIJN_API_KEY}
    
    try:
        async with httpx.AsyncClient() as client:
            await rate_limit()  # Add rate limiting
            logger.debug(f"Fetching color info for line {line_number}")
            response = await client.get(
                f"{BASE_URL}/lijnen/3/{line_number}/lijnkleuren",
                headers=headers
            )
            
            if response.status_code == 200:
                line_data = response.json()
                colors = await get_line_colors()
                
                # Extract color codes
                voorgrond = line_data.get("voorgrond", {}).get("code")
                achtergrond = line_data.get("achtergrond", {}).get("code")
                voorgrond_rand = line_data.get("voorgrondRand", {}).get("code")
                achtergrond_rand = line_data.get("achtergrondRand", {}).get("code")
                
                color_data = {
                    "text": colors.get(voorgrond),
                    "background": colors.get(achtergrond),
                    "text_border": colors.get(voorgrond_rand),
                    "background_border": colors.get(achtergrond_rand)
                }
                
                await cache_set(cache_key, color_data)
                logger.debug(f"Successfully retrieved colors for line {line_number}")
                return color_data
                
    except Exception as e:
        logger.error(f"Error getting line colors for line {line_number}: {str(e)}", exc_info=True)
    return None

async def get_line_stops(line_number: str, direction: str) -> Optional[List[Dict]]:
    """Get stops for a specific line and direction with caching"""
    cache_key = f"line_stops_{line_number}_{direction}"
    
    # Try to get from cache first
    cached_data = await cache_get(cache_key)
    if cached_data is not None:
        return cached_data
    
    # If not in cache or expired, fetch from API
    headers = {"Ocp-Apim-Subscription-Key": DELIJN_API_KEY}
    
    try:
        async with httpx.AsyncClient() as client:
            await rate_limit()  # Add rate limiting
            response = await client.get(
                f"{BASE_URL}/lijnen/3/{line_number}/lijnrichtingen/{direction}/haltes",
                headers=headers
            )
            
            if response.status_code == 200:
                stops_data = response.json()
                
                # Get validity period from response if available
                valid_until = None
                if 'lijnGeldigTot' in stops_data:
                    valid_until = datetime.fromisoformat(stops_data['lijnGeldigTot'])
                
                # Cache the results with validity period
                await cache_set(cache_key, stops_data, valid_until)
                return stops_data
                
    except Exception as e:
        logger.error(f"Error getting stops for line {line_number} direction {direction}: {e}", exc_info=True)
        return None

async def get_formatted_arrivals(stop_ids: List[str] = None) -> Dict:
    delijn_data = {
        "stops": {},
        "processed_vehicles": [],  # Make sure this field exists
        "errors": []
    }
    
    try:
        if stop_ids is None:
            stop_ids = STOP_ID  # Use default stops if none provided
        if isinstance(stop_ids, str):
            stop_ids = [stop_ids]
        
        logger.info(f"Fetching arrivals for stops {stop_ids}")
        if not stop_ids:
            logger.error("No stop IDs provided for De Lijn")
        
        headers = {"Ocp-Apim-Subscription-Key": DELIJN_API_KEY}
        
        # Initialize result structure
        formatted_data = {
            "stops": {},
            "colors": {}  # Moved colors to top level to avoid duplication
        }
        
        
        async with httpx.AsyncClient() as client:
                for stop_id in stop_ids:
                    # Rate limit before each API call
                    await rate_limit()
                    
                    # Get basic stop info
                    logger.debug(f"Fetching stop info for {stop_id}")
                    stop_response = await client.get(f"{BASE_URL}/haltes/3/{stop_id}", headers=headers)
                    logger.debug(f"Stop info response status for {stop_id}: {stop_response.status_code}")
                    logger.debug(f"Stop info response for {stop_id}: {stop_response.text}")  # Log full response
                    
                    if stop_response.status_code != 200:
                        logger.error(f"Failed to get stop info for {stop_id}: HTTP {stop_response.status_code}")
                        logger.error(f"Response headers: {stop_response.headers}")
                        continue
                    
                    stop_data = stop_response.json()
                    stop_info = await parse_stop_info(stop_data)
                    logger.debug(f"Parsed stop info for {stop_id}: {stop_info}")
                    
                    # Rate limit before getting realtime arrivals
                    await rate_limit()
                    
                    # Get realtime arrivals
                    logger.debug(f"Fetching realtime arrivals for {stop_id}")
                    arrivals_response = await client.get(
                        f"{BASE_URL}/haltes/3/{stop_id}/real-time",
                        headers=headers
                    )
                    logger.debug(f"Realtime response status for {stop_id}: {arrivals_response.status_code}")
                    logger.debug(f"Realtime response for {stop_id}: {arrivals_response.text}")  # Log full response
                    
                    if arrivals_response.status_code != 200:
                        logger.error(f"Failed to get arrivals for {stop_id}: HTTP {arrivals_response.status_code}")
                        logger.error(f"Response headers: {arrivals_response.headers}")
                        logger.error(f"Response: {arrivals_response.text}")
                        logger.error(f"URL: {BASE_URL}/haltes/3/{stop_id}/real-time")
                        continue
                    
                    arrivals_data = arrivals_response.json()
                    passing_times = await parse_passing_times(arrivals_data)
                    logger.debug(f"Parsed {len(passing_times)} passing times for {stop_id}: {passing_times}")
                    
                    # Initialize stop data structure
                    formatted_data["stops"][stop_id] = {
                        "name": stop_info["name"],
                        "coordinates": stop_info["coordinates"],
                        "lines": {}
                    }
                    
                    # Process each passing time
                    for passing in passing_times:
                        line = passing["line"]
                        destination = passing["destination"]
                        logger.debug(f"Processing passing time for {stop_id}, line {line} to {destination}")
                        
                        if MONITORED_LINES and line not in MONITORED_LINES:
                            logger.debug(f"Skipping unmonitored line {line}")
                            continue
                        
                        # Get line colors if not already cached
                        if line not in formatted_data["colors"]:
                            logger.debug(f"Fetching colors for line {line}")
                            colors = await get_line_color(line)
                            if colors:
                                formatted_data["colors"][line] = colors
                                logger.debug(f"Added colors for line {line}: {colors}")
                            else:
                                logger.warning(f"No colors found for line {line}")
                        
                        # Initialize data structures if needed
                        if line not in formatted_data["stops"][stop_id]["lines"]:
                            formatted_data["stops"][stop_id]["lines"][line] = {}
                        if destination not in formatted_data["stops"][stop_id]["lines"][line]:
                            formatted_data["stops"][stop_id]["lines"][line][destination] = []
                        
                        # Calculate minutes and format times
                        scheduled_minutes = await format_time_until(passing["scheduled_arrival"])
                        scheduled_time = passing["scheduled_arrival"].strftime("%H:%M")
                        
                        arrival_data = {
                            "scheduled_minutes": scheduled_minutes,
                            "scheduled_time": scheduled_time,
                            "is_realtime": passing["realtime"],
                            "message": passing["message"] if passing["message"] else None
                        }
                        
                        if passing["realtime"]:
                            realtime_minutes = await format_time_until(passing["expected_arrival"])
                            delay = int(realtime_minutes.rstrip("'")) - int(scheduled_minutes.rstrip("'"))
                            arrival_data.update({
                                "realtime_minutes": realtime_minutes,
                                "realtime_time": passing["expected_arrival"].strftime("%H:%M"),
                                "delay": delay
                            })
                            logger.debug(f"Realtime data for {stop_id}, line {line}: minutes={realtime_minutes}, delay={delay}")
                        
                        formatted_data["stops"][stop_id]["lines"][line][destination].append(arrival_data)
                        logger.debug(f"Added arrival data for {stop_id}, line {line}: {arrival_data}")
                
                logger.debug(f"Final formatted data: {json.dumps(formatted_data, indent=2, default=str)}")
                logger.debug(f"Returning De Lijn data with {len(delijn_data['processed_vehicles'])} vehicles")
                for vehicle in delijn_data['processed_vehicles']:
                    logger.debug(f"Vehicle data: {vehicle}")
                return formatted_data
                
    except Exception as e:
            logger.error(f"Error getting formatted arrivals: {str(e)}", exc_info=True)
            return {
                "stops": {},
                "processed_vehicles": [],  # Make sure it's included in error case too
                "errors": [str(e)]
            }

async def download_and_extract_gtfs() -> bool:
    """Download and extract fresh GTFS data with file locking"""
    lock_file = CACHE_DIR / "gtfs_download.lock"
    
    # Check if we already have recent GTFS data
    if GTFS_DIR.exists():
        # Check if all required files exist and are recent
        all_files_exist = True
        oldest_file_age = 0
        
        for filename in GTFS_USED_FILES:
            file_path = GTFS_DIR / filename
            if not file_path.exists():
                logger.info(f"Missing required GTFS file: {filename}, path: {file_path}")
                all_files_exist = False
                break
            
            file_age = time.time() - file_path.stat().st_mtime
            oldest_file_age = max(oldest_file_age, file_age)
        
        if all_files_exist:
            if oldest_file_age < GTFS_CACHE_DURATION:
                logger.debug(f"Using existing GTFS data (age: {oldest_file_age:.1f}s)")
                return True
            else:
                logger.info(f"GTFS data is too old (age: {oldest_file_age:.1f}s), downloading fresh copy")
        else:
            logger.info("Some GTFS files are missing, downloading fresh copy")
    
    try:
        while True:  # Loop until we get the lock or timeout
            try:
                start_time = time.time()
                with open(lock_file, 'w') as f:
                    try:
                        # Try to acquire lock
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break  # Got the lock, proceed with download
                    except BlockingIOError:
                        # Check for stale lock
                        if lock_file.exists():
                            lock_age = time.time() - lock_file.stat().st_mtime
                            if lock_age > 3600:  # 1 hour in seconds
                                logger.warning(f"Lock file is {lock_age:.1f}s old, attempting to remove stale lock")
                                try:
                                    lock_file.unlink()
                                    logger.info("Successfully removed stale lock, will retry")
                                    continue  # Retry lock acquisition
                                except Exception as e:
                                    logger.error(f"Failed to remove stale lock: {e}")
                        
                        # Not stale or couldn't remove - wait and retry
                        logger.info("Another process is downloading GTFS data, waiting...")
                        await asyncio.sleep(10)  # Wait 10 seconds before retry
                        
                        # Check overall timeout
                        if time.time() - start_time > 300:  # 5 minutes timeout
                            logger.error("Timeout waiting for GTFS download lock")
                            return False
                        
                        continue  # Try again
            except Exception as e:
                logger.error(f"Error handling lock file: {e}")
                return False

        try:
            logger.info("Starting GTFS data download")
            
            headers = {
                'Cache-Control': 'no-cache',
                'Ocp-Apim-Subscription-Key': DELIJN_GTFS_STATIC_API_KEY
            }
            
            # Get file size from the GET response
            req = urllib.request.Request(GTFS_URL, headers=headers)
            with urllib.request.urlopen(req) as response:
                total_size = int(response.headers.get('content-length', 0))
                logger.info(f"GTFS file size: {total_size/(1024*1024):.1f}MB")
                
                logger.debug("Saving GTFS zip file")
                progress = ProgressTracker(total_size)
                
                with open('gtfs_transit.zip', 'wb') as f_zip:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f_zip.write(chunk)
                        progress.update(len(chunk))
                
            logger.debug("Extracting GTFS data")
            GTFS_DIR.mkdir(exist_ok=True)
            try:
                with zipfile.ZipFile('gtfs_transit.zip', 'r') as zip_ref:
                    zip_ref.extractall(GTFS_DIR)
                    logger.debug(f"Extracted GTFS data to {GTFS_DIR}")
            except Exception as e:
                logger.error(f"Error extracting GTFS data: {e}", exc_info=True)
            
            # Clean up zip file
            try:
                Path('gtfs_transit.zip').unlink()
                logger.debug("Deleted GTFS zip file")
            except Exception as e:
                logger.error(f"Error deleting GTFS zip file: {e}", exc_info=True)

            # Clean up unused files
            for file in GTFS_DIR.glob('*'):
                if file.name not in GTFS_USED_FILES:
                    file.unlink()
                    logger.debug(f"Deleted unused GTFS file: {file.name}")
            
            logger.info("GTFS data updated successfully")
            return True
            
        finally:
            # Release lock and clean up
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    logger.debug("Deleted lock file")
                except Exception as e:
                    logger.error(f"Error deleting lock file: {e}")
                    
    except Exception as e:
        logger.error(f"Error updating GTFS data: {str(e)}", exc_info=True)
        return False

def iter_gtfs_file(file_path: Path) -> Generator[Dict[str, str], None, None]:
    """Generator to read GTFS files line by line."""
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row

# Helper function to create cache key from file path and modification time
def get_file_hash(file_path: Path) -> str:
    """Create hash from file path and modification time for cache invalidation."""
    mtime = file_path.stat().st_mtime
    return hashlib.md5(f"{file_path}:{mtime}".encode()).hexdigest()

@lru_cache(maxsize=128)
def get_cached_route_info(file_hash: str, line_number: str) -> Tuple[Optional[str], Optional[Dict]]:
    """Cached version of route info lookup."""
    route_file = GTFS_DIR / 'routes.txt'
    route_id = None
    route_data = None
    
    for route in iter_gtfs_file(route_file):
        if route['route_short_name'] == str(line_number):
            route_id = route['route_id']
            route_data = route
            break
    
    return route_id, route_data

@lru_cache(maxsize=128)
def get_cached_trips_for_route(file_hash: str, route_id: str) -> Dict[str, List[Dict[str, str]]]:
    """Cached version of trips lookup."""
    trips_file = GTFS_DIR / 'trips.txt'
    trips_by_direction = {}
    
    for trip in iter_gtfs_file(trips_file):
        if trip['route_id'] == route_id:
            direction = trip['direction_id']
            if direction not in trips_by_direction:
                trips_by_direction[direction] = []
            trips_by_direction[direction].append(trip)
    
    return trips_by_direction

@lru_cache(maxsize=256)
def get_cached_shapes_for_trip(file_hash: str, shape_id: str) -> List[Dict[str, str]]:
    """Cached version of shapes lookup."""
    shapes_file = GTFS_DIR / 'shapes.txt'
    shape_points = []
    
    for point in iter_gtfs_file(shapes_file):
        if point['shape_id'] == shape_id:
            shape_points.append(point)
    
    return sorted(shape_points, key=lambda x: int(x['shape_pt_sequence']))

# Update the async functions to use the cached versions
async def get_route_info(gtfs_dir: Path, line_number: str) -> Tuple[Optional[str], Optional[Dict]]:
    """Get route info from GTFS data using cached generator."""
    try:
        route_file = gtfs_dir / 'routes.txt'
        file_hash = get_file_hash(route_file)
        return get_cached_route_info(file_hash, line_number)
    except Exception as e:
        logger.error(f"Error reading route data: {e}")
        return None, {"error": str(e)}

async def get_trips_for_route(gtfs_dir: Path, route_id: str) -> Dict[str, List[Dict[str, str]]]:
    """Get all trips for a route using cached lookup."""
    try:
        trips_file = gtfs_dir / 'trips.txt'
        file_hash = get_file_hash(trips_file)
        return get_cached_trips_for_route(file_hash, route_id)
    except Exception as e:
        logger.error(f"Error reading trips data: {e}")
        return {}

async def get_shapes_for_trip(gtfs_dir: Path, shape_id: str) -> List[Dict[str, str]]:
    """Get ALL shape points for a trip using cached lookup."""
    try:
        shapes_file = gtfs_dir / 'shapes.txt'
        file_hash = get_file_hash(shapes_file)
        return get_cached_shapes_for_trip(file_hash, shape_id)
    except Exception as e:
        logger.error(f"Error reading shapes data: {e}")
        return []

async def get_line_shape(line_number: str) -> Optional[Dict]:
    """Get the shape of a line with caching."""
    cache_key = f"line_{line_number}"
    
    # Try to get from cache first
    cached_data = await cache_get(cache_key)
    if cached_data is not None:
        return cached_data
    
    try:
        logger.debug(f"Processing GTFS data for line {line_number}")
        
        gtfs_dir = await ensure_gtfs_data()
        if gtfs_dir is None:
            logger.error("Could not get GTFS data")
            return {"error": "GTFS data not available"}
        
        # Get route info
        route_id, route_error = await get_route_info(gtfs_dir, line_number)
        if not route_id:
            return route_error
        
        # Get ALL trips for this route, grouped by direction
        trips_by_direction = await get_trips_for_route(gtfs_dir, route_id)
        if not trips_by_direction:
            logger.warning(f"No trips found for route {line_number}")
            return None
            
        # Process shapes for each direction
        variants = []
        for direction_id, direction_trips in trips_by_direction.items():
            # Take first trip for each direction (same as pandas groupby.first())
            trip = direction_trips[0]
            shape_id = trip['shape_id']
            logger.debug(f"Processing shape {shape_id} for direction {direction_id}")
            
            # Get ALL shape points, sorted by sequence
            shape_points = await get_shapes_for_trip(gtfs_dir, shape_id)
            coordinates = [
                [float(point['shape_pt_lat']), float(point['shape_pt_lon'])]
                for point in shape_points
            ]
            
            variants.append({
                "variante": len(variants) + 1,
                "date_debut": datetime.now().strftime("%d/%m/%Y"),
                "date_fin": (datetime.now() + timedelta(seconds=GTFS_CACHE_DURATION)).strftime("%d/%m/%Y"),
                "coordinates": coordinates
            })
        
        shape_data = {
            "variants": variants,
            "date_fin": (datetime.now() + timedelta(seconds=GTFS_CACHE_DURATION)).strftime("%d/%m/%Y"),
            "cached_at": datetime.now(timezone.utc).isoformat()
        }
        
        await cache_set(cache_key, shape_data)
        logger.info(f"Successfully processed shape data for line {line_number}")
        return shape_data
        
    except Exception as e:
        logger.error(f"Error getting shape for line {line_number}: {str(e)}", exc_info=True)
        return {"error": str(e)}

async def get_vehicle_positions(line_number: str = "272", direction: str = "TERUG") -> List[Dict]:
    """Get real-time positions of vehicles for a specific line"""
    try:
        logger.info(f"\n=== Fetching vehicle positions for line {line_number} ===")
        
        # First get the route ID from GTFS data
        gtfs_dir = await ensure_gtfs_data()
        if not gtfs_dir:
            logger.error("Could not get GTFS data")
            return []
            
        routes_df = pd.read_csv(gtfs_dir / 'routes.txt')
        route = routes_df[routes_df['route_short_name'] == str(line_number)]
        if route.empty:
            logger.warning(f"Route {line_number} not found in GTFS data")
            return []
            
        route_ids = route['route_id'].tolist()
        logger.info(f"Found route_ids: {route_ids} for line {line_number}")
        
        # Get trips for this route to map trip_ids to directions and headsigns
        trips_df = pd.read_csv(gtfs_dir / 'trips.txt')
        route_trips = trips_df[trips_df['route_id'].isin(route_ids)]
        
        logger.info(f"Found {len(route_trips)} trips in GTFS data for routes {route_ids}")
        
        # Create trip mapping and store valid trip IDs for this route
        trip_directions = {}
        valid_trip_ids = set()  # Store valid trip IDs for this route
        for _, trip in route_trips.iterrows():
            trip_id = trip['trip_id']
            trip_directions[trip_id] = {
                'direction': f"TERUG" if trip['direction_id'] == 1 else f"HEEN",
                'headsign': trip['trip_headsign'],
                '_direction_id': trip['direction_id']
            }
            valid_trip_ids.add(trip_id)  # Add to set of valid trip IDs

        logger.info(f"Mapped {len(trip_directions)} trips to directions/headsigns")
        logger.debug("Sample GTFS trip data:")
        if route_trips.shape[0] > 0:
            sample_trip = route_trips.iloc[0]
            logger.debug(f"  Trip ID: {sample_trip['trip_id']}")
            logger.debug(f"  Headsign: {sample_trip['trip_headsign']}")
            logger.debug(f"  Direction: {'HEEN' if sample_trip['direction_id'] == 0 else 'TERUG'}")

        # Get real-time vehicle positions
        headers = {
            'Cache-Control': 'no-cache',
            'Ocp-Apim-Subscription-Key': DELIJN_GTFS_REALTIME_API_KEY
        }
        
        params = {
            'json': 'true',
            'position': 'true',
            'delay': 'true'
        }
        
        async with httpx.AsyncClient() as client:
            await rate_limit()
            response = await client.get(
                'https://api.delijn.be/gtfs/v3/realtime',
                headers=headers,
                params=params
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get vehicle positions: HTTP {response.status_code}")
                return []
            
            data = response.json()
            vehicles = []
            matched_trips = 0
            unmatched_trips = 0
            
            for entity in data.get('entity', []):
                if 'vehicle' not in entity:
                    continue
                    
                vehicle = entity['vehicle']
                trip_info = vehicle.get('trip', {})
                trip_id = trip_info.get('tripId', '')
                
                if trip_id in valid_trip_ids:  # Only process vehicles with matching trip_ids
                    # Get direction and headsign from our trip_directions mapping
                    trip_data = trip_directions.get(trip_id)
                    
                    if trip_data:
                        matched_trips += 1
                    else:
                        unmatched_trips += 1
                        trip_data = {
                            'direction': "Unknown Direction",
                            'headsign': "Unknown Destination"
                        }
                        logger.debug(f"No match found for trip_id: {trip_id}")
                    
                    position = vehicle.get('position', {})
                    if not position:
                        continue
                        
                    delay = None
                    if 'tripUpdate' in entity:
                        stop_time_updates = entity['tripUpdate'].get('stopTimeUpdate', [])
                        if stop_time_updates:
                            delay = stop_time_updates[0].get('departure', {}).get('delay', 0)
                    
                    vehicle_data = {
                        'line': line_number,
                        'direction': trip_data['direction'],
                        'headsign': trip_data['headsign'],
                        'position': {
                            'lat': position.get('latitude'),
                            'lon': position.get('longitude')
                        },
                        'bearing': position.get('bearing', 0),
                        'timestamp': datetime.fromtimestamp(
                            int(vehicle.get('timestamp', 0)),
                            tz=TIMEZONE
                        ).isoformat(),
                        'vehicle_id': vehicle.get('vehicle', {}).get('id'),
                        'trip_id': trip_id,
                        'delay': delay if delay is not None else 0,
                        'is_valid': True
                    }
                    
                    vehicles.append(vehicle_data)
            
            logger.info(f"\n=== Results for line {line_number} ===")
            logger.info(f"Total vehicles found: {len(vehicles)}")
            logger.info(f"Trips matched: {matched_trips}")
            logger.info(f"Trips unmatched: {unmatched_trips}")
            
            # Log details of first few vehicles
            for i, vehicle in enumerate(vehicles[:3]):
                logger.info(f"\nVehicle {i+1}:")
                logger.info(f"  Trip ID: {vehicle['trip_id']}")
                logger.info(f"  Headsign: {vehicle['headsign']}")
                logger.info(f"  Direction: {vehicle['direction']}")
                logger.info(f"  Position: {vehicle['position']}")
                logger.info(f"  Delay: {vehicle['delay']} seconds")
            
            return vehicles
            
    except Exception as e:
        logger.error(f"Error getting vehicle positions: {str(e)}", exc_info=True)
        return []

def message_is_duplicate(msg1: dict, msg2: dict) -> bool:
    """Compare two messages to determine if they are duplicates.
    
    Compares key fields that would indicate the same disruption/message.
    """
    # Compare essential fields
    key_fields = [
        ('titel', 'title'),
        ('omschrijving', 'description'),
        ('type', 'type'),
        ('periode.startDatum', 'start date'),
        ('periode.eindDatum', 'end date')
    ]
    
    for field, name in key_fields:
        val1 = msg1.get(field)
        val2 = msg2.get(field)
        if val1 != val2:
            logger.debug(f"Messages differ in {name}: '{val1}' vs '{val2}'")
            return False
    
    # Compare affected lines
    lines1 = sorted([str(lr.get('lijnnummer')) for lr in msg1.get('lijnrichtingen', [])])
    lines2 = sorted([str(lr.get('lijnnummer')) for lr in msg2.get('lijnrichtingen', [])])
    if lines1 != lines2:
        logger.debug(f"Messages differ in affected lines: {lines1} vs {lines2}")
        return False
    
    # Compare affected stops
    stops1 = sorted([str(h.get('haltenummer')) for h in msg1.get('haltes', [])])
    stops2 = sorted([str(h.get('haltenummer')) for h in msg2.get('haltes', [])])
    if stops1 != stops2:
        logger.debug(f"Messages differ in affected stops: {stops1} vs {stops2}")
        return False
    
    return True

service_messages_cache = {}


async def get_service_messages() -> List[Dict]:
    """Get service messages for monitored stops and lines with caching"""
    cache_key = "service_messages"
    
    # Try to get from cache first
    cached_data = await cache_get(cache_key)
    if cached_data is not None:
        logger.debug(f"Returning cached service messages for De Lijn: {len(cached_data)}")
        return cached_data
    logger.debug(f"No cached service messages found for De Lijn, fetching fresh data")
    headers = {"Ocp-Apim-Subscription-Key": DELIJN_API_KEY}
    messages = []
    global STOP_ID
    if isinstance(STOP_ID, str):
        STOP_ID = [STOP_ID]
    try:
        # Collect all messages first
        async with httpx.AsyncClient() as client:
            # Get messages for our monitored stops
            for stop_id in STOP_ID:  # Now iterates over all monitored stops
                for endpoint in ['storingen', 'omleidingen']:
                    await rate_limit()  # Add rate limiting
                    stop_response = await client.get(
                        f"{BASE_URL}/haltes/{3}/{stop_id}/{endpoint}",
                        headers=headers
                    )
                    if stop_response.status_code == 200:
                        stop_data = stop_response.json()
                        messages.extend(stop_data.get("omleidingen", []))

            # Get messages for each monitored line
            for line in MONITORED_LINES:
                for direction in ['HEEN', 'TERUG']:
                    for endpoint in ['storingen', 'omleidingen']:
                        await rate_limit()  # Add rate limiting
                        line_response = await client.get(
                            f"{BASE_URL}/lijnen/{3}/{line}/lijnrichtingen/{direction}/{endpoint}",
                            headers=headers
                        )
                        if line_response.status_code == 200:
                            line_data = line_response.json()
                            messages.extend(line_data.get("omleidingen", []))

        # Remove duplicates using thorough comparison
        logger.debug(f"Found {len(messages)} messages before deduplication")
        unique_messages = []
        for msg in messages:
            is_duplicate = any(message_is_duplicate(msg, existing) for existing in unique_messages)
            if not is_duplicate:
                unique_messages.append(msg)
            else:
                logger.debug(f"Skipping duplicate message: {msg.get('titel')}")

        logger.debug(f"Found {len(unique_messages)} unique messages after deduplication")
        
        # Format messages in a clean structure
        filtered_messages = []
        
        # Process each message with a new client
        async with httpx.AsyncClient() as client:
            for msg in unique_messages:
                try:
                    # Get affected lines and their colors
                    affected_lines = sorted([
                        str(lr.get('lijnnummer'))
                        for lr in msg.get('lijnrichtingen', [])
                    ], key=lambda x: int(x) if x.isdigit() else float('inf'))
                    
                    # Get colors for all affected lines
                    line_colors = {}
                    for line in affected_lines:
                        try:
                            colors = await get_line_color(line)
                            if colors:
                                line_colors[line] = colors
                                logger.debug(f"Got colors for line {line}: {colors}")
                        except Exception as e:
                            logger.error(f"Error getting colors for line {line}: {str(e)}", exc_info=True)
                            continue

                    # Get affected stops with names
                    affected_stops = []
                    for stop in msg.get('haltes', []):
                        stop_id = str(stop.get('haltenummer'))
                        try:
                            # Get stop details
                            await rate_limit()  # Add rate limiting
                            stop_response = await client.get(
                                f"{BASE_URL}/haltes/3/{stop_id}",
                                headers=headers
                            )
                            if stop_response.status_code == 200:
                                stop_data = stop_response.json()
                                stop_name = stop_data.get('omschrijvingLang') or stop_data.get('omschrijving')
                                logger.debug(f"Got name for stop {stop_id}: {stop_name}")
                            else:
                                stop_name = stop.get('omschrijving') or stop_id
                                logger.warning(f"Failed to get name for stop {stop_id}, using fallback: {stop_name}")
                        except Exception as e:
                            logger.error(f"Error getting stop name for {stop_id}: {str(e)}", exc_info=True)
                            stop_name = stop.get('omschrijving') or stop_id

                        affected_stops.append({
                            'id': stop_id,
                            'name': stop_name,
                            'long_name': stop.get('omschrijvingLang')
                        })

                    is_monitored = (
                        any(line in MONITORED_LINES for line in affected_lines) and 
                        STOP_ID in [stop['id'] for stop in affected_stops]
                    )

                    filtered_message = {
                        'title': msg.get('titel'),
                        'description': msg.get('omschrijving'),
                        'period': {
                            'start': msg.get('periode', {}).get('startDatum'),
                            'end': msg.get('periode', {}).get('eindDatum')
                        },
                        'type': msg.get('type'),
                        'reference': msg.get('referentieOmleiding'),
                        'affected_lines': affected_lines,
                        'line_colors': line_colors,  # Add line colors to the message
                        'affected_stops': affected_stops,
                        'affected_days': msg.get('omleidingsDagen', []),
                        'is_monitored': is_monitored
                    }
                    
                    logger.debug(f"Processed message with {len(affected_lines)} lines and {len(affected_stops)} stops: {filtered_message}")
                    logger.debug(f"Line colors: {line_colors}")
                    
                    filtered_messages.append(filtered_message)
                    
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}", exc_info=True)
                    continue

        # Before returning, cache the filtered messages
        cache_until = datetime.now(timezone.utc) + timedelta(seconds=SERVICE_MESSAGE_CACHE_DURATION)
        await cache_set(cache_key, filtered_messages, cache_until)
        logger.debug(f"Cached {len(filtered_messages)} service messages until {cache_until}")
        
        return filtered_messages

    except Exception as e:
        logger.error(f"Error getting service messages: {str(e)}", exc_info=True)
        return []

async def ensure_gtfs_data() -> Optional[Path]:
    """Ensure GTFS data is downloaded and return path to GTFS directory."""
    logger.debug(f"Checking GTFS data in directory: {GTFS_DIR}")
    if GTFS_DIR.exists():
        # Check if another process is currently downloading GTFS data
        lock_file = CACHE_DIR / "gtfs_download.lock"
        if lock_file.exists():
            logger.info("GTFS Lock file exists, waiting for other process to finish downloading...")
            start_time = time.time()
            while time.time() - start_time < 120:  # Wait up to 2 minutes
                if not lock_file.exists():
                    logger.info("GTFS Lock file removed, proceeding after 20s delay...")
                    await asyncio.sleep(10)  # Wait additional 20s for unzipping
                    break
                await asyncio.sleep(10)  # Check every 10 seconds
                logger.debug("Still waiting for GTFS Lock file to be removed...")
            else:
                logger.warning("Timeout waiting for GTFS Lock file to be removed")

        # Check if all required files exist and are recent
        all_files_exist = True
        oldest_file_age = 0
        
        for filename in GTFS_USED_FILES:
            file_path = GTFS_DIR / filename
            logger.debug(f"Checking for GTFS file: {file_path}")
            if not file_path.exists():
                logger.info(f"Missing required GTFS file: {filename} (full path: {file_path})")
                all_files_exist = False
                break
            
            file_age = time.time() - file_path.stat().st_mtime
            oldest_file_age = max(oldest_file_age, file_age)
            logger.debug(f"GTFS File {filename} exists, age: {file_age:.1f}s")
        
        if all_files_exist:
            if oldest_file_age < GTFS_CACHE_DURATION:
                logger.debug(f"Using existing GTFS data (age: {oldest_file_age:.1f}s)")
                return GTFS_DIR
            else:
                logger.info(f"GTFS data is too old (age: {oldest_file_age:.1f}s), downloading fresh copy")
        else:
            logger.info("Some GTFS files are missing, downloading fresh copy")
    else:
        logger.info(f"GTFS directory does not exist: {GTFS_DIR}")
    
    # Need to download fresh data
    logger.debug(f"Downloading GTFS data from {GTFS_URL}. Download triggered by {__file__}, function: {inspect.currentframe().f_code.co_name}")
    success = await download_and_extract_gtfs()
    if not success:
        logger.error("Failed to download GTFS data")
        return None
    
    # Verify files after download
    if GTFS_DIR.exists():
        missing_files = [f for f in GTFS_USED_FILES if not (GTFS_DIR / f).exists()]
        if missing_files:
            logger.error(f"After GTFSdownload, still missing files: {missing_files}")
            return None
        logger.debug("All required GTFS files present after download")
    else:
        logger.error("GTFS directory still does not exist after download")
        return None
    
    return GTFS_DIR

async def get_stops() -> Dict[str, Stop]:
    """Get all stops from GTFS data or cache."""
    cache_path = CACHE_DIR / 'stops.json'
    
    # Try to get from cache first
    cached_stops = get_cached_stops(cache_path)
    if cached_stops is not None:
        return cached_stops
    
    # If not in cache, ensure GTFS data and load stops
    logger.debug(f"Getting stops from GTFS data. Getting triggered by {__file__}, function: {inspect.currentframe().f_code.co_name}")
    gtfs_dir = await ensure_gtfs_data()
    if gtfs_dir is None:
        logger.error("Could not get GTFS data")
        return {}
    
    stops = ingest_gtfs_stops(gtfs_dir)
    if stops:
        cache_stops(stops, cache_path)
    return stops

async def find_nearest_stops(lat: float, lon: float, limit: int = 5, max_distance: float = 2.0) -> List[Dict]:
    """Find nearest stops to given coordinates."""
    stops = await get_stops()
    if not stops:
        logger.error("No stops data available")
        return []
    
    return get_nearest_stops(stops, (lat, lon), limit, max_distance)

async def main():
    # Get formatted arrivals for all monitored stops
    logger.debug(f"Getting formatted arrivals for stop {STOP_ID}")
    formatted = await get_formatted_arrivals(STOP_ID)
    
    # Add service messages
    messages = await get_service_messages()
    
    # Prepare data in STIB-like format
    delijn_data = {
        "stops_data": {},  # Will contain stop arrivals
        "messages": {
            "messages": messages  # Will contain service messages
        },
        "processed_vehicles": [],  # Will contain vehicle positions
        "errors": []
    }
    
    try:
        # Convert De Lijn arrivals to STIB format
        for stop_id, stop_data in formatted.get("stops", {}).items():
            for line, destinations in stop_data.get("lines", {}).items():
                for destination, times in destinations.items():
                    for time in times:
                        # Create STIB-like format for each arrival
                        arrival_data = {
                            "scheduled_minutes": time["scheduled_minutes"],
                            "scheduled_time": time["scheduled_time"]
                        }
                        
                        if time.get("is_realtime"):
                            arrival_data.update({
                                "minutes": time["realtime_minutes"],
                                "formatted_time": time["realtime_time"],
                                "delay": time["delay"]
                            })
                        
                        # Add to stops_data in STIB format
                        if stop_id not in delijn_data["stops_data"]:
                            delijn_data["stops_data"][stop_id] = {
                                "lines": {}
                            }
                        
                        if line not in delijn_data["stops_data"][stop_id]["lines"]:
                            delijn_data["stops_data"][stop_id]["lines"][line] = {}
                        
                        if destination not in delijn_data["stops_data"][stop_id]["lines"][line]:
                            delijn_data["stops_data"][stop_id]["lines"][line][destination] = []
                        
                        delijn_data["stops_data"][stop_id]["lines"][line][destination].append(arrival_data)
        
        # Get and process vehicle positions
        for line in MONITORED_LINES:
            vehicles = await get_vehicle_positions(line)
            if vehicles:
                # Convert to STIB-like format
                for vehicle in vehicles:
                    processed_vehicle = {
                        "line": vehicle["line"],
                        "direction": vehicle["direction"],
                        "position": vehicle["position"],
                        "bearing": vehicle["bearing"],
                        "delay": vehicle["delay"],
                        "last_update": vehicle["timestamp"],
                        "is_valid": vehicle["is_valid"],
                        # Fields we'll add later when we implement segment tracking:
                        # "current_segment": vehicle.get("current_segment"),
                        # "distance_to_next": None,
                        # "segment_length": None,
                        # "interpolated_position": None
                    }
                    delijn_data["processed_vehicles"].append(processed_vehicle)
        
        # Print formatted data for debugging
        # print("\nDe Lijn Data in STIB Format:")
        # print(json.dumps(delijn_data, indent=2, default=str))
        
        # Print vehicle positions separately for clarity
        if delijn_data["processed_vehicles"]:
            # print(f"\nFound {len(delijn_data['processed_vehicles'])} vehicles:")
            # for vehicle in delijn_data["processed_vehicles"]:
            #     print(f"Vehicle on line {vehicle['line']}:")
            #     print(f"  Position: {vehicle['position']['lat']}, {vehicle['position']['lon']}")
            #     print(f"  Bearing: {vehicle['bearing']}°")
            #     print(f"  Delay: {vehicle['delay']} seconds")
            #     print(f"  Last update: {vehicle['last_update']}")
            pass
    
    except Exception as e:
        logger.error(f"Error processing De Lijn data: {e}")
        import traceback
        logger.error(traceback.format_exc())
        delijn_data["errors"].append(str(e))
    
    return delijn_data


def get_nearest_stop(coordinates: Tuple[float, float]) -> Dict[str, Any]:
    """Get nearest stop to coordinates."""
    lat, lon = coordinates
    stops = asyncio.run(find_nearest_stops(lat, lon, limit=1))
    return stops[0] if stops else {}

async def get_stop_by_name(name: str, limit: int = 5) -> List[Dict]:
    """Search for stops by name using the generic function.
    
    Args:
        name (str): The name or partial name to search for
        limit (int, optional): Maximum number of results to return. Defaults to 5.
        
    Returns:
        List[Dict]: List of matching stops with their details
    """
    try:
        # Get cached stops
        stops = get_cached_stops(CACHE_DIR / 'stops.json')
        if not stops:
            # If not in cache, ensure GTFS data and load stops
            logger.debug(f"Getting stops from GTFS data. Getting triggered by {__file__}, function: {inspect.currentframe().f_code.co_name}")
            gtfs_dir = await ensure_gtfs_data()
            if gtfs_dir is None:
                logger.error("Could not get GTFS data")
                return []
            
            stops = ingest_gtfs_stops(gtfs_dir)
            if not stops:
                logger.error("No stops data available")
                return []
            
        # Use the generic function
        matching_stops = generic_get_stop_by_name(stops, name, limit)
        
        # Convert Stop objects to dictionaries
        return [asdict(stop) for stop in matching_stops] if matching_stops else []
        
    except Exception as e:
        logger.error(f"Error in get_stop_by_name: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
    

