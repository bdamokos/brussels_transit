import os
from config import get_config
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple, Optional, Union
import pytz
import logging
from logging.config import dictConfig
import asyncio
from pathlib import Path
from dataclasses import asdict

import pytz
from utils import RateLimiter, get_client, select_language, matches_destination
from dataclasses import dataclass
from collections import defaultdict
from get_stop_names import get_stop_names
from transit_providers.config import get_provider_config
from .gtfs import download_gtfs_data
from transit_providers.nearest_stop import (
    ingest_gtfs_stops, get_nearest_stops, cache_stops, 
    get_cached_stops, Stop, get_stop_by_name as generic_get_stop_by_name
)
from .stop_coordinates import get_stop_coordinates as get_stop_coordinates_with_fallback
from .locate_vehicles import process_vehicle_positions, interpolate_position, VehiclePosition, validate_segment
from .validate_stops import validate_line_stops, load_route_shape

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

# Get available languages from provider config
AVAILABLE_LANGUAGES = provider_config.get('_AVAILABLE_LANGUAGES', ['en', 'fr', 'nl'])
logger.debug(f"Available languages: {AVAILABLE_LANGUAGES}")

def parse_service_message(message, stop_details):
    """Parse a service message and extract relevant information"""
    try:
        content = json.loads(message['content'])
        lines = json.loads(message['lines'])
        points = json.loads(message['points'])
        
        # Get text using language selection utility
        text_with_langs = content[0]['text'][0]
        text, metadata = select_language(text_with_langs, provider_languages=AVAILABLE_LANGUAGES)
        if metadata['language']['warning']:
            logger.warning(f"Language warning for message: {metadata['language']['warning']}")
        
        # Get affected stop names
        affected_stops = [stop_details.get(point['id'], {'name': point['id']})['name'] 
                        for point in points]
        
        # Get affected lines
        affected_lines = [line['id'] for line in lines]
        
        return {
            'text': text,
            '_metadata': metadata,  # Include language metadata
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
    """Get service messages for monitored lines and stops
    
    Args:
        monitored_lines: Optional list or dict of monitored line numbers
        monitored_stops: Optional list of monitored stop IDs
        
    Returns:
        Dictionary containing messages in the format:
        {
            'messages': [
                {
                    'text': 'Message text in English',
                    'lines': ['1', '2'],  # Affected line numbers
                    'points': ['8122', '8032'],  # Affected stop IDs
                    'stops': ['ROODEBEEK', 'PARC'],  # Affected stop names
                    'priority': 0,  # Message priority
                    'type': '',  # Message type
                    'is_monitored': True  # Whether this affects monitored lines/stops
                }
            ]
        }
    """
    try:
        # Convert monitored_lines to a set of strings for easier lookup
        monitored_line_set = set()
        if monitored_lines:
            if isinstance(monitored_lines, dict):
                monitored_line_set.update(str(line) for line in monitored_lines.keys())
            elif isinstance(monitored_lines, (list, set)):
                monitored_line_set.update(str(line) for line in monitored_lines)
            else:
                monitored_line_set.add(str(monitored_lines))
        
        # Convert monitored_stops to a set of strings
        monitored_stop_set = set(str(stop) for stop in (monitored_stops or []))
        
        # Build API query
        filters = []
        
        # Add stop filters
        if monitored_stop_set:
            stop_filters = [f"points like '%{stop}%'" for stop in monitored_stop_set]
            filters.extend(stop_filters)
            logger.debug(f"Added {len(stop_filters)} stop filters")
        
        # Add line filters
        if monitored_line_set:
            line_filters = [f"lines like '%{line}%'" for line in monitored_line_set]
            filters.extend(line_filters)
            logger.debug(f"Added {len(line_filters)} line filters")
        
        # Build query parameters
        params = {
            'apikey': API_KEY,
            'limit': 100,  # Get a reasonable number of messages
            'select': 'content,lines,points,priority,type'  # Only get fields we need
        }
        
        # Add where clause if we have filters
        if filters:
            params['where'] = ' or '.join(filters)
        
        logger.debug(f"Service messages API URL: {MESSAGES_API_URL}?{params}")
        
        # Make API request
        async with await get_client() as client:
            response = await client.get(MESSAGES_API_URL, params=params)
            rate_limiter.update_from_headers(response.headers)
            
            if response.status_code != 200:
                logger.error(f"Service messages API returned {response.status_code}: {response.text}")
                return {'messages': []}
            
            data = response.json()
            parsed_messages = []
            
            # Process each message
            for message in data.get('results', []):
                try:
                    # Parse JSON fields
                    try:
                        content = json.loads(message.get('content', '[]'))
                        lines = json.loads(message.get('lines', '[]'))
                        points = json.loads(message.get('points', '[]'))
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse message JSON: {e}")
                        continue
                    
                    # Get message text using language selection utility
                    try:
                        text_with_langs = content[0]['text'][0]
                        text, metadata = select_language(text_with_langs, provider_languages=AVAILABLE_LANGUAGES)
                        if metadata['language']['warning']:
                            logger.warning(f"Language warning for message: {metadata['language']['warning']}")
                    except (IndexError, KeyError) as e:
                        logger.error(f"Failed to get message text: {e}")
                        continue
                    
                    # Get affected lines
                    affected_lines = []
                    try:
                        affected_lines = [str(line['id']) for line in lines]
                    except (KeyError, TypeError) as e:
                        logger.error(f"Failed to get affected lines: {e}")
                        continue
                    
                    # Get affected stops
                    affected_stop_ids = []
                    try:
                        affected_stop_ids = [str(point['id']) for point in points]
                    except (KeyError, TypeError) as e:
                        logger.error(f"Failed to get affected stops: {e}")
                        continue
                    
                    # Get stop names
                    stop_names = []
                    try:
                        stop_info = await get_stop_names(affected_stop_ids)
                        if stop_info:
                            stop_names = [info.get('name', stop_id) for stop_id, info in stop_info.items()]
                        else:
                            stop_names = affected_stop_ids  # Fallback to IDs if names not found
                    except Exception as e:
                        logger.error(f"Failed to get stop names: {e}")
                        stop_names = affected_stop_ids  # Fallback to IDs
                    
                    # Check if this message affects monitored lines/stops
                    is_monitored = (
                        bool(monitored_line_set) and bool(set(affected_lines) & monitored_line_set) or
                        bool(monitored_stop_set) and bool(set(affected_stop_ids) & monitored_stop_set)
                    )
                    
                    # Add the parsed message
                    parsed_messages.append({
                        'text': text,
                        '_metadata': metadata,  # Include language metadata
                        'lines': affected_lines,
                        'points': affected_stop_ids,
                        'stops': stop_names,
                        'priority': message.get('priority', 0),
                        'type': message.get('type', ''),
                        'is_monitored': is_monitored
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    continue
            
            logger.debug(f"Successfully parsed {len(parsed_messages)} messages")
            return {'messages': parsed_messages}
            
    except Exception as e:
        logger.error(f"Error getting service messages: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {'messages': []}  # Return empty result instead of raising

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
                routes_cache['timestamp'] = datetime.fromisoformat(cache_data.get('timestamp', ''))
                logger.debug(f"Loaded route colors from file cache: {routes_cache.get('data', 'Error no data in cache')}")
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
                    cache_timestamp = datetime.fromisoformat(cache_data.get('timestamp', ''))
                    if cache_timestamp and datetime.now() - cache_timestamp < CACHE_DURATION:
                        return cache_data.get('data', {})
        except Exception as cache_e:
            logger.error(f"Error loading routes cache: {cache_e}\n{traceback.format_exc()}")
        
        # Return empty dictionary if everything fails
        return route_colors

# Initialize routes_cache at startup
routes_cache = {
    'timestamp': None,
    'data': None
}


async def get_vehicle_positions(line: str = None, direction: str = None):
    """Get real-time vehicle positions from STIB API
    
    Args:
        line: Optional line number to filter results
        direction: Optional direction to filter results
        
    Returns:
        Dictionary containing vehicle positions in the format:
        {
            "vehicles": [
                {
                    "line": "55",
                    "direction": "1",
                    "current_segment": ["8122", "8032"],
                    "distance_to_next": 100,
                    "segment_length": 500,
                    "is_valid": true,
                    "interpolated_position": [50.8, 4.3],
                    "bearing": 45
                }
            ]
        }
    """
    try:
        # Get monitored lines from config if no specific line is requested
        if line:
            monitored_lines = {str(line)}
        else:
            monitored_lines = set()
            for stop in STIB_STOPS:
                if 'lines' in stop:
                    monitored_lines.update(str(l) for l in stop['lines'])
        
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
                return {"vehicles": []}
                
            response = await client.get(
                base_url,
                params=params
            )
            # Update rate limits from response headers
            rate_limiter.update_from_headers(response.headers)
            
            data = response.json()
            
            # Transform into intermediate format
            positions = defaultdict(lambda: defaultdict(list))
            
            # Process each vehicle record
            for record in data.get('results', []):
                try:
                    line_id = str(record.get('lineid'))
                    # Parse the nested vehiclepositions JSON string
                    vehicle_positions = json.loads(record.get('vehiclepositions', '[]'))
                    
                    for position in vehicle_positions:
                        vehicle_direction = str(position.get('directionId'))
                        # Skip if direction doesn't match (if specified)
                        if direction and vehicle_direction != direction:
                            continue
                            
                        point_id = str(position.get('pointId'))
                        distance = position.get('distanceFromPoint')
                        
                        # Skip invalid data
                        if not all([vehicle_direction, point_id]) or distance is None:
                            continue
                        
                        position_data = {
                            'distance': distance,
                            'next_stop': point_id
                        }
                        
                        positions[line_id][vehicle_direction].append(position_data)
                        logger.debug(f"Added position data for line {line_id} ({vehicle_direction}): {position_data}")
                    
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.error(f"Error processing vehicle position for line {line_id}: {e}")
                    continue
            
            # Process positions into VehiclePosition objects
            vehicle_positions = []
            for line_id, directions in positions.items():
                # Get route variants for this line
                variants = await validate_line_stops(line_id)
                if not variants:
                    logger.error(f"No route variants found for line {line_id}")
                    continue

                # Process each direction's vehicles
                for direction_id, vehicles_list in directions.items():
                    # Find the route variant for this direction
                    # First try to find a variant where this direction ID is the terminus
                    variant = next(
                        (v for v in variants 
                         if v.stops and v.stops[-1]['id'].rstrip('FG') == direction_id.rstrip('FG')),
                        None
                    )
                    
                    # If not found, try the other variant (assuming 2 variants per line)
                    if not variant and len(variants) > 0:
                        variant = variants[0]  # Use first variant
                        
                    if not variant:
                        logger.error(f"No route variant found for line {line_id} direction {direction_id}")
                        continue

                    # Process each vehicle
                    for vehicle_data in vehicles_list:
                        try:
                            next_stop = vehicle_data['next_stop'].rstrip('FG')
                            
                            # Find the stop in the variant's stop list
                            stop_index = next(
                                (i for i, stop in enumerate(variant.stops)
                                 if stop['id'].rstrip('FG') == next_stop),
                                None
                            )
                            if stop_index is None:
                                logger.error(f"Stop {next_stop} not found in variant for line {line_id}")
                                continue
                                
                            # Get the next stop in the sequence
                            if stop_index + 1 < len(variant.stops):
                                next_stop_obj = variant.stops[stop_index + 1]
                                next_stop_id = next_stop_obj['id']
                                
                                # Get the current stop and next stop
                                from_stop = variant.stops[stop_index]
                                to_stop = variant.stops[stop_index + 1]
                                
                                # Create VehiclePosition object using validate_segment
                                position = validate_segment(
                                    from_stop=from_stop,
                                    to_stop=to_stop,
                                    line=line_id,
                                    direction=variant.direction,  # Use City/Suburb from variant
                                    distance_to_next=vehicle_data['distance'],
                                    route_variant=variant,
                                    raw_data=vehicle_data
                                )
                                
                                if position:
                                    vehicle_positions.append(position)
                            else:
                                logger.warning(f"Vehicle at terminal stop {next_stop} on line {line_id}")
                                
                        except Exception as e:
                            logger.error(f"Error processing vehicle on line {line_id}: {e}")
                            continue

            # Convert to v1 format
            return {
                "vehicles": [
                    {
                        "line": v.line,
                        "direction": v.direction,
                        "current_segment": v.current_segment,
                        "distance_to_next": v.distance_to_next,
                        "segment_length": v.segment_length,
                        "is_valid": v.is_valid,
                        "interpolated_position": v.interpolated_position,
                        "bearing": v.bearing,
                        "shape_segment": v.shape_segment,
                        "raw_data": v.raw_data
                    }
                    for v in vehicle_positions
                ]
            }
            
    except Exception as e:
        logger.error(f"Error fetching vehicle positions: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"vehicles": []}

def normalize_stop_id(stop_id: str) -> str:
    """Remove any suffix (letters) from a stop ID.
    
    Args:
        stop_id: The stop ID to normalize (e.g., "5710F")
        
    Returns:
        The normalized stop ID (e.g., "5710")
    """
    # Remove any non-digit characters from the end of the stop ID
    return ''.join(c for c in stop_id if c.isdigit())

async def get_waiting_times(stop_id: Union[str, List[str]] = None) -> Dict[str, Any]:
    """Get real-time waiting times for STIB stops
    
    Args:
        stop_id: Optional stop ID or list of stop IDs to filter results. 
                Example of a valid stop_id: 8122 (ROODEBEEK)
                Example of a list: ["8122", "8032"] (ROODEBEEK and PARC)
                Stop IDs with suffixes (e.g., "5710F") will be normalized
                by removing the suffix before querying the API.
        
    Returns:
        Dictionary containing waiting times data in the format:
        {
            "stops_data": {
                "stop_id": {
                    "name": "Stop Name",
                    "coordinates": {"lat": 50.8, "lon": 4.3},
                    "lines": {
                        "line_number": {
                            "destination": [{
                                "destination": "DESTINATION",
                                "formatted_time": "14:30",
                                "message": "",
                                "minutes": 5
                            }]
                        }
                    }
                }
            }
        }"""

    try:
        # Get monitored stops from merged config
        provider_config = get_provider_config('stib')
        monitored_stops = {
            normalize_stop_id(str(stop['id'])): stop 
            for stop in provider_config.get('STIB_STOPS', [])
        }
        logger.debug(f"Found {len(monitored_stops)} monitored stops in config")
        
        # Build API query
        params = {
            'apikey': API_KEY,
            'limit': 100,
            'select': 'pointid,lineid,passingtimes'
        }
        
        # Handle stop_id parameter
        requested_stops = set()
        original_to_normalized = {}  # Keep track of original stop IDs
        if stop_id:
            if isinstance(stop_id, str):
                # Handle comma-separated string
                stop_ids = [s.strip() for s in stop_id.split(',')]
            elif isinstance(stop_id, list):
                stop_ids = [str(s) for s in stop_id]
            else:
                logger.warning(f"Invalid stop_id parameter type: {type(stop_id)}")
                stop_ids = []
                
            # Normalize stop IDs and keep track of originals
            for original_id in stop_ids:
                normalized_id = normalize_stop_id(original_id)
                requested_stops.add(normalized_id)
                original_to_normalized[original_id] = normalized_id
                
            logger.debug(f"Requested stops: {requested_stops} (normalized from {stop_id})")
                
            # Build query for requested stops
            stop_filter = ' or '.join(f'pointid="{stop_id}"' for stop_id in requested_stops)
            params['where'] = f'({stop_filter})'
            params['limit'] = 100  # Make sure we get all results for the requested stops
        # Otherwise filter for all monitored stops
        elif monitored_stops:
            stop_filter = ' or '.join(f'pointid="{stop_id}"' for stop_id in monitored_stops.keys())
            params['where'] = f'({stop_filter})'
            params['limit'] = 100  # Make sure we get all results for monitored stops
            logger.debug(f"Using monitored stops: {list(monitored_stops.keys())}")
            
        async with await get_client() as client:
            response = await client.get(WAITING_TIMES_API_URL, params=params)
            rate_limiter.update_from_headers(response.headers)
            
            if response.status_code != 200:
                logger.error(f"Failed to get waiting times: {response.status_code} {response.text}")
                return {"stops_data": {}}
            
            data = response.json()
            formatted_data = {"stops_data": {}}
            
            # Process each record
            for record in data.get('results', []):
                try:
                    current_stop_id = str(record.get('pointid'))
                    if not current_stop_id:
                        logger.warning("Skipping record with no stop ID")
                        continue
                    
                    # If specific stops were requested, only process those
                    if requested_stops and current_stop_id not in requested_stops:
                        logger.debug(f"Skipping stop {current_stop_id} - not in requested stops")
                        continue
                    # Otherwise only process monitored stops
                    elif not requested_stops and current_stop_id not in monitored_stops:
                        logger.debug(f"Skipping stop {current_stop_id} - not in monitored stops")
                        continue
                    
                    line = str(record.get('lineid'))
                    if not line:
                        logger.warning(f"Skipping record for stop {current_stop_id} - no line ID")
                        continue
                    
                    # Find the original stop ID if it exists
                    original_stop_id = None
                    if original_to_normalized:
                        for orig, norm in original_to_normalized.items():
                            if norm == current_stop_id:
                                original_stop_id = orig
                                break
                    
                    # Use the original stop ID in the response if available
                    response_stop_id = original_stop_id or current_stop_id
                    
                    # Initialize stop data if needed
                    if response_stop_id not in formatted_data["stops_data"]:
                        # Get stop name from monitored stops if available, otherwise use stop ID
                        stop_name = monitored_stops[current_stop_id]['name'] if current_stop_id in monitored_stops else response_stop_id
                        
                        # Get coordinates for this stop (use original ID for coordinates lookup)
                        coordinates = get_stop_coordinates_with_fallback(response_stop_id)
                        if coordinates:
                            logger.debug(f"Found coordinates for stop {response_stop_id}")
                        else:
                            logger.warning(f"No coordinates found for stop {response_stop_id}")
                            
                        formatted_data["stops_data"][response_stop_id] = {
                            "name": stop_name,
                            "coordinates": coordinates or {},
                            "lines": {}
                        }
                    
                    # Process passing times
                    passing_times = record.get('passingtimes')
                    if not passing_times:
                        logger.warning(f"No passing times for stop {response_stop_id}, line {line}")
                        continue
                        
                    # Handle both string and list formats
                    if isinstance(passing_times, str):
                        try:
                            passing_times = json.loads(passing_times)
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON in passing times for stop {response_stop_id}, line {line}")
                            continue
                    
                    if not isinstance(passing_times, list):
                        logger.warning(f"Invalid passing times format for stop {response_stop_id}, line {line}")
                        continue
                    
                    for passing_time in passing_times:
                        try:
                            # Get destination with all language versions
                            destination_data = passing_time.get('destination', {})
                            if not isinstance(destination_data, dict):
                                destination_data = {'fr': str(destination_data)}
                            
                            # Select display name using language precedence
                            selected_destination,_metadata = select_language(content=destination_data, provider_languages=AVAILABLE_LANGUAGES)
                            destination = selected_destination
                            
                            # For monitored stops, check if this line is monitored
                            if current_stop_id in monitored_stops:
                                stop_config = monitored_stops[current_stop_id]
                                allowed_lines = stop_config.get('lines', {})
                                
                                if line not in allowed_lines:
                                    logger.debug(f"Skipping line {line} for monitored stop {response_stop_id} - not in config")
                                    continue
                                
                                # Check if this destination is allowed for this line
                                allowed_destinations = allowed_lines[line]
                                if allowed_destinations and not any(matches_destination(allowed_dest, destination_data) 
                                                                  for allowed_dest in allowed_destinations):
                                    logger.warning(
                                        f"Unexpected destination '{destination}' for line {line} at stop {response_stop_id} "
                                        f"(configured destinations: {allowed_destinations})"
                                    )
                                    continue
                            
                            # Initialize line data if needed
                            if line not in formatted_data["stops_data"][response_stop_id]["lines"]:
                                formatted_data["stops_data"][response_stop_id]["lines"][line] = {}
                            
                            if destination not in formatted_data["stops_data"][response_stop_id]["lines"][line]:
                                formatted_data["stops_data"][response_stop_id]["lines"][line][destination] = []
                            
                            # Calculate minutes until arrival
                            expected_time = passing_time.get('expectedArrivalTime')
                            if not expected_time:
                                logger.warning(f"No arrival time for stop {response_stop_id}, line {line}")
                                continue
                                
                            try:
                                arrival_dt = datetime.fromisoformat(expected_time.replace('Z', '+00:00'))
                                now = datetime.now(timezone.utc)
                                minutes = max(0, int((arrival_dt - now).total_seconds() / 60))
                                
                                formatted_data["stops_data"][response_stop_id]["lines"][line][destination].append({
                                    "destination": destination,
                                    "destination_data": destination_data,  # Keep all language versions
                                    "minutes": minutes,
                                    "message": passing_time.get('message', ''),
                                    "formatted_time": arrival_dt.strftime("%H:%M"),
                                    "_metadata": {
                                        "language": _metadata['language']
                                    }
                                })
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error parsing time {expected_time} for stop {response_stop_id}, line {line}: {e}")
                                continue
                                
                        except Exception as e:
                            logger.error(f"Error processing passing time for stop {response_stop_id}, line {line}: {e}")
                            continue
                            
                except Exception as e:
                    import traceback
                    logger.error(f"Error processing record: {e}, {traceback.format_exc()}")
                    continue
            
            # Remove any stops that ended up with no valid data
            formatted_data["stops_data"] = {
                stop_id: stop_data
                for stop_id, stop_data in formatted_data["stops_data"].items()
                if stop_data.get("lines")
            }
            
            return formatted_data
            
    except Exception as e:
        logger.error(f"Error getting waiting times: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"stops_data": {}}

async def get_route_data(line: str) -> Dict[str, Any]:
    """Get route data for a specific line
    
    Args:
        line: Line number
        
    Returns:
        Dictionary containing route variants with stops and shapes
    """
    try:
        # Get route variants from validate_stops
        from validate_stops import validate_line_stops, load_route_shape
        route_variants = await validate_line_stops(line)
        
        if not route_variants:
            return None
            
        # Convert RouteVariant objects to dictionaries
        variants_dict = []
        for variant in route_variants:
            # Get shape data for this variant
            shape = load_route_shape(line, variant.direction)
            
            variants_dict.append({
                'direction': variant.direction,
                'stops': variant.stops,
                'shape': shape,
                'destination': variant.destination,
                'date_fin': getattr(variant, 'date_fin', None),
                'variante': getattr(variant, 'variante', None)
            })
            
        return {line: variants_dict}
        
    except Exception as e:
        logger.error(f"Error getting route data: {e}")
        return None

async def ensure_gtfs_data() -> Optional[Path]:
    """Ensure GTFS data is downloaded and return path to GTFS directory."""
    if not GTFS_DIR.exists() or not (GTFS_DIR / 'stops.txt').exists():
        logger.info("GTFS data not found, downloading...")
        await download_gtfs_data()
    return GTFS_DIR

async def get_stops() -> Dict[str, Stop]:
    """Get all stops from GTFS data or cache."""
    cache_path = CACHE_DIR / 'stops_gtfs.json'
    
    # Try to get from cache first
    cached_stops = get_cached_stops(cache_path)
    if cached_stops is not None:
        return cached_stops
    
    # If not in cache, ensure GTFS data and load stops
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

async def get_stop_by_name(name: str, limit: int = 5) -> List[Dict]:
    """Search for stops by name using the generic function.
    
    Args:
        name (str): The name or partial name to search for
        limit (int, optional): Maximum number of results to return. Defaults to 5.
        
    Returns:
        List[Dict]: List of matching stops with their details
    """
    try:
        # Ensure GTFS data is available
        await ensure_gtfs_data()
        
        # Get all stops
        stops = ingest_gtfs_stops(GTFS_DIR)
        
        # Use the generic function
        matching_stops = generic_get_stop_by_name(stops, name, limit)
        
        # Convert Stop objects to dictionaries
        return [asdict(stop) for stop in matching_stops] if matching_stops else []
        
    except Exception as e:
        logger.error(f"Error in get_stop_by_name: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

def get_nearest_stop(coordinates: Tuple[float, float]) -> Dict[str, Any]:
    """Get nearest stop to coordinates."""
    lat, lon = coordinates
    stops = asyncio.run(find_nearest_stops(lat, lon, limit=1))
    return stops[0] if stops else {}

async def get_stop_coordinates(self, stop_id: str) -> Optional[Dict[str, float]]:
    """Get coordinates for a stop."""
    try:
        # Try to get coordinates from API first
        url = f"{self.stops_api_url}?apikey={self.api_key}&where=id='{stop_id}'"
        async with await get_client() as client:
            response = await client.get(url)
            if response.status_code != 200:
                logger.error(f"Failed to get stop coordinates: {response.status_code} {response.text}")
                return None
                    
            data = response.json()
            results = data.get('results', [])
            if not results:
                logger.warning(f"No results found for stop {stop_id}")
                return get_stop_coordinates_with_fallback(stop_id)
                    
            stop = results[0]
            lat = stop.get('latitude')
            lon = stop.get('longitude')
            
            # Use GTFS fallback if API returns null coordinates
            return get_stop_coordinates_with_fallback(stop_id, (lat, lon))
                
    except Exception as e:
        logger.error(f"Error getting stop coordinates: {e}")
        return get_stop_coordinates_with_fallback(stop_id)

def convert_v2_to_v1_format(v2_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert v2 API response format to v1 format for backward compatibility.
    
    See api_formats.md for detailed format documentation.

    Function to be removed once all clients have been migrated to v2.
    
    Args:
        v2_data: Data in v2 format
        
    Returns:
        Data in v1 format
    """
    v1_data = {
        "stops_data": {},
        "messages": {"messages": []},
        "processed_vehicles": [],
        "errors": [],
        "shapes": {},  # Will be transformed below
        "route_colors": v2_data.get("route_colors", {}),  # Copy route colors directly
        "display_stops": v2_data.get("display_stops", [])  # Copy display stops directly
    }
    
    # Transform shapes - swap coordinates from [lon, lat] to [lat, lon]
    shapes_data = v2_data.get("shapes", {})
    for line, variants in shapes_data.items():
        if not isinstance(variants, list):
            continue
        v1_data["shapes"][line] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            # Get shape coordinates and swap them
            shape_coords = variant.get('shape', [])
            if shape_coords:
                # Create a new variant with swapped coordinates
                v1_variant = {
                    "date_fin": variant.get("date_fin"),
                    "destination": variant.get("destination", {}),
                    "direction": variant.get("direction", ""),
                    "shape": [[lat, lon] for lon, lat in shape_coords],  # Swap coordinates
                    "stops": variant.get("stops", []),
                    "variante": variant.get("variante")
                }
                v1_data["shapes"][line].append(v1_variant)
    
    # Convert stops data - handle both "stops" and "stops_data" keys
    stops_data = v2_data.get("stops", {}) or v2_data.get("stops_data", {})
    for stop_id, stop_data in stops_data.items():
        v1_stop = {
            "name": stop_data["name"],
            "coordinates": stop_data.get("coordinates", {}).get("coordinates", {}),
            "lines": {}
        }
        
        # Convert lines and waiting times
        for line, line_data in stop_data.get("lines", {}).items():
            v1_stop["lines"][line] = {}
            for dest, dest_data in line_data.items():
                # Use the provided language version as in v1
                v1_stop["lines"][line][dest] = [
                    {
                        "destination": arrival["destination"],
                        "formatted_time": arrival["formatted_time"],
                        "message": arrival.get("message", ""),
                        "minutes": arrival["minutes"]
                    }
                    for arrival in dest_data
                ]
        
        v1_data["stops_data"][stop_id] = v1_stop
    
    # Convert messages
    # Get monitored stops and their lines from config
    logger.debug(f"STIB_STOPS: {STIB_STOPS}")
    # Convert list of stops to a dict keyed by stop ID
    monitored_stops = {str(stop['id']): stop for stop in STIB_STOPS}
    logger.debug(f"Monitored stops: {monitored_stops}")
    monitored_lines = set()
    for stop_data in STIB_STOPS:  # Iterate directly over the list
        monitored_lines.update(str(line) for line in stop_data.get('lines', []))

    v1_data["messages"]["messages"] = [
        {
            "text": msg["text"],
            "lines": msg["lines"],
            "points": msg["points"],
            "stops": msg["stops"],
            "priority": msg.get("priority", 0),
            "type": msg.get("type", ""),
            "is_monitored": (
                any(stop_id in monitored_stops for stop_id in msg["points"]) and 
                any(line in monitored_lines for line in msg["lines"])
            )
        }
        for msg in v2_data.get("messages", [])
    ]
    
    # Convert vehicles
    v1_data["processed_vehicles"] = v2_data.get("vehicles", {}).get("vehicles", [])
    
    # Add any errors from metadata
    for stop_id, stop_data in stops_data.items():
        if "metadata" in stop_data and stop_data["metadata"].get("warning"):
            v1_data["errors"].append(f"Stop {stop_id}: {stop_data['metadata']['warning']}")
            
    return v1_data

async def get_data(stop_id: Union[str, List[str]] = None) -> Dict[str, Any]:
    """Get all data for a stop or list of stops in v2 format.
    
    Args:
        stop_id: Optional stop ID or list of stop IDs to filter results
        
    Returns:
        Dictionary containing all data in v2 format
    """
    try:
        # Get waiting times
        waiting_times = await get_waiting_times(stop_id)
        
        # Get service messages
        messages = await get_service_messages()  # No need to pass monitored lines/stops here
        
        # Get vehicle positions
        vehicles = await get_vehicle_positions()
        
        return {
            "stops": waiting_times.get("stops_data", {}),  # For v2 format
            "stops_data": waiting_times.get("stops_data", {}),  # For v1 format
            "messages": messages.get("messages", []),
            "vehicles": vehicles
        }
        
    except Exception as e:
        logger.error(f"Error getting data: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"error": str(e)}
