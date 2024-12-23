"""BKK (Budapest) transit provider API implementation"""

import os
from datetime import datetime, timezone, timedelta
import logging
from logging.config import dictConfig
from pathlib import Path
import asyncio
from typing import Dict, List, Optional, TypedDict, Any, Union, Tuple
import httpx
from google.transit import gtfs_realtime_pb2
from mobility_db_api import MobilityAPI
from transit_providers.config import get_provider_config
from config import get_config
from transit_providers.nearest_stop import (
    ingest_gtfs_stops, get_nearest_stops, cache_stops, 
    get_cached_stops, Stop, get_stop_by_name as generic_get_stop_by_name
)

# Export public API functions
__all__ = [
    'get_vehicle_positions',
    'get_waiting_times',
    'get_service_alerts',
    'get_static_data',
    'bkk_config',
    'get_line_info',
    'get_route_shapes',
    'get_route_variants_api',
    'get_line_colors'
]

# Setup logging
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)

# Add handler for BKK provider if not exists
if 'handlers' not in logging_config:
    logging_config['handlers'] = {}
if 'loggers' not in logging_config:
    logging_config['loggers'] = {}

logging_config['handlers']['bkk_file'] = {
    'class': 'logging.handlers.RotatingFileHandler',
    'filename': str(Path('logs/bkk.log').absolute()),
    'maxBytes': 1024 * 1024,  # 1MB
    'backupCount': 3,
    'formatter': 'standard',
    'level': 'DEBUG'
}

logging_config['loggers']['bkk'] = {
    'handlers': ['bkk_file', 'file'],
    'level': 'DEBUG',
    'propagate': True
}

dictConfig(logging_config)
logger = logging.getLogger('bkk')

# Get provider configuration
provider_config = get_provider_config('bkk')

# Constants from config
CACHE_DIR = provider_config.get('CACHE_DIR')
GTFS_DIR = provider_config.get('GTFS_DIR')
API_KEY = provider_config.get('API_KEY')
PROVIDER_ID = provider_config.get('PROVIDER_ID', 'mdb-990')  # BKK's ID in Mobility DB
MONITORED_LINES = provider_config.get('MONITORED_LINES', [])
STOP_IDS = provider_config.get('STOP_IDS', [])

# Create necessary directories
if CACHE_DIR:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
if GTFS_DIR:
    GTFS_DIR.mkdir(parents=True, exist_ok=True)

# GTFS-realtime endpoints
VEHICLE_POSITIONS_URL = f'https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/VehiclePositions.pb?key={API_KEY}'
TRIP_UPDATES_URL = f'https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/TripUpdates.pb?key={API_KEY}'
ALERTS_URL = f'https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/Alerts.pb?key={API_KEY}'

# Cache for scheduled stop times
_stop_times_cache = {}
_last_cache_update = None
_CACHE_DURATION = timedelta(hours=3)

# Cache for stop and route information
_stops_cache = {}
_routes_cache = {}
_stops_cache_update = None
_routes_cache_update = None

def _load_stop_times_cache() -> None:
    """Load scheduled stop times for monitored routes into cache"""
    global _stop_times_cache, _last_cache_update
    
    try:
        gtfs_path = _get_current_gtfs_path()
        if not gtfs_path:
            return
            
        # Get monitored routes and stops
        config = get_provider_config('bkk')
        monitored_lines = config.get('MONITORED_LINES', [])
        stop_ids = config.get('STOP_IDS', [])
        
        # First get trip IDs for monitored routes
        trips_file = gtfs_path / 'trips.txt'
        monitored_trips = set()
        
        with open(trips_file, 'r', encoding='utf-8') as f:
            header = next(f).strip().split(',')
            trip_id_index = header.index('trip_id')
            route_id_index = header.index('route_id')
            
            for line in f:
                fields = line.strip().split(',')
                route_id = fields[route_id_index]
                if route_id in monitored_lines:
                    monitored_trips.add(fields[trip_id_index])
        
        # Read stop_times.txt for monitored trips
        stop_times_file = gtfs_path / 'stop_times.txt'
        new_cache = {}
        
        with open(stop_times_file, 'r', encoding='utf-8') as f:
            header = next(f).strip().split(',')
            trip_id_index = header.index('trip_id')
            stop_id_index = header.index('stop_id')
            stop_sequence_index = header.index('stop_sequence')
            arrival_time_index = header.index('arrival_time')
            
            for line in f:
                fields = line.strip().split(',')
                trip_id = fields[trip_id_index]
                stop_id = fields[stop_id_index]
                
                if trip_id in monitored_trips and (not stop_ids or stop_id in stop_ids):
                    cache_key = (trip_id, stop_id, int(fields[stop_sequence_index]))
                    time_str = fields[arrival_time_index]
                    hours, minutes, _ = map(int, time_str.split(':'))
                    
                    # Handle times past midnight (hours > 24)
                    if hours >= 24:
                        hours = hours % 24
                    
                    new_cache[cache_key] = (hours, minutes)
        
        _stop_times_cache = new_cache
        _last_cache_update = datetime.now(timezone.utc)
        logger.info(f"Updated stop times cache with {len(_stop_times_cache)} entries")
        
    except Exception as e:
        logger.error(f"Error loading stop times cache: {e}")

def _load_stops_cache() -> None:
    """Load stop information from GTFS data into cache"""
    global _stops_cache, _stops_cache_update
    
    try:
        gtfs_path = _get_current_gtfs_path()
        if not gtfs_path:
            return
            
        stops_file = gtfs_path / 'stops.txt'
        if not stops_file.exists():
            return
            
        new_cache = {}
        with open(stops_file, 'r', encoding='utf-8') as f:
            import csv
            reader = csv.DictReader(f)
            
            for row in reader:
                stop_id = row['stop_id'].strip()
                try:
                    new_cache[stop_id] = {
                        'name': row['stop_name'].strip(),
                        'lat': float(row['stop_lat'].strip()),
                        'lon': float(row['stop_lon'].strip())
                    }
                except (ValueError, KeyError) as e:
                    logger.error(f"Error parsing stop data for {stop_id}: {e}")
                    continue
        
        _stops_cache = new_cache
        _stops_cache_update = datetime.now(timezone.utc)
        logger.info(f"Updated stops cache with {len(_stops_cache)} entries")
        
    except Exception as e:
        logger.error(f"Error loading stops cache: {e}")

def _load_routes_cache() -> None:
    """Load route information from GTFS data into cache"""
    global _routes_cache, _routes_cache_update
    
    try:
        gtfs_path = _get_current_gtfs_path()
        if not gtfs_path:
            return
            
        routes_file = gtfs_path / 'routes.txt'
        if not routes_file.exists():
            return
            
        new_cache = {}
        with open(routes_file, 'r', encoding='utf-8') as f:
            header = next(f).strip().split(',')
            route_id_index = header.index('route_id')
            route_short_name_index = header.index('route_short_name')
            route_desc_index = header.index('route_desc') if 'route_desc' in header else -1
            
            for line in f:
                fields = line.strip().split(',')
                route_id = fields[route_id_index]
                new_cache[route_id] = {
                    'route_short_name': fields[route_short_name_index],
                    'route_desc': fields[route_desc_index] if route_desc_index >= 0 else None
                }
        
        _routes_cache = new_cache
        _routes_cache_update = datetime.now(timezone.utc)
        logger.info(f"Updated routes cache with {len(_routes_cache)} entries")
        
    except Exception as e:
        logger.error(f"Error loading routes cache: {e}")

def _get_scheduled_time(trip_id: str, stop_id: str, stop_sequence: int) -> Optional[datetime]:
    """Get scheduled arrival time from cache or static GTFS data"""
    global _last_cache_update
    
    # Update cache if needed
    now = datetime.now(timezone.utc)
    if not _last_cache_update or (now - _last_cache_update) > _CACHE_DURATION:
        _load_stop_times_cache()
    
    try:
        # Try to get from cache
        cache_key = (trip_id, stop_id, stop_sequence)
        if cache_key in _stop_times_cache:
            hours, minutes = _stop_times_cache[cache_key]
            
            # Create datetime in local timezone (Budapest)
            from zoneinfo import ZoneInfo
            budapest_tz = ZoneInfo('Europe/Budapest')
            now_local = datetime.now(budapest_tz)
            scheduled = now_local.replace(
                hour=hours,
                minute=minutes,
                second=0,
                microsecond=0
            )
            
            # If the scheduled time is more than 12 hours in the past,
            # it's probably for tomorrow
            if (now_local - scheduled).total_seconds() > 12 * 3600:
                scheduled += timedelta(days=1)
            
            # Convert to UTC
            return scheduled.astimezone(timezone.utc)
            
        return None
        
    except Exception as e:
        logger.error(f"Error getting scheduled time from cache for trip {trip_id}, stop {stop_id}: {e}")
        return None

def _get_stop_info(stop_id: str) -> Dict[str, Any]:
    """Get stop information from cache"""
    global _stops_cache_update
    
    # Update cache if needed
    now = datetime.now(timezone.utc)
    if not _stops_cache_update or (now - _stops_cache_update) > _CACHE_DURATION:
        _load_stops_cache()
    
    # Return cached info or default with actual stop name from cache
    if stop_id in _stops_cache:
        return _stops_cache[stop_id]
    else:
        logger.warning(f"Stop {stop_id} not found in GTFS data")
        return {'name': f"Unknown stop ({stop_id})", 'lat': None, 'lon': None}

def _get_route_info(route_id: str) -> Dict[str, Any]:
    """Get route information from cache"""
    global _routes_cache_update
    
    # Update cache if needed
    now = datetime.now(timezone.utc)
    if not _routes_cache_update or (now - _routes_cache_update) > _CACHE_DURATION:
        _load_routes_cache()
    
    return _routes_cache.get(route_id, {'route_short_name': route_id, 'route_desc': None})

class GTFSManager:
    """Manages GTFS data download and caching using mobility-db-api"""
    
    def __init__(self):
        if not GTFS_DIR:
            raise ValueError("GTFS_DIR is not set in provider configuration")
        self.mobility_api = MobilityAPI(
            data_dir=str(GTFS_DIR),
            refresh_token=os.getenv('MOBILITY_API_REFRESH_TOKEN')
        )
        
    async def ensure_gtfs_data(self) -> Optional[Path]:
        """Ensure GTFS data is downloaded and up to date"""
        try:
            # Create GTFS directory if it doesn't exist
            if GTFS_DIR:
                GTFS_DIR.mkdir(parents=True, exist_ok=True)
            else:
                logger.error("GTFS_DIR is not set in provider configuration")
                return None
            
            # Check if we need to download new data
            datasets = self.mobility_api.datasets
            current_dataset = next(
                (d for d in datasets.values() if d.provider_id == PROVIDER_ID), 
                None
            )
            
            if not current_dataset or self._is_dataset_expired(current_dataset):
                logger.info("Downloading fresh GTFS data")
                dataset_path = self.mobility_api.download_latest_dataset(PROVIDER_ID)
                if not dataset_path:
                    logger.error("Failed to download GTFS data")
                    return None
                return Path(dataset_path)
            
            return Path(current_dataset.download_path)
            
        except Exception as e:
            logger.error(f"Error ensuring GTFS data: {e}")
            return None
            
    def _is_dataset_expired(self, dataset) -> bool:
        """Check if dataset needs updating"""
        if not dataset.feed_end_date:
            return True
            
        # Convert string to datetime if needed
        if isinstance(dataset.feed_end_date, str):
            try:
                end_date = datetime.fromisoformat(dataset.feed_end_date)
            except ValueError:
                # If we can't parse the date, consider it expired
                return True
        else:
            end_date = dataset.feed_end_date
            
        # Ensure we're comparing timezone-aware datetimes
        now = datetime.now(timezone.utc)
        if not end_date.tzinfo:
            end_date = end_date.replace(tzinfo=timezone.utc)
            
        # Update if less than 7 days until expiry
        days_until_expiry = (end_date - now).days
        return days_until_expiry < 7

async def get_stops() -> Dict[str, Stop]:
    """Get all stops from GTFS data"""
    cache_path = CACHE_DIR / 'stops.json'
    
    # Try cache first
    cached_stops = get_cached_stops(cache_path)
    if cached_stops:
        return cached_stops
        
    # Get fresh GTFS data if needed
    gtfs_manager = GTFSManager()
    gtfs_dir = await gtfs_manager.ensure_gtfs_data()
    if not gtfs_dir:
        return {}
        
    # Load and cache stops
    stops = ingest_gtfs_stops(gtfs_dir)
    if stops:
        cache_stops(stops, cache_path)
    return stops

async def get_vehicle_positions() -> List[Dict]:
    """Get current vehicle positions.
    
    Returns:
        List[Dict]: List of vehicle position dictionaries with provider information
    """
    try:
        # Get latest config
        config = get_provider_config('bkk')
        monitored_lines = config.get('MONITORED_LINES', [])
        logger.debug(f"Monitoring lines: {monitored_lines}")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(VEHICLE_POSITIONS_URL)
            response.raise_for_status()
            
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            logger.debug(f"Parsed protobuf feed with {len(feed.entity)} entities")
            
            vehicles = []
            for entity in feed.entity:
                if not entity.HasField('vehicle'):
                    logger.debug("Entity does not have vehicle field")
                    continue
                    
                vehicle = entity.vehicle
                if not vehicle.trip.route_id:
                    logger.debug("Vehicle does not have route_id")
                    continue
                    
                line_id = _get_line_id_from_trip(vehicle.trip.route_id)
                logger.debug(f"Found vehicle with route_id {vehicle.trip.route_id}, extracted line_id {line_id}")
                
                if monitored_lines and line_id not in monitored_lines:
                    logger.debug(f"Skipping vehicle for line {line_id} as it's not in monitored lines")
                    continue
                    
                vehicles.append({
                    'id': vehicle.vehicle.id,
                    'line': line_id,
                    'lat': vehicle.position.latitude,
                    'lon': vehicle.position.longitude,
                    'bearing': vehicle.position.bearing if vehicle.position.HasField('bearing') else None,
                    'destination': _get_destination_from_trip(vehicle.trip.trip_id),
                    'timestamp': datetime.fromtimestamp(vehicle.timestamp, timezone.utc).isoformat(),
                    'provider': 'bkk'
                })
            
            logger.debug(f"Found {len(vehicles)} vehicles for monitored lines")
            return vehicles
    except Exception as e:
        logger.error(f"Error getting vehicle positions: {e}")
        return []

async def get_waiting_times() -> Dict:
    """Get waiting times for monitored stops."""
    try:
        # Get latest config
        config = get_provider_config('bkk')
        monitored_lines = config.get('MONITORED_LINES', [])
        stop_ids = config.get('STOP_IDS', [])
        
        async with httpx.AsyncClient() as client:
            response = await client.get(TRIP_UPDATES_URL)
            response.raise_for_status()
            
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            formatted_data = {"stops_data": {}}
            
            for entity in feed.entity:
                if not entity.HasField('trip_update'):
                    continue
                    
                trip = entity.trip_update
                line_id = _get_line_id_from_trip(trip.trip.route_id)
                if monitored_lines and line_id not in monitored_lines:
                    continue
                
                destination = _get_destination_from_trip(trip.trip.trip_id)
                route_info = _get_route_info(line_id)
                
                for stop_time in trip.stop_time_update:
                    stop_id = stop_time.stop_id
                    if stop_ids and stop_id not in stop_ids:
                        continue
                        
                    # Get stop info from cache
                    stop_info = _get_stop_info(stop_id)
                        
                    # Initialize stop data if needed
                    if stop_id not in formatted_data["stops_data"]:
                        formatted_data["stops_data"][stop_id] = {
                            "name": stop_info['name'],
                            "coordinates": {
                                "lat": stop_info['lat'],
                                "lon": stop_info['lon']
                            } if stop_info['lat'] and stop_info['lon'] else None,
                            "lines": {}
                        }
                    
                    # Initialize line data if needed
                    if line_id not in formatted_data["stops_data"][stop_id]["lines"]:
                        formatted_data["stops_data"][stop_id]["lines"][line_id] = {
                            "_metadata": {
                                "route_short_name": route_info['route_short_name'],
                                "route_desc": route_info['route_desc']
                            }
                        }
                    
                    # Initialize destination data if needed
                    if destination not in formatted_data["stops_data"][stop_id]["lines"][line_id]:
                        formatted_data["stops_data"][stop_id]["lines"][line_id][destination] = []
                        
                    if stop_time.HasField('arrival'):
                        now = datetime.now(timezone.utc)
                        
                        # Get actual arrival time in UTC
                        arrival_time_utc = datetime.fromtimestamp(stop_time.arrival.time, timezone.utc)
                        
                        # Convert to Budapest time for display
                        from zoneinfo import ZoneInfo
                        budapest_tz = ZoneInfo('Europe/Budapest')
                        arrival_time = arrival_time_utc.astimezone(budapest_tz)
                        
                        # Calculate minutes for display (in local time)
                        now_local = now.astimezone(budapest_tz)
                        realtime_minutes = int((arrival_time - now_local).total_seconds() / 60)
                        
                        # Get scheduled time from static GTFS data (already in UTC)
                        scheduled_time_utc = _get_scheduled_time(
                            trip.trip.trip_id,
                            stop_id,
                            stop_time.stop_sequence
                        )
                        
                        if scheduled_time_utc:
                            # Convert scheduled time to local for display
                            scheduled_time = scheduled_time_utc.astimezone(budapest_tz)
                            scheduled_minutes = int((scheduled_time - now_local).total_seconds() / 60)
                            
                            # Calculate delay in seconds with full precision
                            delay_seconds = int((arrival_time_utc - scheduled_time_utc).total_seconds())
                        else:
                            scheduled_time = arrival_time
                            scheduled_minutes = realtime_minutes
                            delay_seconds = 0
                        
                        # Skip if both scheduled and realtime are in the past
                        if scheduled_minutes < 0 and realtime_minutes < 0:
                            continue
                            
                        formatted_data["stops_data"][stop_id]["lines"][line_id][destination].append({
                            "delay": delay_seconds,
                            "is_realtime": delay_seconds != 0,  # Only realtime if there's an actual delay
                            "message": None,  # BKK doesn't provide message per arrival
                            "realtime_minutes": f"{realtime_minutes}'",
                            "realtime_time": arrival_time.strftime("%H:%M"),
                            "scheduled_minutes": f"{scheduled_minutes}'",
                            "scheduled_time": scheduled_time.strftime("%H:%M"),
                            "provider": "bkk"
                        })
            
            # Sort waiting times by arrival time for each destination
            for stop_id, stop_data in formatted_data["stops_data"].items():
                for line_id, line_data in stop_data["lines"].items():
                    for destination, times in line_data.items():
                        if destination != "_metadata":  # Skip metadata when sorting
                            times.sort(key=lambda x: datetime.strptime(x["realtime_time"], "%H:%M"))
            
            return formatted_data
    except Exception as e:
        logger.error(f"Error getting waiting times: {e}")
        return {"stops_data": {}}

async def get_service_alerts() -> List[Dict]:
    """Get current service alerts.
    
    Returns:
        List[Dict]: List of service alert dictionaries with provider information
    """
    try:
        # Get latest config
        config = get_provider_config('bkk')
        monitored_lines = config.get('MONITORED_LINES', [])
        
        async with httpx.AsyncClient() as client:
            response = await client.get(ALERTS_URL)
            response.raise_for_status()
            
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            alerts = []
            for entity in feed.entity:
                if not entity.HasField('alert'):
                    continue
                    
                alert = entity.alert
                affected_lines = set()
                for informed_entity in alert.informed_entity:
                    if informed_entity.HasField('route_id'):
                        line_id = _get_line_id_from_trip(informed_entity.route_id)
                        if not monitored_lines or line_id in monitored_lines:
                            affected_lines.add(line_id)
                
                if not affected_lines:
                    continue
                    
                alerts.append({
                    'id': entity.id,
                    'lines': list(affected_lines),
                    'title': _get_translated_text(alert.header_text),
                    'description': _get_translated_text(alert.description_text),
                    'start': datetime.fromtimestamp(alert.active_period[0].start, timezone.utc).isoformat() if alert.active_period and alert.active_period[0].HasField('start') else None,
                    'end': datetime.fromtimestamp(alert.active_period[0].end, timezone.utc).isoformat() if alert.active_period and alert.active_period[0].HasField('end') else None,
                    'provider': 'bkk'
                })
            
            return alerts
    except Exception as e:
        logger.error(f"Error getting service alerts: {e}")
        return []

# Helper functions
def _get_current_gtfs_path() -> Optional[Path]:
    """Get the path to the current GTFS dataset"""
    try:
        # First try reading from metadata file
        metadata_file = GTFS_DIR / 'datasets_metadata.json'
        if metadata_file.exists():
            import json
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
                # Find the latest BKK dataset
                bkk_datasets = [
                    (k, v) for k, v in metadata.items() 
                    if v['provider_id'] == PROVIDER_ID
                ]
                if bkk_datasets:
                    # Sort by download date and get the latest
                    latest = sorted(
                        bkk_datasets,
                        key=lambda x: datetime.fromisoformat(x[1]['download_date']),
                        reverse=True
                    )[0]
                    return Path(latest[1]['download_path'])
        
        # Fallback to using MobilityAPI
        mobility_api = MobilityAPI(
            data_dir=str(GTFS_DIR),
            refresh_token=os.getenv('MOBILITY_API_REFRESH_TOKEN')
        )
        datasets = mobility_api.datasets
        current_dataset = next(
            (d for d in datasets.values() if d.provider_id == PROVIDER_ID),
            None
        )
        if current_dataset:
            return Path(current_dataset.download_path)
        
        return None
    except Exception as e:
        logger.error(f"Error getting current GTFS path: {e}")
        return None

def _get_line_id_from_trip(route_id: str) -> str:
    """Extract line ID from route ID based on GTFS data structure"""
    try:
        # First try direct route ID to route short name mapping from routes.txt
        gtfs_dir = GTFS_DIR
        if not gtfs_dir.exists():
            return route_id  # Return original ID if GTFS data is not available
            
        gtfs_path = _get_current_gtfs_path()
        if not gtfs_path:
            return route_id
            
        routes_file = gtfs_path / 'routes.txt'
        if routes_file.exists():
            with open(routes_file, 'r', encoding='utf-8') as rf:
                # Skip header line
                header = next(rf).strip().split(',')
                route_id_index = header.index('route_id')
                route_short_name_index = header.index('route_short_name')
                
                for route_line in rf:
                    fields = route_line.strip().split(',')
                    if len(fields) > max(route_id_index, route_short_name_index) and fields[route_id_index] == route_id:
                        # Found the route, return the route_id as is since it's already in the correct format
                        return route_id
        
        # If not found in routes.txt, return the route_id as is
        # The real-time feed uses the same format as our monitored lines
        return route_id
    except Exception as e:
        logger.error(f"Error extracting line ID from route {route_id}: {e}")
        return route_id  # Return original ID if something goes wrong

def _get_destination_from_trip(trip_id: str) -> str:
    """Extract destination from trip ID based on GTFS data structure"""
    try:
        # Load trip information from GTFS data
        gtfs_dir = GTFS_DIR
        if not gtfs_dir.exists():
            return ''
            
        gtfs_path = _get_current_gtfs_path()
        if not gtfs_path:
            return ''
            
        trips_file = gtfs_path / 'trips.txt'
        if not trips_file.exists():
            return ''
            
        with open(trips_file, 'r', encoding='utf-8') as f:
            # Skip header line
            header = next(f).strip().split(',')
            trip_id_index = header.index('trip_id')
            trip_headsign_index = header.index('trip_headsign')
            
            for line in f:
                fields = line.strip().split(',')
                if len(fields) > max(trip_id_index, trip_headsign_index) and fields[trip_id_index] == trip_id:
                    # Remove quotes if present
                    headsign = fields[trip_headsign_index].strip('"')
                    return headsign
        return ''
    except Exception as e:
        logger.error(f"Error getting destination for trip {trip_id}: {e}")
        return ''

def _format_minutes_until(dt: datetime) -> str:
    """Format minutes until given datetime"""
    # Ensure both datetimes are timezone-aware
    now = datetime.now(timezone.utc)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Calculate difference in minutes, rounding to nearest minute
    diff = (dt - now).total_seconds() / 60
    minutes = round(diff)
    return f"{minutes}'"

def _get_translated_text(text_container) -> str:
    """Get text in preferred language from GTFS-RT TranslatedString"""
    # First try Hungarian
    for translation in text_container.translation:
        if translation.language == 'hu':
            return translation.text
    
    # Fallback to first available translation
    if text_container.translation:
        return text_container.translation[0].text
    return ""

async def get_static_data() -> Dict[str, Any]:
    """Get static data for the BKK provider.
    
    Returns:
        Dict[str, Any]: Static data including line info and route shapes
    """
    try:
        # Get line information for monitored lines
        line_info = await get_line_info()
        
        # Get route shapes for monitored lines
        route_shapes = await get_route_shapes()
        
        return {
            'provider': 'bkk',
            'line_info': line_info,
            'route_shapes': route_shapes
        }
    except Exception as e:
        logger.error(f"Error getting static data: {e}")
        return {
            'provider': 'bkk',
            'line_info': {},
            'route_shapes': {}
        }

async def bkk_config() -> Dict[str, Any]:
    """Get BKK provider configuration.
    
    Returns:
        Dict[str, Any]: Provider configuration
    """
    return {
        'name': 'BKK',
        'city': 'Budapest',
        'country': 'Hungary',
        'monitored_lines': MONITORED_LINES,
        'stop_ids': STOP_IDS,
        'capabilities': {
            'has_vehicle_positions': True,
            'has_waiting_times': True,
            'has_service_alerts': True,
            'has_line_info': True,
            'has_route_shapes': True
        }
    }

async def get_line_info() -> Dict[str, Dict[str, Any]]:
    """Get information about all monitored lines, including display names and colors.
    
    Returns:
        Dict[str, Dict[str, Any]]: Dictionary mapping route_ids to their information
    """
    try:
        gtfs_path = _get_current_gtfs_path()
        if not gtfs_path:
            return {}
            
        line_info = {}
        routes_file = gtfs_path / 'routes.txt'
        
        if not routes_file.exists():
            logger.error(f"Routes file not found at {routes_file}")
            return {}
            
        with open(routes_file, 'r', encoding='utf-8') as f:
            # Read header
            header = f.readline().strip().split(',')
            route_id_index = header.index('route_id')
            route_short_name_index = header.index('route_short_name')
            route_long_name_index = header.index('route_long_name') if 'route_long_name' in header else -1
            route_type_index = header.index('route_type') if 'route_type' in header else -1
            route_color_index = header.index('route_color') if 'route_color' in header else -1
            route_text_color_index = header.index('route_text_color') if 'route_text_color' in header else -1
            
            # Read routes
            for line in f:
                # Split by comma but preserve quoted fields
                fields = []
                current_field = []
                in_quotes = False
                for char in line.strip():
                    if char == '"':
                        in_quotes = not in_quotes
                    elif char == ',' and not in_quotes:
                        fields.append(''.join(current_field))
                        current_field = []
                    else:
                        current_field.append(char)
                fields.append(''.join(current_field))
                
                # Remove quotes from fields
                fields = [f.strip('"') for f in fields]
                
                route_id = fields[route_id_index]
                
                # Only include monitored lines
                if route_id not in MONITORED_LINES:
                    continue
                    
                info = {
                    'route_id': route_id,
                    'display_name': fields[route_short_name_index],
                    'provider': 'bkk'
                }
                
                # Add optional fields if available
                if route_long_name_index >= 0:
                    info['long_name'] = fields[route_long_name_index]
                if route_type_index >= 0:
                    info['route_type'] = int(fields[route_type_index])
                if route_color_index >= 0 and len(fields) > route_color_index:
                    color = fields[route_color_index].strip()
                    if color:
                        info['color'] = f"#{color}"
                if route_text_color_index >= 0 and len(fields) > route_text_color_index:
                    text_color = fields[route_text_color_index].strip()
                    if text_color:
                        info['text_color'] = f"#{text_color}"
                
                line_info[route_id] = info
        
        return line_info
    except Exception as e:
        logger.error(f"Error getting line information: {e}")
        return {}

async def get_route_shapes() -> Dict[str, List[Dict[str, float]]]:
    """Get route shapes for all monitored lines.
    
    Returns:
        Dict[str, List[Dict[str, float]]]: Dictionary mapping route_ids to their shape coordinates
    """
    try:
        gtfs_path = _get_current_gtfs_path()
        if not gtfs_path:
            return {}
            
        # First get shape IDs for monitored lines from trips.txt
        shape_ids = set()
        trips_file = gtfs_path / 'trips.txt'
        
        if not trips_file.exists():
            logger.error(f"Trips file not found at {trips_file}")
            return {}
            
        with open(trips_file, 'r', encoding='utf-8') as f:
            # Read header
            header = f.readline().strip().split(',')
            route_id_index = header.index('route_id')
            shape_id_index = header.index('shape_id') if 'shape_id' in header else -1
            
            if shape_id_index < 0:
                logger.error("No shape_id column found in trips.txt")
                return {}
                
            # Read trips
            for line in f:
                fields = line.strip().split(',')
                route_id = fields[route_id_index].strip('"')
                
                # Only include monitored lines
                if route_id not in MONITORED_LINES:
                    continue
                    
                shape_id = fields[shape_id_index].strip('"')
                shape_ids.add(shape_id)
        
        # Now get coordinates for each shape from shapes.txt
        shapes_file = gtfs_path / 'shapes.txt'
        route_shapes = {route_id: [] for route_id in MONITORED_LINES}
        
        if not shapes_file.exists():
            logger.error(f"Shapes file not found at {shapes_file}")
            return {}
            
        with open(shapes_file, 'r', encoding='utf-8') as f:
            # Read header
            header = f.readline().strip().split(',')
            shape_id_index = header.index('shape_id')
            lat_index = header.index('shape_pt_lat')
            lon_index = header.index('shape_pt_lon')
            sequence_index = header.index('shape_pt_sequence')
            
            # Read shapes
            shape_points = {}
            for line in f:
                fields = line.strip().split(',')
                shape_id = fields[shape_id_index].strip('"')
                
                # Only include monitored shapes
                if shape_id not in shape_ids:
                    continue
                    
                lat = float(fields[lat_index])
                lon = float(fields[lon_index])
                sequence = int(fields[sequence_index])
                
                if shape_id not in shape_points:
                    shape_points[shape_id] = []
                shape_points[shape_id].append((sequence, {'lat': lat, 'lon': lon}))
        
        # Sort points by sequence and add to route shapes
        for shape_id, points in shape_points.items():
            points.sort(key=lambda x: x[0])  # Sort by sequence
            for route_id in MONITORED_LINES:
                route_shapes[route_id].extend([p[1] for p in points])
        
        return route_shapes
    except Exception as e:
        logger.error(f"Error getting route shapes: {e}")
        return {}

async def get_route_variants_api(route_id: str) -> Dict:
    """Get route variants for a specific route.
    
    Args:
        route_id: The route ID to get variants for
    
    Returns:
        Dict: Dictionary containing route variants with their shapes and stops
    """
    try:
        # Get fresh GTFS data if needed
        gtfs_manager = GTFSManager()
        gtfs_dir = await gtfs_manager.ensure_gtfs_data()
        if not gtfs_dir:
            return {'shapes': []}
        
        # Get monitored stops for matching with shapes
        stops = await get_stops()
        monitored_stops = [
            {'lat': float(stop.lat), 'lon': float(stop.lon)}
            for stop in stops.values()
        ]
        
        # Get variants for the route
        from .routes import get_route_variants
        variants = get_route_variants(route_id, monitored_stops, gtfs_dir)
        if not variants:
            return {'shapes': []}
        
        # Convert to API format
        shapes = []
        for variant_num, points in variants['variants'].items():
            # Convert points to [lon, lat] format
            shape_points = points  # points are already in [lon, lat] format
            
            # Get stops for this variant
            variant_stops = []
            for stop in stops.values():
                if _point_matches_any_point(stop, points):
                    variant_stops.append({
                        'coordinates': {
                            'lat': float(stop.lat),
                            'lon': float(stop.lon)
                        },
                        'id': stop.id,
                        'name': stop.name,
                        'order': len(variant_stops) + 1
                    })
            
            shapes.append({
                'points': shape_points,
                'stops': variant_stops,
                'variante': int(variant_num)
            })
        
        return {'shapes': shapes}
        
    except Exception as e:
        logger.error(f"Error getting route variants: {e}")
        return {'shapes': []}

def _point_matches_any_point(stop: Stop, points: List[List[float]], threshold: float = 0.0001) -> bool:
    """Check if a stop matches any point in a list of points"""
    for point in points:
        if abs(point[1] - float(stop.lat)) < threshold and abs(point[0] - float(stop.lon)) < threshold:
            return True
    return False

async def get_line_colors(line_number: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Get line colors in De Lijn format.
    
    Args:
        line_number: Optional specific line number to get colors for
        
    Returns:
        Dict with format:
        {
            "text": "#RRGGBB",
            "background": "#RRGGBB",
            "text_border": "#RRGGBB",
            "background_border": "#RRGGBB"
        }
    """
    try:
        gtfs_path = _get_current_gtfs_path()
        if not gtfs_path:
            return {}
            
        routes_file = gtfs_path / 'routes.txt'
        if not routes_file.exists():
            return {}
            
        with open(routes_file, 'r', encoding='utf-8') as f:
            header = next(f).strip().split(',')
            route_id_index = header.index('route_id')
            route_color_index = header.index('route_color') if 'route_color' in header else -1
            route_text_color_index = header.index('route_text_color') if 'route_text_color' in header else -1
            
            # If looking for a specific line
            if line_number:
                for line in f:
                    fields = line.strip().split(',')
                    if fields[route_id_index] == line_number:
                        bg_color = f"#{fields[route_color_index]}" if route_color_index >= 0 and fields[route_color_index] else "#666666"
                        text_color = f"#{fields[route_text_color_index]}" if route_text_color_index >= 0 and fields[route_text_color_index] else "#FFFFFF"
                        
                        return {
                            "text": text_color,
                            "background": bg_color,
                            "text_border": text_color,  # Use same colors for borders
                            "background_border": bg_color
                        }
                return {}
            
            # If getting all colors
            colors = {}
            for line in f:
                fields = line.strip().split(',')
                route_id = fields[route_id_index]
                
                if not MONITORED_LINES or route_id in MONITORED_LINES:
                    bg_color = f"#{fields[route_color_index]}" if route_color_index >= 0 and fields[route_color_index] else "#666666"
                    text_color = f"#{fields[route_text_color_index]}" if route_text_color_index >= 0 and fields[route_text_color_index] else "#FFFFFF"
                    
                    colors[route_id] = {
                        "text": text_color,
                        "background": bg_color,
                        "text_border": text_color,  # Use same colors for borders
                        "background_border": bg_color
                    }
            
            return colors
            
    except Exception as e:
        logger.error(f"Error getting line colors: {e}")
        return {}