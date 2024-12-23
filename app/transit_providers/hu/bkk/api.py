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
    'get_route_shapes'
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
            
        # Ensure we're comparing timezone-aware datetimes
        now = datetime.now(timezone.utc)
        end_date = dataset.feed_end_date
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
    """Get waiting times for monitored stops.
    
    Returns:
        Dict: Dictionary of stop IDs mapping to their waiting times with provider information
    """
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
            
            waiting_times = {}
            for entity in feed.entity:
                if not entity.HasField('trip_update'):
                    continue
                    
                trip = entity.trip_update
                line_id = _get_line_id_from_trip(trip.trip.route_id)
                if monitored_lines and line_id not in monitored_lines:
                    continue
                
                for stop_time in trip.stop_time_update:
                    stop_id = stop_time.stop_id
                    if stop_ids and stop_id not in stop_ids:
                        continue
                        
                    if stop_id not in waiting_times:
                        waiting_times[stop_id] = []
                        
                    if stop_time.HasField('arrival'):
                        arrival_time = datetime.fromtimestamp(stop_time.arrival.time, timezone.utc)
                        waiting_times[stop_id].append({
                            'line': line_id,
                            'destination': _get_destination_from_trip(trip.trip.trip_id),
                            'minutes_until': _format_minutes_until(arrival_time),
                            'timestamp': arrival_time.isoformat(),
                            'provider': 'bkk'
                        })
            
            # Sort waiting times by arrival time
            for stop_id in waiting_times:
                waiting_times[stop_id].sort(key=lambda x: datetime.fromisoformat(x['timestamp']))
            
            return waiting_times
    except Exception as e:
        logger.error(f"Error getting waiting times: {e}")
        return {}

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