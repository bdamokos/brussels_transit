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

# Setup logging
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)
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
        
        async with httpx.AsyncClient() as client:
            response = await client.get(VEHICLE_POSITIONS_URL)
            response.raise_for_status()
            
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            vehicles = []
            for entity in feed.entity:
                vehicle = entity.vehicle
                if not vehicle.trip.route_id:
                    continue
                    
                line_id = _get_line_id_from_trip(vehicle.trip.route_id)
                if monitored_lines and line_id not in monitored_lines:
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
def _get_line_id_from_trip(trip_id: str) -> str:
    """Extract line ID from trip ID based on GTFS data structure"""
    try:
        # Load trip information from GTFS data
        gtfs_dir = GTFS_DIR
        if not gtfs_dir.exists():
            return ''
            
        trips_file = gtfs_dir / 'mdb-990_Budapesti_Kozlekedesi_Kozpont_BKK/mdb-990-202412230112/trips.txt'
        if not trips_file.exists():
            return ''
            
        with open(trips_file, 'r', encoding='utf-8') as f:
            # Skip header line
            next(f)
            for line in f:
                if trip_id in line:
                    # Extract route_id from the line
                    fields = line.strip().split(',')
                    if len(fields) >= 1:
                        route_id = fields[0]
                        # Get route short name from routes.txt
                        routes_file = gtfs_dir / 'mdb-990_Budapesti_Kozlekedesi_Kozpont_BKK/mdb-990-202412230112/routes.txt'
                        if routes_file.exists():
                            with open(routes_file, 'r', encoding='utf-8') as rf:
                                # Skip header line
                                next(rf)
                                for route_line in rf:
                                    if route_id in route_line:
                                        route_fields = route_line.strip().split(',')
                                        if len(route_fields) >= 3:
                                            return route_fields[2]  # route_short_name
        return ''
    except Exception as e:
        logger.error(f"Error extracting line ID from trip {trip_id}: {e}")
        return ''

def _get_destination_from_trip(trip_id: str) -> str:
    """Extract destination from trip ID based on GTFS data structure"""
    try:
        # Load trip information from GTFS data
        gtfs_dir = GTFS_DIR
        if not gtfs_dir.exists():
            return ''
            
        trips_file = gtfs_dir / 'mdb-990_Budapesti_Kozlekedesi_Kozpont_BKK/mdb-990-202412230112/trips.txt'
        if not trips_file.exists():
            return ''
            
        with open(trips_file, 'r', encoding='utf-8') as f:
            # Skip header line
            next(f)
            for line in f:
                if trip_id in line:
                    # Extract headsign from the line
                    fields = line.strip().split(',')
                    if len(fields) >= 4:  # trip_headsign is the 4th field
                        return fields[3].strip('"')
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
    """Get static data for the provider.
    
    Returns:
        Dict[str, Any]: Dictionary containing static data with provider information
    """
    return {
        'provider': 'bkk',
        'monitored_lines': MONITORED_LINES,
        'stop_ids': STOP_IDS,
        'has_vehicle_positions': True,
        'has_service_alerts': True,
        'has_waiting_times': True
    }

async def bkk_config() -> Dict[str, Any]:
    """Get BKK provider configuration.
    
    Returns:
        Dict[str, Any]: Configuration dictionary with provider information
    """
    # Get latest config values
    config = get_provider_config('bkk')
    
    return {
        'provider': 'bkk',
        'monitored_lines': config.get('MONITORED_LINES', []),
        'stop_ids': config.get('STOP_IDS', []),
        'has_vehicle_positions': True,
        'has_service_alerts': True,
        'has_waiting_times': True
    }