from flask import Flask, render_template, request, jsonify, send_from_directory
import json
from datetime import datetime, timedelta
import pytz
from get_stop_names import get_stop_names
import asyncio
from hypercorn.asyncio import serve
from hypercorn.config import Config
from dataclasses import dataclass
from typing import Dict, Any, Optional
from inspect import signature, Parameter
import inspect
import logging
from logging.config import dictConfig
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
        if 'delijn' in PROVIDERS:
            delijn_provider = PROVIDERS['delijn']
            delijn_config = await delijn_provider.endpoints['config']()
        else:
            delijn_config = {}
            delijn_config['stops'] = []
            delijn_config['monitored_lines'] = []

        return render_template('index.html',
            stops=STIB_STOPS,
            initial_load=True,
            route_colors=route_colors,
            DELIJN_STOP_IDS=delijn_config['stops'],
            DELIJN_MONITORED_LINES=delijn_config['monitored_lines'],
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
    

@app.route('/css/<path:path>')
def serve_css(path):
    return send_from_directory('templates/css', path)

@app.route('/js/<path:path>')
def serve_js(path):
    return send_from_directory('templates/js', path)

@app.route('/images/<path:path>')
def serve_images(path):
    return send_from_directory('templates/images', path)

@app.route('/api/providers')
def get_providers():
    providers_data = {}
    for provider_name, provider in PROVIDERS.items():
        providers_data[provider_name] = {
            'endpoints': list(provider.endpoints.keys())
        }
    return jsonify(providers_data)

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

