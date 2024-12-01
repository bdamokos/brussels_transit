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
        elif not ROUTES_CACHE_FILE.exists():
            logger.warning("Routes cache file not found, creating empty cache")
            # Create empty cache file
            with open(ROUTES_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            logger.info("Created empty routes cache file")
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
            elif not ROUTES_CACHE_FILE.exists():
                logger.warning("Routes cache file not found, creating empty cache")
                # Create empty cache file
                with open(ROUTES_CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump({}, f)
                logger.info("Created empty routes cache file")
        except Exception as cache_e:
            logger.error(f"Error loading routes cache: {cache_e}\n{traceback.format_exc()}")
        
        # Return empty dictionary if everything fails
        return route_colors

# Initialize routes_cache at startup
routes_cache = {
    'timestamp': None,
    'data': None
}

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
    except FileNotFoundError:
        logger.warning(f"Stops cache file not found, creating empty cache")
        # Create empty cache file
        with open(STOPS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        logger.info("Created empty stops cache file")
    except Exception as e:
        logger.error(f"Error getting coordinates for stop {stop_id}: {e}")
    return {}




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
            elif not ROUTES_CACHE_FILE.exists():
                logger.warning("Routes cache file not found, creating empty cache")
                # Create empty cache file
                with open(ROUTES_CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump({}, f)
                logger.info("Created empty routes cache file")
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

# Update the get_data route to recalculate times before sending
@app.route('/api/data')
async def get_data():
    """Legacy v1 endpoint for all real-time data"""
    try:
        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider
        from transit_providers.be.stib.api import convert_v2_to_v1_format
        provider = StibProvider()
            
        # Get data from v2 endpoint
        v2_response = await provider.get_data()
        
        # Check for error
        if 'error' in v2_response:
            return {"error": v2_response['error']}, 500
            
        # Convert v2 format to v1 format
        v1_response = convert_v2_to_v1_format(v2_response)
            
        return v1_response
    except Exception as e:
        logger.error(f"Error in data route: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"error": str(e)}, 500

@app.route('/api/stop_coordinates/<stop_id>')
async def get_stop_coordinates(stop_id):
    """Legacy v1 endpoint to get stop coordinates from cache"""
    try:
        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider
        provider = StibProvider()
            
        # Get data from v2 endpoint
        v2_response = await provider.get_stop_coordinates(stop_id)
        
        # Check for error
        if 'error' in v2_response:
            return v2_response, 500
            
        # Add deprecation notice
        v2_response['_deprecated'] = 'This endpoint is deprecated. Please use /api/stib/stop/{id}/coordinates instead.'
            
        # Return coordinates with deprecation notice
        return v2_response
    except Exception as e:
        logger.error(f"Error getting coordinates for stop {stop_id}: {e}")
        return {'error': str(e)}, 500

@app.route('/api/stop_names', methods=['POST'])
async def get_stop_names_api():
    """Legacy v1 endpoint to get stop names from cache"""
    try:
        # Get stop IDs from request body
        stop_ids = request.get_json()
        if not isinstance(stop_ids, list):
            return {'error': 'Expected list of stop IDs'}, 400
            
        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider
        provider = StibProvider()
            
        # Get data from v2 endpoint
        v2_response = await provider.get_stops(stop_ids)
        
        # Check for error
        if 'error' in v2_response:
            return v2_response, 500
            
        # Convert v2 format to v1 format
        v1_response = {}
        for stop_id, stop_data in v2_response.get('stops', {}).items():
            v1_response[stop_id] = {
                'name': stop_data['name'],
                'coordinates': stop_data['coordinates']
            }
            
        # Add deprecation notice
        return {
            'stops': v1_response,
            '_deprecated': 'This endpoint is deprecated. Please use /api/stib/stops instead.'
        }
    except Exception as e:
        logger.error(f"Error getting stop names: {e}")
        return {'error': str(e)}, 500

@app.route('/api/static_data')
async def get_static_data():
    """Legacy v1 endpoint for static data like routes, stops, and colors"""
    try:
        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider
        provider = StibProvider()
            
        # Get data from v2 endpoint
        v2_response = await provider.get_static_data()
        
        # Check for error
        if 'error' in v2_response:
            return {"error": v2_response['error']}, 500
            
        # Add deprecation notice to v2 response
        v2_response['_deprecated'] = 'This endpoint is deprecated. Please use /api/stib/static instead.'
        
        # Return v2 response with deprecation notice
        return v2_response
        
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

