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
PROVIDER_ID = provider_config.get('PROVIDER_ID', 'tld-5862')  # BKK's ID in Mobility DB
MONITORED_LINES = provider_config.get('MONITORED_LINES', [])
STOP_IDS = provider_config.get('STOP_IDS', [])

# GTFS-realtime endpoints
VEHICLE_POSITIONS_URL = 'https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/VehiclePositions.pb'
TRIP_UPDATES_URL = 'https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/TripUpdates.pb'
ALERTS_URL = 'https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/Alerts.pb'

class GTFSManager:
    """Manages GTFS data download and caching using mobility-db-api"""
    
    def __init__(self):
        self.mobility_api = MobilityAPI(
            data_dir=str(GTFS_DIR),
            refresh_token=os.getenv('MOBILITY_API_REFRESH_TOKEN')
        )
        
    async def ensure_gtfs_data(self) -> Optional[Path]:
        """Ensure GTFS data is downloaded and up to date"""
        try:
            # Create GTFS directory if it doesn't exist
            GTFS_DIR.mkdir(parents=True, exist_ok=True)
            
            # Check if we need to download new data
            datasets = self.mobility_api.list_downloaded_datasets()
            current_dataset = next(
                (d for d in datasets if d.provider_id == PROVIDER_ID), 
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
    """Get real-time vehicle positions"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                VEHICLE_POSITIONS_URL,
                params={'key': API_KEY}
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get vehicle positions: {response.status_code}")
                return []
                
            # Parse protobuf message
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            vehicles = []
            for entity in feed.entity:
                if entity.HasField('vehicle'):
                    vehicle = entity.vehicle
                    
                    # Only process vehicles for monitored lines
                    trip_id = vehicle.trip.trip_id
                    line_id = _get_line_id_from_trip(trip_id)
                    if MONITORED_LINES and line_id not in MONITORED_LINES:
                        continue
                        
                    vehicles.append({
                        'line': line_id,
                        'trip_id': trip_id,
                        'position': {
                            'lat': vehicle.position.latitude,
                            'lon': vehicle.position.longitude
                        },
                        'bearing': vehicle.position.bearing,
                        'timestamp': datetime.fromtimestamp(
                            vehicle.timestamp, 
                            tz=timezone.utc
                        ).isoformat(),
                        'vehicle_id': vehicle.vehicle.id
                    })
                    
            return vehicles
            
    except Exception as e:
        logger.error(f"Error getting vehicle positions: {e}")
        return []

async def get_waiting_times() -> Dict:
    """Get real-time arrival predictions"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                TRIP_UPDATES_URL,
                params={'key': API_KEY}
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get trip updates: {response.status_code}")
                return {}
                
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            # Process and format arrival times
            stops_data = {}
            for entity in feed.entity:
                if entity.HasField('trip_update'):
                    update = entity.trip_update
                    
                    # Only process monitored lines
                    line_id = _get_line_id_from_trip(update.trip.trip_id)
                    if MONITORED_LINES and line_id not in MONITORED_LINES:
                        continue
                        
                    for stop_time in update.stop_time_update:
                        stop_id = stop_time.stop_id
                        if STOP_IDS and stop_id not in STOP_IDS:
                            continue
                            
                        if stop_id not in stops_data:
                            stops_data[stop_id] = {'lines': {}}
                            
                        if line_id not in stops_data[stop_id]['lines']:
                            stops_data[stop_id]['lines'][line_id] = {}
                            
                        # Format arrival time
                        arrival_time = datetime.fromtimestamp(
                            stop_time.arrival.time,
                            tz=timezone.utc
                        )
                        
                        arrival_data = {
                            'scheduled_time': arrival_time.strftime('%H:%M'),
                            'scheduled_minutes': _format_minutes_until(arrival_time),
                            'is_realtime': True,
                            'delay': stop_time.arrival.delay
                        }
                        
                        # Add to appropriate destination
                        destination = _get_destination_from_trip(update.trip.trip_id)
                        if destination not in stops_data[stop_id]['lines'][line_id]:
                            stops_data[stop_id]['lines'][line_id][destination] = []
                        stops_data[stop_id]['lines'][line_id][destination].append(arrival_data)
                        
            return stops_data
            
    except Exception as e:
        logger.error(f"Error getting waiting times: {e}")
        return {}

async def get_service_alerts() -> List[Dict]:
    """Get service disruption messages"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                ALERTS_URL,
                params={'key': API_KEY}
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get service alerts: {response.status_code}")
                return []
                
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            alerts = []
            for entity in feed.entity:
                if entity.HasField('alert'):
                    alert = entity.alert
                    
                    # Check if alert affects monitored lines/stops
                    affects_monitored = False
                    affected_entities = []
                    
                    for informed_entity in alert.informed_entity:
                        if (informed_entity.HasField('route_id') and 
                            informed_entity.route_id in MONITORED_LINES):
                            affects_monitored = True
                            affected_entities.append({
                                'type': 'line',
                                'id': informed_entity.route_id
                            })
                        elif (informed_entity.HasField('stop_id') and 
                              informed_entity.stop_id in STOP_IDS):
                            affects_monitored = True
                            affected_entities.append({
                                'type': 'stop',
                                'id': informed_entity.stop_id
                            })
                    
                    if not affects_monitored and (MONITORED_LINES or STOP_IDS):
                        continue
                    
                    alerts.append({
                        'id': entity.id,
                        'title': _get_translated_text(alert.header_text),
                        'description': _get_translated_text(alert.description_text),
                        'effect': alert.effect,
                        'affected_entities': affected_entities,
                        'active_period': [
                            {
                                'start': datetime.fromtimestamp(
                                    period.start, 
                                    tz=timezone.utc
                                ).isoformat(),
                                'end': datetime.fromtimestamp(
                                    period.end,
                                    tz=timezone.utc
                                ).isoformat() if period.HasField('end') else None
                            }
                            for period in alert.active_period
                        ]
                    })
                    
            return alerts
            
    except Exception as e:
        logger.error(f"Error getting service alerts: {e}")
        return []

# Helper functions
def _get_line_id_from_trip(trip_id: str) -> str:
    """Extract line ID from trip ID based on GTFS data structure"""
    try:
        # BKK trip_id format: "line_number.direction.variant.service_id"
        # Example: "3040.1.123.123"
        parts = trip_id.split('.')
        if len(parts) >= 1 and parts[0].isdigit():
            return parts[0]
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
            
        trips_file = gtfs_dir / 'trips.txt'
        if not trips_file.exists():
            return ''
            
        with open(trips_file, 'r', encoding='utf-8') as f:
            for line in f:
                if trip_id in line:
                    # Extract headsign from the line
                    fields = line.strip().split(',')
                    if len(fields) >= 4:  # Assuming trip_headsign is the 4th field
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

async def get_static_data() -> Dict:
    """Get static configuration data"""
    gtfs_manager = GTFSManager()
    gtfs_dir = await gtfs_manager.ensure_gtfs_data()
    
    if not gtfs_dir:
        return {
            "error": "Could not access GTFS data"
        }
        
    return {
        "provider": "BKK",
        "gtfs_dir": str(gtfs_dir),
        "monitored_lines": MONITORED_LINES,
        "stop_ids": STOP_IDS
    }

def bkk_config():
    """Get BKK provider configuration"""
    return provider_config