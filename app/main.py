from flask import Flask, render_template, request, jsonify
import json
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
from get_stop_names import get_stop_names
from routes import  get_route_data
import asyncio
from hypercorn.asyncio import serve
from hypercorn.config import Config
from dataclasses import dataclass
from typing import Dict, Any, Optional
from inspect import signature, Parameter
import inspect
from locate_vehicles import process_vehicle_positions, interpolate_position
from validate_stops import validate_line_stops
from locate_vehicles import process_vehicle_positions
from collections import defaultdict
import logging
from logging.config import dictConfig
from utils import RateLimiter, get_client
from flask import jsonify
from transit_providers import PROVIDERS
from config import get_config, get_required_config
from dataclasses import asdict
import os
from pathlib import Path
from flask_cors import CORS

# Ensure logs directory exists
Path('logs').mkdir(exist_ok=True)

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)

# Get loggers
logger = logging.getLogger('main')
time_logger = logging.getLogger('main.time')
api_logger = logging.getLogger('main.api')
vehicle_logger = logging.getLogger('main.vehicles')

app = Flask(__name__)
# Enable CORS for all routes
CORS(app, resources={
    r"/api/*": {  # This will enable CORS for all routes under /api/
        "origins": ["*"],  # Allow all origins
        "methods": ["GET", "POST", "OPTIONS"],  # Allow these methods
        "allow_headers": ["Content-Type", "Authorization"]  # Allow these headers
    }
})
FILTER_VEHICLES = True

# Get API key from environment variable
API_KEY = get_required_config('STIB_API_KEY')


# Get configuration
STIB_STOPS = get_config('STIB_STOPS')
MAP_CONFIG = get_config('MAP_CONFIG')
REFRESH_INTERVAL = get_config('REFRESH_INTERVAL')
LOCATION_UPDATE_INTERVAL = get_config('LOCATION_UPDATE_INTERVAL')
WALKING_SPEED = get_config('WALKING_SPEED')

# Update API URLs
API_CONFIG = get_config('API_CONFIG')
API_URL = f"{API_CONFIG['STIB_API_URL']}/waiting-time-rt-production/records"
STOPS_API_URL = f"{API_CONFIG['STIB_API_URL']}/stop-details-production/records"
MESSAGES_API_URL = f"{API_CONFIG['STIB_API_URL']}/travellers-information-rt-production/records"

CACHE_DIR = get_config('CACHE_DIR')
STOPS_CACHE_FILE = CACHE_DIR / "stops.json"
CACHE_DURATION = get_config('CACHE_DURATION')

# Create cache directory if it doesn't exist
CACHE_DIR.mkdir(exist_ok=True)

PORT = get_config('PORT')

# In-memory cache for service messages
service_messages_cache = {
    'timestamp': None,
    'data': None
}



TIMEZONE = pytz.timezone(get_config('TIMEZONE')) 

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



# Create a global rate limiter instance
rate_limiter = RateLimiter()



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

# Add this near the top with other cache variables
waiting_times_cache = {}
WAITING_TIMES_CACHE_DURATION = timedelta(seconds=30)

# Add these near the top with other cache variables
ROUTES_CACHE_FILE = CACHE_DIR / "routes.json"


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



@app.template_filter('stop_name')
def stop_name_filter(stop_id: str) -> str:
    """Template filter to convert stop ID to name"""
    return get_stop_names([stop_id])[stop_id]['name']

@app.template_filter('stop_coordinates')
def stop_coordinate_filter(stop_id: str) -> dict:
    """Template filter to get stop coordinates from cache"""
    try:
        with open(STOPS_CACHE_FILE, 'r') as f:
            stops_data = json.load(f)
            logger.debug(f"Looking up coordinates for stop {stop_id}")
            
            # First try the original stop ID
            if stop_id in stops_data:
                coords = stops_data[stop_id].get('coordinates', {})
                logger.debug(f"Found coordinates for stop {stop_id}: {coords}")
                return coords
                
            # If not found, try appending letters A-G
            for suffix in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                modified_id = f"{stop_id}{suffix}"
                if modified_id in stops_data:
                    coords = stops_data[modified_id].get('coordinates', {})
                    logger.debug(f"Found coordinates for modified stop ID {modified_id}: {coords}")
                    return coords
                    
            logger.warning(f"Stop {stop_id} not found in cache (including letter suffixes)")
    except Exception as e:
        logger.error(f"Error getting coordinates for stop {stop_id}: {e}")
    return {}

async def get_next_buses():
    logger.debug("Starting get_next_buses function")
    all_stops_data = {}
    errors = []
    shape_errors = []
    service_messages = []
    shapes_data = {}  # Initialize shapes dictionary
    
    # Get vehicle positions first
    logger.info("Fetching vehicle positions...")
    vehicle_positions = await get_vehicle_positions()
    logger.debug(f"Got raw vehicle positions data: {json.dumps(vehicle_positions, indent=2)}")

    # Process vehicle positions
    logger.debug("Processing vehicle positions...")
    processed_vehicles = await process_vehicle_positions(vehicle_positions)
    logger.debug(f"Processed {len(processed_vehicles)} vehicles")
    
    # Create a dictionary of monitored stops with their line configurations
    monitored_stops_config = {stop['id']: stop.get('lines', {}) for stop in STIB_STOPS}
    
    try:
        delijn_provider = PROVIDERS['delijn']
        # Get De Lijn data
        delijn_data = await delijn_provider.endpoints['data']()
        if delijn_data and delijn_data.get('stops'):
            # Add each De Lijn stop to all_stops_data
            for stop_id, stop_data in delijn_data['stops'].items():
                all_stops_data[stop_id] = {
                    'name': stop_data['name'],
                    'coordinates': stop_data['coordinates'],
                    'lines': stop_data.get('lines', {})
                }
    except Exception as e:
        logger.error(f"Error fetching De Lijn data: {e}")
        errors.append(f"De Lijn data error: {str(e)}")
        # Continue with STIB data even if De Lijn fails

    # Filter vehicles that are before monitored stops
    filtered_vehicles = []
    for vehicle in processed_vehicles:
        if not vehicle.is_valid:
            continue
            
        try:
            # Get route variants for this line
            route_variants = await validate_line_stops(vehicle.line)
            
            # Find the matching route variant for this vehicle's direction
            route_variant = next(
                (variant for variant in route_variants 
                 if variant.direction == vehicle.direction),
                None
            )
            
            if route_variant:
                # Create a mapping of base stop IDs to their positions in the sequence
                stops_sequence = {}
                for idx, stop in enumerate(route_variant.stops):
                    # Strip all suffixes and leading zeros
                    base_stop_id = str(stop['id']).lstrip('0').rstrip('A').rstrip('B').rstrip('C').rstrip('D').rstrip('E').rstrip('F').rstrip('G').rstrip('H')
                    stops_sequence[base_stop_id] = idx
                
                logger.debug(f"Stops sequence for line {vehicle.line}: {stops_sequence}")
                
                # Find the vehicle's current position in the sequence
                try:
                    current_index = -1
                    for stop_id in vehicle.current_segment:
                        # Strip all suffixes and leading zeros
                        base_stop_id = str(stop_id).lstrip('0').rstrip('A').rstrip('B').rstrip('C').rstrip('D').rstrip('E').rstrip('F').rstrip('G').rstrip('H')
                        
                        if base_stop_id in stops_sequence:
                            current_index = stops_sequence[base_stop_id]
                            logger.debug(f"Found stop {base_stop_id} at index {current_index}")
                            break
                    
                    if current_index == -1:
                        logger.warning(f"Could not find stops {vehicle.current_segment} in route variant for line {vehicle.line}")
                        logger.debug(f"Available stop IDs in variant: {list(stops_sequence.keys())}")
                        continue
                    
                    # Check if any monitored stops are after the current position
                    has_upcoming_monitored_stop = False
                    for stop_id in monitored_stops_config:
                        base_monitored_stop = str(stop_id).lstrip('0').rstrip('A').rstrip('B').rstrip('C').rstrip('D').rstrip('E').rstrip('F').rstrip('G').rstrip('H')
                        
                        if base_monitored_stop in stops_sequence:
                            stop_index = stops_sequence[base_monitored_stop]
                            if stop_index > current_index:
                                # Check if this stop is monitoring this line/direction
                                stop_config = next(s for s in STIB_STOPS if s['id'] == stop_id)
                                if (vehicle.line in stop_config.get('lines', {}) and 
                                    stop_config.get('direction') == vehicle.direction):
                                    has_upcoming_monitored_stop = True
                                    logger.debug(f"Vehicle on line {vehicle.line} at stop {current_index} is approaching monitored stop {stop_id} at position {stop_index}")
                                    break
                    
                    if has_upcoming_monitored_stop:
                        filtered_vehicles.append(vehicle)
                        logger.debug(f"Added vehicle on line {vehicle.line} to filtered list")
                    else:
                        stop_names = get_stop_names(vehicle.current_segment)
                        
                        logger.debug(f"Vehicle on line {vehicle.line} is not approaching any monitored stops. Current segment: {stop_names}, Direction: {vehicle.direction}")
                except Exception as e:
                    logger.warning(f"Error checking vehicle position for line {vehicle.line}: {str(e)}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error filtering vehicle on line {vehicle.line}: {str(e)}")
            continue

    # Log the filtering results
    logger.info(f"Filtered from {len(processed_vehicles)} to {len(filtered_vehicles)} vehicles")
    if FILTER_VEHICLES:
        processed_vehicles = filtered_vehicles
    else:
        processed_vehicles = processed_vehicles
    
    # For each vehicle, calculate its interpolated position
    logger.debug("Calculating interpolated positions...")
    for i, vehicle in enumerate(processed_vehicles):
        logger.debug(f"\nProcessing vehicle {i+1}/{len(processed_vehicles)}:")
        logger.debug(f"  Line: {vehicle.line}")
        logger.debug(f"  Direction: {vehicle.direction}")
        logger.debug(f"  Current segment: {vehicle.current_segment}")
        logger.debug(f"  Distance to next: {vehicle.distance_to_next:.1f}m")
        logger.debug(f"  Segment length: {vehicle.segment_length:.1f}m")
        logger.debug(f"  Is valid: {vehicle.is_valid}")

        if vehicle.is_valid:
            try:
                # Get route variants for this line
                route_variants = await validate_line_stops(vehicle.line)  # Add await here
                
                # Now we can iterate over the awaited result
                route_variant = next(
                    (variant for variant in route_variants 
                     if variant.direction == vehicle.direction),
                    None
                )
                logger.debug("  Calculating interpolated position...")
                position = interpolate_position(vehicle)
                if position:
                    vehicle.interpolated_position = position
                    logger.debug(f"  Interpolated position: {position}")
                else:
                    vehicle.interpolated_position = None
                    logger.info("  Failed to interpolate position")
            except Exception as e:
                import traceback
                logger.error(f"Error processing record: {str(e)}")
                logger.error(traceback.format_exc())
                errors.append(f"Error processing record: {str(e)}")
                continue
        else:
            logger.info("  Skipping interpolation - vehicle position invalid")

    # Create a dictionary of monitored stops with their line configurations
    monitored_stops_config = {stop['id']: stop.get('lines', {}) for stop in STIB_STOPS}
    
    # Collect monitored lines and stops
    monitored_lines = set()
    monitored_stops = set(monitored_stops_config.keys())
    for stop in STIB_STOPS:
        if stop['lines']:
            monitored_lines.update(stop['lines'].keys())
    
    # Try to fetch route shapes and stops
    for line in monitored_lines:
        try:
            route_data = await get_route_data(line)
            if route_data:
                filtered_variants = []
                for variant in route_data[line]:
                    # Check if this variant's direction matches any monitored stop
                    is_monitored_direction = False
                    for stop in STIB_STOPS:
                        if (line in stop.get('lines', {}) and 
                            stop.get('direction') == variant['direction']):
                            is_monitored_direction = True
                            break
                    
                    if is_monitored_direction:
                        filtered_variants.append(variant)
                
                if filtered_variants:
                    shapes_data[line] = filtered_variants
        except Exception as e:
            shape_errors.append(f"Error fetching route data for line {line}: {e}")

    # Get route colors
    try:
        route_colors = await get_route_colors(monitored_lines)
        logger.debug(f"Route colors: {route_colors}")
    except Exception as e:
        errors.append(f"Error fetching route colors: {str(e)}")
        route_colors = {}
    
    # Get service messages
    try:
        service_messages = await get_service_messages(monitored_lines, monitored_stops)
    except Exception as e:
        errors.append(f"Error fetching service messages: {str(e)}")
        service_messages = []
    
    # Process each monitored stop
    async with await get_client() as client:
        # Build a single query for all stops
        stop_ids = list(monitored_stops_config.keys())
        stop_conditions = [f'pointid="{stop_id}"' for stop_id in stop_ids]
        combined_where = ' or '.join(stop_conditions)
        
        try:
            # Check rate limits before making request
            if not rate_limiter.can_make_request():
                logger.warning("Rate limit exceeded, skipping waiting times request")
                return {
                    'stops_data': {},
                    'errors': ['Rate limit exceeded'],
                    'messages': [],
                    'route_colors': route_colors,
                }

            # Get waiting times for all stops in one request
            params = {
                'where': combined_where,
                'limit': 100,  # Increased to accommodate multiple stops
                'apikey': API_KEY
            }
            
            response = await client.get(API_URL, params=params)
            # Update rate limits from response headers
            rate_limiter.update_from_headers(response.headers)
            
            data = response.json()
            
            # Process the results for all stops
            for record in data.get('results', []):
                try:
                    stop_id = str(record.get('pointid'))
                    line = str(record.get('lineid'))
                    
                    # Skip if this stop is not in our monitored stops
                    if stop_id not in monitored_stops_config:
                        continue
                        
                    # Skip if this line is not in allowed_lines for this stop
                    allowed_lines = monitored_stops_config[stop_id]
                    if allowed_lines and line not in allowed_lines:
                        continue
                    
                    # Initialize the stop data if needed
                    if stop_id not in all_stops_data:
                        all_stops_data[stop_id] = {
                            'name': next((s['name'] for s in STIB_STOPS if s['id'] == stop_id), stop_id),
                            'lines': defaultdict(lambda: defaultdict(list)),  # Changed to nested defaultdict
                            'coordinates': next((s.get('coordinates', {}) for s in STIB_STOPS if s['id'] == stop_id), {})
                        }
                    
                    # Process passing times
                    passing_times = json.loads(record.get('passingtimes', '[]'))
                    
                    for passing_time in passing_times:
                        # Skip if the line ID doesn't match
                        if str(passing_time.get('lineId')) != line:
                            continue
                        
                        # Get destination with all language versions
                        destination_data = passing_time.get('destination', {})
                        
                        # For backward compatibility and logging
                        destination = destination_data.get('fr', 'Unknown')

                        # Check if this destination is unexpected for this line
                        if (allowed_lines and line in allowed_lines and 
                            allowed_lines[line] and 
                            not any(matches_destination(allowed_dest, destination_data) 
                                   for allowed_dest in allowed_lines[line])):
                            logger.warning(
                                f"Unexpected destination '{destination}' for line {line} at stop {stop_id} "
                                f"(configured destinations: {allowed_lines[line]})"
                            )
                            continue

                        # Get message if it exists
                        message = ''
                        if isinstance(passing_time.get('message'), dict):
                            message = passing_time['message'].get('en', '')
                        
                        # Add to lines data, grouped by destination
                        expected_time = passing_time.get('expectedArrivalTime', '')
                        if expected_time:
                            time_logger.debug(f"\nProcessing time for line {line} to {destination}")
                            time_logger.debug(f"Raw expected time from API: {expected_time}")
                            
                            arrival_dt = datetime.fromisoformat(expected_time)
                            time_logger.debug(f"Parsed arrival time: {arrival_dt}")
                            time_logger.debug(f"Arrival timezone info: {arrival_dt.tzinfo}")
                            
                            if arrival_dt.tzinfo is None:
                                arrival_dt = TIMEZONE.localize(arrival_dt)
                                time_logger.debug(f"After Brussels localization: {arrival_dt}")
                            
                            now = datetime.now(TIMEZONE)
                            time_logger.debug(f"Current time (Brussels): {now}")
                            time_logger.debug(f"Current timezone info: {now.tzinfo}")
                            
                            diff_seconds = (arrival_dt - now).total_seconds()
                            minutes = int(diff_seconds // 60)
                            time_logger.debug(f"Time difference in seconds: {diff_seconds}")
                            time_logger.debug(f"Calculated minutes: {minutes}")
                            formatted_time = arrival_dt.strftime('%H:%M')
                            time_logger.debug(f"Formatted time: {formatted_time}")
                        else:
                            minutes = ''
                            formatted_time = ''

                        logger.debug(f"Adding to stops_data - minutes value: {minutes}")

                        all_stops_data[stop_id]['lines'][line][destination].append({
                            'destination': destination,
                            'minutes': minutes,
                            'message': message,
                            'formatted_time': formatted_time
                        })

                        logger.debug(f"Added data: {all_stops_data[stop_id]['lines'][line][destination][-1]}")
                    
                except Exception as e:
                    logger.error(f"Error processing record for stop {stop_id}: {str(e)}")
                    continue
                    
        except Exception as e:
            error_msg = f"Error fetching waiting times: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)

    logger.debug("Final all_stops_data:")
    logger.debug(json.dumps(all_stops_data, indent=2, default=str))

    return {
        'display_stops': STIB_STOPS,
        'stops': all_stops_data,
        'stops_data': all_stops_data,
        'messages': service_messages,
        'errors': errors,
        'shape_errors': shape_errors,
        'route_colors': route_colors,
        'shapes': shapes_data,
        'vehicle_positions': vehicle_positions,
        'processed_vehicles': processed_vehicles
    }





@app.route('/')
async def index():
    app.logger.info('Received request for index page')
    try:
        # Load cached route colors
        route_colors = {}
        try:
            if ROUTES_CACHE_FILE.exists():
                with open(ROUTES_CACHE_FILE, 'r') as f:
                    cache_data = json.load(f)
                    route_colors = cache_data.get('data', {})
        except Exception as e:
            logger.error(f"Error loading cached route colors: {e}")

        # Get De Lijn config for stop IDs
        delijn_provider = PROVIDERS['delijn']
        delijn_config = await delijn_provider.endpoints['config']()

        return render_template('index.html',
            stops=STIB_STOPS,
            initial_load=True,
            route_colors=route_colors,
            DELIJN_STOP_IDS=delijn_config['stops'],
            map_config=MAP_CONFIG,
            refresh_interval=REFRESH_INTERVAL,
            location_update_interval=LOCATION_UPDATE_INTERVAL,
            walking_speed=WALKING_SPEED
        )
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return f"Error: {str(e)}", 500

# Add error handling for missing API key
if not API_KEY:
    raise ValueError("STIB_API_KEY not found in environment variables. Please add it to your .env file.")

# Add this function near the top of your file, after creating the Flask app
@app.template_filter('proper_title')
def proper_title(text):
    """Convert text to title case, handling special cases"""
    # List of words that should remain uppercase
    uppercase_words = {'uz', 'vub', 'ulb'}
    
    # Split on spaces and hyphens
    words = text.lower().replace('-', ' - ').split()
    
    # Process each word
    formatted_words = []
    for word in words:
        # Handle words with periods (abbreviations)
        if '.' in word:
            # Split by period and capitalize each part
            parts = word.split('.')
            formatted_parts = [p.upper() if p.lower() in uppercase_words else p.capitalize() for p in parts]
            formatted_words.append('.'.join(formatted_parts))
        elif word in uppercase_words:
            formatted_words.append(word.upper())
        else:
            formatted_words.append(word.capitalize())
    
    return ' '.join(formatted_words)

# Add this function near the top with other utility functions
def calculate_minutes_until(target_time: str, now: datetime = None) -> str:
    """Calculate minutes until a target time, using fresh now time"""
    if now is None:
        now = datetime.now(TIMEZONE)
    else:
        now = now.astimezone(TIMEZONE)
    
    # Parse the target time
    if isinstance(target_time, str):
        if 'T' in target_time:  # ISO format
            target_dt = datetime.fromisoformat(target_time.replace('Z', '+00:00'))
            target_dt = target_dt.astimezone(TIMEZONE)
        else:  # HH:MM format
            target_dt = datetime.strptime(target_time, "%H:%M").replace(
                year=now.year,
                month=now.month,
                day=now.day,
                tzinfo=TIMEZONE
            )
            
            # If the time is more than 4 hours in the past, assume it's for tomorrow
            if (now - target_dt).total_seconds() > 4 * 3600:
                target_dt += timedelta(days=1)
    else:
        target_dt = target_time.astimezone(TIMEZONE)
        
    # Calculate difference directly in minutes
    diff = (target_dt - now).total_seconds() / 60
    minutes = int(diff)
    return f"{minutes}'"

# Update the get_data route to recalculate times before sending
@app.route('/api/data')
async def get_data():
    try:
        data = await get_next_buses()
        return {
            'stops_data': data['stops_data'],
            'messages': data['messages'],
            'processed_vehicles': data['processed_vehicles'],
            'errors': data['errors']
        }
    except Exception as e:
        logger.error(f"Error in data route: {e}")
        return {"error": str(e)}, 500

@app.route('/api/stop_coordinates/<stop_id>')
async def get_stop_coordinates(stop_id):
    """API endpoint to get stop coordinates from cache"""
    try:
        coordinates = stop_coordinate_filter(stop_id)
        return {'coordinates': coordinates}
    except Exception as e:
        logger.error(f"Error getting coordinates for stop {stop_id}: {e}")
        return {'error': str(e)}, 500

@app.route('/api/stop_names', methods=['POST'])
async def get_stop_names_api():
    """API endpoint to get stop names from cache"""
    try:
        # Get stop IDs from request body - remove await
        stop_ids = request.get_json()
        if not isinstance(stop_ids, list):
            return {'error': 'Expected list of stop IDs'}, 400
            
        # Use existing function to get stop names
        stop_names = get_stop_names(stop_ids)
        return {'stops': stop_names}
    except Exception as e:
        logger.error(f"Error getting stop names: {e}")
        return {'error': str(e)}, 500

@app.route('/api/static_data')
async def get_static_data():
    """Endpoint for static data like routes, stops, and colors"""
    try:
        monitored_lines = set()
        monitored_stops = set()
        for stop in STIB_STOPS:
            if stop['lines']:
                monitored_lines.update(stop['lines'].keys())
            monitored_stops.add(stop['id'])

        shapes_data = {}
        shape_errors = []
        
        # Get route shapes
        for line in monitored_lines:
            try:
                route_data = await get_route_data(line)
                if route_data:
                    filtered_variants = []
                    for variant in route_data[line]:
                        is_monitored_direction = False
                        for stop in STIB_STOPS:
                            if (line in stop.get('lines', {}) and 
                                stop.get('direction') == variant['direction']):
                                is_monitored_direction = True
                                break
                        
                        if is_monitored_direction:
                            filtered_variants.append(variant)
                    
                    if filtered_variants:
                        shapes_data[line] = filtered_variants
            except Exception as e:
                shape_errors.append(f"Error fetching route data for line {line}: {e}")

        # Get route colors
        try:
            route_colors = await get_route_colors(monitored_lines)
        except Exception as e:
            route_colors = {}
            shape_errors.append(f"Error fetching route colors: {str(e)}")

        return {
            'display_stops': STIB_STOPS,
            'shapes': shapes_data,
            'route_colors': route_colors,
            'errors': shape_errors
        }
        
    except Exception as e:
        logger.error(f"Error fetching static data: {e}")
        return {"error": str(e)}, 500
    



# Add these routes after your existing routes

# Get the registered provider

@app.route('/api/<provider>/<endpoint>', methods=['GET', 'POST'])
@app.route('/api/<provider>/<endpoint>/<param1>', methods=['GET', 'POST'])
@app.route('/api/<provider>/<endpoint>/<param1>/<param2>', methods=['GET', 'POST'])
async def provider_endpoint(provider, endpoint, param1=None, param2=None):
    """Generic endpoint for accessing transit provider data"""
    logger.debug(f"Provider endpoint called: {provider}/{endpoint} with params: {param1}, {param2}")
    
    try:
        if provider not in PROVIDERS:
            available_providers = list(PROVIDERS.keys())
            return jsonify({
                'error': f'Provider "{provider}" not found',
                'available_providers': available_providers,
                'example_urls': [
                    f'/api/{p}/data' for p in available_providers
                ],
                'documentation': '/api/docs/v2'
            }), 404
            
        provider_data = PROVIDERS[provider]
        
        if endpoint not in provider_data.endpoints:
            available_endpoints = list(provider_data.endpoints.keys())
            return jsonify({
                'error': f'Endpoint "{endpoint}" not found for provider "{provider}"',
                'available_endpoints': available_endpoints,
                'example_urls': [
                    f'/api/{provider}/{ep}' for ep in available_endpoints
                ]
            }), 404
            
        func = provider_data.endpoints[endpoint]

        # Handle different endpoint types
        if endpoint == 'stops':
            # For POST requests with stop IDs
            if request.method == 'POST':
                stop_ids = request.get_json()
                result = await func(stop_ids)
            # For GET requests (all stops)
            else:
                result = await func()
        elif endpoint == 'stop':
            # Use param1 as stop_id
            if param1:
                result = await func(param1)
            else:
                return jsonify({'error': f'Stop ID required for {endpoint} endpoint'}), 400
        elif endpoint == 'vehicles':
            # First check query parameters
            line = request.args.get('line', param1)  # Use param1 as fallback
            direction = request.args.get('direction', param2)  # Use param2 as fallback
            
            # Handle line and direction
            if line and direction:  # Both line and direction provided
                result = await func(line, direction)
            elif line:  # Only line provided
                result = await func(line)
            else:
                result = await func()
        elif endpoint in ['route', 'colors']:
            # Use param1 as line number
            if param1:
                result = await func(param1)
            else:
                return jsonify({'error': f'Line number required for {endpoint} endpoint'}), 400
        else:
            # Default behavior for other endpoints
            if asyncio.iscoroutinefunction(func):
                result = await func()
            else:
                result = func()

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in provider endpoint {provider}/{endpoint}: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/<provider>/lines/<line>/<endpoint>')
async def provider_line_endpoint(provider, line, endpoint):
    """Route handler for line-specific endpoints"""
    logger.debug(f"Line-specific endpoint called: {provider}/lines/{line}/{endpoint}")
    return await provider_endpoint(provider, endpoint, line)

@app.route('/api/health')
@app.route('/health')
def health_check():
    """Health check endpoint for Docker container."""
    return jsonify({"status": "healthy"}), 200

@app.route('/api/docs') # For backwards compatibility
@app.route('/api/docs/v2')
async def api_docs_v2():
    """Enhanced documentation endpoint that dynamically discovers all provider endpoints"""
    
    # Get provider documentation
    provider_docs = await get_provider_docs()
    
    api_spec = {
        "version": "2.0.0",
        "base_url": "/api",
        "endpoints": {}
    }
    
    # Convert each category's endpoints to a dictionary format
    for category_name, endpoints in provider_docs.items():
        api_spec["endpoints"][category_name] = {}
        for path, endpoint_doc in endpoints.items():
            # Check if endpoint_doc is a dataclass instance
            if hasattr(endpoint_doc, '__dataclass_fields__'):
                # Convert dataclass to dict
                endpoint_dict = asdict(endpoint_doc)
            elif isinstance(endpoint_doc, dict):
                # Already a dict, use as is
                endpoint_dict = endpoint_doc
            else:
                # Convert to dict manually
                endpoint_dict = {
                    "method": getattr(endpoint_doc, 'method', 'GET'),
                    "description": getattr(endpoint_doc, 'description', ''),
                    "parameters": getattr(endpoint_doc, 'parameters', None),
                    "returns": getattr(endpoint_doc, 'returns', None),
                    "body": getattr(endpoint_doc, 'body', None),
                    "example_response": getattr(endpoint_doc, 'example_response', None),
                    "config": getattr(endpoint_doc, 'config', None)
                }
            api_spec["endpoints"][category_name][path] = endpoint_dict
          # Add system endpoints
    api_spec["endpoints"]["System Endpoints"] = {
        "/api/docs/v2": {
            "method": "GET",
            "description": "Enhanced API documentation with dynamic provider discovery",
            "returns": "Complete API specification with examples"
        },
        "/health": {
            "method": "GET",
            "description": "Health check endpoint",
            "returns": {"status": "Current system status"}
        }
    }
    
    # If the request wants HTML (browser), render the template
    if request.headers.get('Accept', '').find('text/html') != -1:
        return render_template('api_docs.html', api_spec=api_spec)
    
    # Otherwise return JSON
    return jsonify(api_spec)

@dataclass
class EndpointDoc:
    method: str
    description: str
    parameters: Optional[Dict[str, str]] = None
    returns: Optional[Dict[str, Any]] = None
    body: Optional[str] = None
    example_response: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

async def get_provider_docs() -> Dict[str, Dict[str, EndpointDoc]]:
    """Dynamically generate documentation for all registered providers"""
    docs = {}
    
    # Sort providers alphabetically to ensure consistent order
    for provider_name in sorted(PROVIDERS.keys()):
        provider = PROVIDERS[provider_name]
        
        # Get provider configuration
        provider_config = {}
        if hasattr(provider, 'config'):
            provider_config = await provider.config() if inspect.iscoroutinefunction(provider.config) else provider.config()
        
        # Create a category name for each provider
        category_name = f"{provider_name.upper()} Endpoints"
        
        for endpoint_name, endpoint_func in provider.endpoints.items():
            try:
                # Get function signature
                sig = signature(endpoint_func)
                params = {}
                
                # Get return type annotation
                return_type = sig.return_annotation if sig.return_annotation != Parameter.empty else None
                
                # Parse docstring to get return value description
                docstring = endpoint_func.__doc__ or ""
                return_desc = ""
                for line in docstring.split('\n'):
                    if ':return:' in line or ':returns:' in line:
                        return_desc = line.split(':', 2)[-1].strip()
                        break
                
                # Build returns documentation
                returns = {
                    "type": str(return_type) if return_type else "any",
                    "description": return_desc,
                }
                
                # If we have an example response, include its structure
                example_response = None
                try:
                    if inspect.iscoroutinefunction(endpoint_func):
                        # For async functions that need parameters, try to use defaults or config values
                        kwargs = {}
                        if 'line' in sig.parameters and hasattr(provider, 'monitored_lines'):
                            kwargs['line'] = next(iter(provider.monitored_lines))
                        if 'stop_id' in sig.parameters and hasattr(provider, 'stop_ids'):
                            kwargs['stop_id'] = next(iter(provider.stop_ids))
                        if kwargs:
                            example_response = await endpoint_func(**kwargs)
                        else:
                            example_response = await endpoint_func()
                    else:
                        example_response = endpoint_func()
                    
                    if example_response:
                        returns["example_structure"] = {
                            "type": type(example_response).__name__,
                            "structure": _describe_structure(example_response)
                        }
                except Exception as e:
                    logger.warning(f"Could not get example response for {provider_name}/{endpoint_name}: {e}")
                
                # Store under the provider-specific category
                if category_name not in docs:
                    docs[category_name] = {}
                docs[category_name][f"/api/{provider_name}/{endpoint_name}"] = EndpointDoc(
                    method="GET",
                    description=docstring,
                    parameters=params if params else None,
                    returns=returns,
                    example_response=example_response,
                    config=provider_config.get(endpoint_name) if provider_config else None
                )
                
            except Exception as e:
                logger.error(f"Error documenting endpoint {endpoint_name}: {e}")
                continue
    
    # Add system endpoints as a separate category
    docs["System Endpoints"] = {
        "/api/docs/v2": {
            "method": "GET",
            "description": "Enhanced API documentation with dynamic provider discovery",
            "returns": "Complete API specification with examples"
        },
        "/health": {
            "method": "GET",
            "description": "Health check endpoint",
            "returns": {"status": "Current system status"}
        }
    }
    
    return docs

def _describe_structure(obj, max_depth=3, current_depth=0):
    """Helper function to describe the structure of an object"""
    if current_depth >= max_depth:
        return "..."
    
    if isinstance(obj, dict):
        return {k: _describe_structure(v, max_depth, current_depth + 1) 
                for k, v in (list(obj.items())[:5] if len(obj) > 5 else obj.items())}
    elif isinstance(obj, (list, tuple)):
        if not obj:
            return "[]"
        return [_describe_structure(obj[0], max_depth, current_depth + 1)] + (["..."] if len(obj) > 1 else [])
    elif isinstance(obj, (int, float)):
        return type(obj).__name__
    elif isinstance(obj, str):
        return "string"
    elif obj is None:
        return "null"
    else:
        return type(obj).__name__

def matches_destination(configured_name: str, destination_data: dict) -> bool:
    """
    Check if a configured destination name matches any language version of the actual destination.
    
    Args:
        configured_name: The destination name from config (e.g., "STOCKEL")
        destination_data: Multilingual destination data (e.g., {"fr": "STOCKEL", "nl": "STOKKEL"})
        
    Returns:
        bool: True if the configured name matches any language version
    """
    if not destination_data or not isinstance(destination_data, dict):
        return False
        
    # Normalize names for comparison (uppercase)
    configured_name = configured_name.upper()
    destination_values = [str(v).upper() for v in destination_data.values()]
    
    return configured_name in destination_values

if __name__ == '__main__':
    app.debug = True
    config = Config()
    
    # Add debug logging
    import socket
    
    # Get all network interfaces
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print(f"\nServer Information:")
    print(f"Hostname: {hostname}")
    print(f"Local IP: {local_ip}")
    
    config.bind = [f"0.0.0.0:{PORT}"]
    config.accesslog = "-"
    config.errorlog = "-"
    
    
    print(f"\nTry accessing the server at:")
    print(f"  Local: http://127.0.0.1:{PORT}")
    print(f"  Network: http://{local_ip}:{PORT}")
    
    asyncio.run(serve(app, config))

