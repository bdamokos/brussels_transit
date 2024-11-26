import os
from config import get_config
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
import pytz
import logging
from logging.config import dictConfig

import pytz
from utils import RateLimiter, get_client
from dataclasses import dataclass
from collections import defaultdict
from get_stop_names import get_stop_names
from transit_providers.config import get_provider_config
# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('stib')

# Get provider configuration
provider_config = get_provider_config('stib')
logger.debug(f"Provider config: {provider_config}")

# API configuration
API_URL = provider_config.get('API_URL', "")
logger.debug(f"API_URL: {API_URL}")
MESSAGES_API_URL = provider_config.get('STIB_MESSAGES_API_URL', "")
logger.debug(f"MESSAGES_API_URL: {MESSAGES_API_URL}")
WAITING_TIMES_API_URL = provider_config.get('STIB_WAITING_TIME_API_URL', "")
logger.debug(f"WAITING_TIMES_API_URL: {WAITING_TIMES_API_URL}")
GTFS_URL = provider_config.get('GTFS_URL', "")
GTFS_DIR = provider_config.get('GTFS_DIR')
if GTFS_DIR:
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
else:
    logger.error("GTFS_DIR is not set in provider configuration")
    logger.debug(f"Provider config: {provider_config}")
CACHE_DIR = provider_config.get('CACHE_DIR')
if CACHE_DIR:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
else:
    logger.error("CACHE_DIR is not set in provider configuration")
    logger.debug(f"Provider config: {provider_config}")
logger.debug(f"GTFS_DIR: {GTFS_DIR}, CACHE_DIR: {CACHE_DIR}")
GTFS_CACHE_DURATION = provider_config.get('GTFS_CACHE_DURATION')
BASE_URL = provider_config.get('API_URL')

# API keys
API_KEY = provider_config.get('API_KEY')
# Configuration
STIB_STOPS = provider_config.get('STIB_STOPS')
TIMEZONE = pytz.timezone(get_config('TIMEZONE'))
# Cache configuration
CACHE_DIR = get_config('CACHE_DIR') / "stib"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_CACHE_DURATION = get_config('CACHE_DURATION')

# Add this configuration
SHAPES_CACHE_DIR = get_config('CACHE_DIR') / "stib/shapes"
SHAPES_CACHE_DIR.mkdir(parents=True, exist_ok=True)

GTFS_CACHE_DURATION = provider_config.get('GTFS_CACHE_DURATION')

# Add this near the top with other cache variables
waiting_times_cache = {}
WAITING_TIMES_CACHE_DURATION = timedelta(seconds=30)

# Add these near the top with other cache variables
ROUTES_CACHE_FILE = CACHE_DIR / "routes.json"
ROUTES_CACHE_DURATION = timedelta(days=30)
CACHE_DURATION = ROUTES_CACHE_DURATION

# Add this near the top of the file with other global variables
last_api_call = datetime.now(timezone.utc)

# Create a global rate limiter instance
rate_limiter = RateLimiter()

def parse_service_message(message, stop_details):
    """Parse a service message and extract relevant information"""
    try:
        content = json.loads(message['content'])
        lines = json.loads(message['lines'])
        points = json.loads(message['points'])
        
        # Get the English text from the first text block
        text = content[0]['text'][0]['en']
        
        # Get affected stop names
        affected_stops = [stop_details.get(point['id'], {'name': point['id']})['name'] 
                        for point in points]
        
        # Get affected lines
        affected_lines = [line['id'] for line in lines]
        
        return {
            'text': text,
            'lines': affected_lines,
            'points': [point['id'] for point in points],
            'stops': affected_stops,
            'affected_lines': affected_lines
        }
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        import traceback
        logger.error(f"Error parsing message: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None
    
async def get_service_messages(monitored_lines=None, monitored_stops=None):
    """Get service messages for monitored lines and stops"""
    try:
        # Build the filter for stops
        stop_filters = [f"points like '%{stop}%'" for stop in monitored_stops] if monitored_stops else []
        
        # Build the filter for lines
        line_filters = []
        unique_lines = set()
        
        # More robust line extraction
        if monitored_lines:
            if isinstance(monitored_lines, dict):
                unique_lines.update(str(line) for line in monitored_lines.keys())
            elif isinstance(monitored_lines, (set, list)):
                for item in monitored_lines:
                    if isinstance(item, dict):
                        unique_lines.update(str(key) for key in item.keys())
                    else:
                        unique_lines.add(str(item))
            else:
                unique_lines.add(str(monitored_lines))
                
        line_filters = [f"lines like '%{line}%'" for line in unique_lines]
        
        # Combine filters
        where_clause = " or ".join(stop_filters + line_filters)
        
        params = {
            'where': where_clause,
            'limit': 100,
            'apikey': API_KEY
        }
        
        
        logger.debug(f"Service messages API URL: {MESSAGES_API_URL}?{params}")
     
        async with await get_client() as client:
            response = await client.get(MESSAGES_API_URL, params=params)
            # Update rate limits from response headers
            rate_limiter.update_from_headers(response.headers)
            
            
            data = response.json()
            
            # Parse the messages
            parsed_messages = []
            for message in data.get('results', []):
                try:
                    content = json.loads(message['content'])
                    lines = json.loads(message['lines'])
                    points = json.loads(message['points'])
                    
                    # Get the English text from the first text block
                    text = content[0]['text'][0]['en']
                    
                    # Get affected lines
                    affected_lines = [line['id'] for line in lines]

                    # Check if any affected lines are in monitored_lines
                    
                    
                    # Extract just the stop IDs from points and get their names
                    stop_ids = [point['id'] for point in points]
                    is_monitored = (
                        any(stop_id in monitored_stops for stop_id in stop_ids) and 
                        any(line in monitored_lines for line in affected_lines)
                    )
                    affected_stops = [stop_info['name'] for stop_info in get_stop_names(stop_ids).values()]
                    
                    # Skip messages that don't affect any monitored lines
                    if not any(line in monitored_lines for line in affected_lines):
                        continue

                    parsed_messages.append({
                        'text': text,
                        'lines': affected_lines,
                        'points': stop_ids,  # Now just using IDs
                        "stops": affected_stops,
                        'priority': message.get('priority', 0),
                        'type': message.get('type', ''),
                        'is_monitored': is_monitored
                    })
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    logger.error(f"Error parsing message: {e}")
                    continue
            
            return {'messages': parsed_messages}
            
    except Exception as e:
        logger.error(f"Error fetching service messages: {e}")
        import traceback
        logger.error(f"Error fetching service messages: {e}\n{traceback.format_exc()}")
        raise e

class APIError(Exception):
    """Custom exception for API errors"""
    pass

@dataclass
class WaitingTimesCache:
    timestamp: datetime
    data: Dict[str, Any]

async def get_route_colors(monitored_lines=None):
    """Fetch route colors with caching"""
        # If monitored_lines is a string (single line number), convert it to a list
    if isinstance(monitored_lines, str):
        monitored_lines = [monitored_lines]
    # If monitored_lines is a number, convert it to a string in a list
    elif isinstance(monitored_lines, (int, float)):
        monitored_lines = [str(monitored_lines)]
    # Initialize cache structure
    routes_cache = {
        'timestamp': None,
        'data': {}
    }

    # Try to load from file cache first
    try:
        if ROUTES_CACHE_FILE.exists():
            with open(ROUTES_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                routes_cache['data'] = cache_data.get('data', {})
                routes_cache['timestamp'] = datetime.fromisoformat(cache_data['timestamp'])
                logger.debug(f"Loaded route colors from file cache: {routes_cache['data']}")
    except Exception as e:
        logger.error(f"Error loading route colors from file cache: {e}")

    # Initialize empty dictionary for route colors
    route_colors = {}
    
    # Check if cache is valid and contains all requested routes
    if (routes_cache['timestamp'] and 
        routes_cache['data'] and 
        datetime.now() - routes_cache['timestamp'] < CACHE_DURATION and
        (not monitored_lines or all(line in routes_cache['data'] for line in monitored_lines))):
        logger.debug("Using cached route colors")
        return routes_cache['data']
    
    logger.debug("Fetching fresh route colors")
    url = "https://stibmivb.opendatasoft.com/api/explore/v2.1/catalog/datasets/gtfs-routes-production/records"
    
    params = {
        'limit': 100,  # Get all routes
        'apikey': API_KEY
    }
    
    # Add filter if we have specific lines we're interested in
    if monitored_lines:
        conditions = [f'route_short_name="{line}"' for line in monitored_lines]
        params['where'] = ' or '.join(conditions)
    
    try:
        async with await get_client() as client:
            # Check rate limits before making request
            if not rate_limiter.can_make_request():
                logger.warning("Rate limit exceeded, using cached colors")
                return routes_cache.get('data', {})
            response = await client.get(url, params=params)
            # Update rate limits from response headers
            rate_limiter.update_from_headers(response.headers)
            
            
            data = response.json()
            
            # Create dictionary mapping route numbers to colors
            for route in data['results']:
                route_number = route['route_short_name']
                route_color = route.get('route_color', '')
                if route_color:
                    route_colors[route_number] = f"#{route_color}"
            
            # Update cache
            routes_cache['timestamp'] = datetime.now()
            routes_cache['data'] = route_colors
            
            # Also save to file cache
            try:
                with open(ROUTES_CACHE_FILE, 'w') as f:
                    json.dump({
                        'timestamp': routes_cache['timestamp'].isoformat(),
                        'data': route_colors
                    }, f)
            except Exception as e:
                import traceback
                logger.error(f"Error saving routes cache: {e}\n{traceback.format_exc()}")
            
            return route_colors
            
    except Exception as e:
        import traceback
        logger.error(f"Error fetching route colors: {e}\n{traceback.format_exc()}")
        # Try to load from file cache if API fails
        try:
            if ROUTES_CACHE_FILE.exists():
                with open(ROUTES_CACHE_FILE, 'r') as f:
                    cache_data = json.load(f)
                    cache_timestamp = datetime.fromisoformat(cache_data['timestamp'])
                    if datetime.now() - cache_timestamp < CACHE_DURATION:
                        return cache_data['data']
        except Exception as cache_e:
            logger.error(f"Error loading routes cache: {cache_e}\n{traceback.format_exc()}")
        
        # Return empty dictionary if everything fails
        return route_colors

# Initialize routes_cache at startup
routes_cache = {
    'timestamp': None,
    'data': None
}


async def get_vehicle_positions():
    """Get real-time vehicle positions from STIB API"""
    try:
        # Filter for our monitored lines
        monitored_lines = set()
        for stop in STIB_STOPS:
            if 'lines' in stop:
                monitored_lines.update(stop['lines'])
        
        # The correct filter syntax for the API
        lines_filter = " or ".join([f'lineid="{line}"' for line in monitored_lines])
        
        params = {
            'where': f'({lines_filter})',
            'limit': 100,
            'apikey': API_KEY
        }
        
        async with await get_client() as client:
            base_url = 'https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/vehicle-position-rt-production/records'
            # Check if we've exceeded quota or have low remaining requests
            if not rate_limiter.can_make_request() or (rate_limiter.remaining is not None and rate_limiter.remaining < 1000):
                logger.warning("Skipping vehicle positions due to rate limit constraints")
                return {}
                
            response = await client.get(
                base_url,
                params=params
            )
            # Update rate limits from response headers
            rate_limiter.update_from_headers(response.headers)
            
            data = response.json()
            
            # Transform into our expected format
            positions = defaultdict(lambda: defaultdict(list))
            
            # Process each vehicle record
            for record in data.get('results', []):
                try:
                    line_id = str(record.get('lineid'))
                    # Parse the nested vehiclepositions JSON string
                    vehicle_positions = json.loads(record.get('vehiclepositions', '[]'))
                    
                    for position in vehicle_positions:
                        direction = str(position.get('directionId'))
                        point_id = str(position.get('pointId'))
                        distance = position.get('distanceFromPoint')
                        
                        # Skip invalid data
                        if not all([direction, point_id]) or distance is None:
                            continue
                        
                        position_data = {
                            'distance': distance,
                            'next_stop': point_id
                        }
                        
                        positions[line_id][direction].append(position_data)
                        logger.debug(f"Added position data for line {line_id} ({direction}): {position_data}")
                    
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.error(f"Error processing vehicle position for line {line_id}: {e}")
                    continue
            
            # Filter out any remaining entries with invalid keys
            return {
                line: {
                    dir_id: pos_list
                    for dir_id, pos_list in directions.items()
                    if dir_id != 'None' and pos_list
                }
                for line, directions in dict(positions).items()
                if line != 'None'
            }
            
    except Exception as e:
        logger.error(f"Error fetching vehicle positions: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {}

async def get_waiting_times(stop_id: str = None) -> Dict[str, Any]:
    """Get real-time waiting times for STIB stops
    
    Args:
        stop_id: Optional stop ID to filter results. Example of a valid stop_id: 8122 (ROODEBEEK)
        
    Returns:
        Dictionary containing waiting times data in the format:
        {
            "stops": {
                "stop_id": {
                    "name": "Stop Name",
                    "coordinates": {"lat": 50.8, "lon": 4.3},
                    "lines": {
                        "line_number": {
                            "destination": [{
                                "minutes": 5,
                                "message": "",
                                "formatted_time": "14:30"
                            }]
                        }
                    }
                }
            }
        }
    """
    try:
        params = {
            'apikey': API_KEY,
            'limit': 100
        }
        
        if stop_id:
            params['where'] = f'pointid="{stop_id}"'
            
        async with await get_client() as client:
            response = await client.get(API_URL, params=params)
            rate_limiter.update_from_headers(response.headers)
            
            data = response.json()
            formatted_data = {"stops": {}}
            
            for record in data.get('results', []):
                try:
                    stop_id = str(record.get('pointid'))
                    line = str(record.get('lineid'))
                    
                    # Initialize stop data if needed
                    if stop_id not in formatted_data["stops"]:
                        stop_names = get_stop_names([stop_id])
                        formatted_data["stops"][stop_id] = {
                            "name": stop_names.get(stop_id, {}).get('name', stop_id),
                            "coordinates": stop_names.get(stop_id, {}).get('coordinates', {}),
                            "lines": {}
                        }
                    
                    # Process passing times
                    passing_times = json.loads(record.get('passingtimes', '[]'))
                    
                    for passing_time in passing_times:
                        destination = passing_time.get('destination', {}).get('fr', 'Unknown')
                        
                        # Initialize line data if needed
                        if line not in formatted_data["stops"][stop_id]["lines"]:
                            formatted_data["stops"][stop_id]["lines"][line] = {}
                        
                        if destination not in formatted_data["stops"][stop_id]["lines"][line]:
                            formatted_data["stops"][stop_id]["lines"][line][destination] = []
                        
                        # Calculate minutes until arrival
                        expected_time = passing_time.get('expectedArrivalTime')
                        if expected_time:
                            arrival_dt = datetime.fromisoformat(expected_time)
                            if arrival_dt.tzinfo is None:
                                arrival_dt = TIMEZONE.localize(arrival_dt)
                            
                            now = datetime.now(TIMEZONE)
                            minutes = int((arrival_dt - now).total_seconds() // 60)
                            formatted_time = arrival_dt.strftime('%H:%M')
                            
                            formatted_data["stops"][stop_id]["lines"][line][destination].append({
                                "minutes": minutes,
                                "message": passing_time.get('message', {}).get('en', ''),
                                "formatted_time": formatted_time
                            })
                
                except Exception as e:
                    logger.error(f"Error processing record: {e}")
                    continue
            
            return formatted_data
            
    except Exception as e:
        logger.error(f"Error fetching waiting times: {e}")
        return {"stops": {}}

async def get_route_data(line: str) -> Dict[str, Any]:
    """Get route data for a specific line
    
    Args:
        line: Line number
        
    Returns:
        Dictionary containing route variants with stops and shapes
    """
    try:
        # Get route variants from validate_stops
        from validate_stops import validate_line_stops
        route_variants = await validate_line_stops(line)
        
        if not route_variants:
            return None
            
        return {line: route_variants}
        
    except Exception as e:
        logger.error(f"Error getting route data: {e}")
        return None
