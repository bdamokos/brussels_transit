from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    abort,
    Response,
    redirect,
)
import html
import json
from datetime import datetime, timedelta
import pytz
import asyncio
from hypercorn.asyncio import serve
from hypercorn.config import Config
from dataclasses import dataclass
from typing import Dict, Any, Optional
from inspect import signature, Parameter
import inspect
import logging
from flask import jsonify
from transit_providers import PROVIDERS, get_provider_from_path
from config import get_config
from dataclasses import asdict
import os
from pathlib import Path
from flask_cors import CORS
import secrets
from functools import wraps
from transit_providers.config import get_provider_config
from functools import lru_cache
import niquests as requests
import re
import socket
import psutil

# Get loggers
logger = logging.getLogger("main")
time_logger = logging.getLogger("main.time")
api_logger = logging.getLogger("main.api")
vehicle_logger = logging.getLogger("main.vehicles")

app = Flask(__name__)
# Enable CORS for all routes
CORS(
    app,
    resources={
        r"/api/*": {  # This will enable CORS for all routes under /api/
            "origins": ["*"],  # Allow all origins
            "methods": ["GET", "POST", "OPTIONS"],  # Allow these methods
            "allow_headers": ["Content-Type", "Authorization"],  # Allow these headers
        }
    },
)

# Proxy configuration - place at the start to handle matching routes before legacy endpoints
SCHEDULE_EXPLORER_PORT = get_config("SCHEDULE_EXPLORER_PORT", "8000")
SCHEDULE_EXPLORER_HOST = get_config("SCHEDULE_EXPLORER_HOST", "localhost")

# Regular expression to match provider-id format (e.g., "abc-1234")
PROVIDER_ID_PATTERN = re.compile(r"^[a-zA-Z]+-\d+$")

FILTER_VEHICLES = True

# Get API key from environment variable
#API_KEY = get_required_config("STIB_API_KEY")

# Get provider configs
stib_config = get_provider_config("stib")
STIB_STOPS = stib_config.get("STIB_STOPS", [])

# Keep these as they are global configs, not provider-specific
MAP_CONFIG = get_config("MAP_CONFIG")
REFRESH_INTERVAL = get_config("REFRESH_INTERVAL")
LOCATION_UPDATE_INTERVAL = get_config("LOCATION_UPDATE_INTERVAL")
WALKING_SPEED = get_config("WALKING_SPEED")

# Update API URLs
API_CONFIG = get_config("API_CONFIG", {})

CACHE_DIR = get_config("CACHE_DIR", "cache")
CACHE_DURATION = get_config("CACHE_DURATION", 3600)

# Create cache directory if it doesn't exist
# CACHE_DIR.mkdir(exist_ok=True)

PORT = get_config("PORT")

# In-memory cache for service messages
service_messages_cache = {"timestamp": None, "data": None}

local_timezone = datetime.now().astimezone().tzname()
if local_timezone=="CEST":
    local_timezone="CET"
TIMEZONE = pytz.timezone(local_timezone)


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
ROUTES_CACHE_FILE = Path(CACHE_DIR) / "routes.json"


# Initialize routes_cache at startup
routes_cache = {"timestamp": None, "data": None}


@app.template_filter("stop_name")
@lru_cache(maxsize=128)  # Cache up to 128 stop names
def stop_name_filter(stop_id: str) -> str:
    """Template filter to convert stop ID to name using the v2 API endpoint"""
    try:
        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider

        provider = StibProvider()

        # Convert async to sync using asyncio
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_data = loop.run_until_complete(provider.get_stop(stop_id))
        loop.close()

        # Return the name from the response
        return stop_data.get("name", f"Unknown stop {stop_id}")
    except Exception as e:
        logger.error(f"Error getting name for stop {stop_id}: {e}")
        return f"Error: {stop_id}"


@app.template_filter("stop_coordinates")
@lru_cache(maxsize=128)  # Cache up to 128 sets of coordinates
def stop_coordinate_filter(stop_id: str) -> dict:
    """Template filter to get stop coordinates from cache"""
    try:
        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider

        provider = StibProvider()

        # Convert async to sync using asyncio
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_data = loop.run_until_complete(provider.get_stop(stop_id))
        loop.close()

        # Return the coordinates from the response
        return stop_data.get("coordinates", {})
    except Exception as e:
        logger.error(f"Error getting coordinates for stop {stop_id}: {e}")
        return {}


@app.route("/")
async def index():
    app.logger.info("Received request for index page")
    try:
        # Load cached route colors
        route_colors = {}
        try:
            if ROUTES_CACHE_FILE.exists():
                with open(ROUTES_CACHE_FILE, "r") as f:
                    cache_data = json.load(f)
                    route_colors = cache_data.get("data", {})
            elif not ROUTES_CACHE_FILE.exists():
                logger.warning("Routes cache file not found, creating empty cache")
                with open(ROUTES_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
                logger.info("Created empty routes cache file")
        except Exception as e:
            logger.error(f"Error loading cached route colors: {e}")

        # Get provider configs
        stib_config = get_provider_config("stib")
        STIB_STOPS = stib_config.get("STIB_STOPS", [])

        # Get De Lijn config
        if "delijn" in PROVIDERS:
            delijn_provider = PROVIDERS["delijn"]
            delijn_config = await delijn_provider.endpoints["config"]()
        else:
            delijn_config = {}
            delijn_config["stops"] = []
            delijn_config["monitored_lines"] = []

        return render_template(
            "index.html",
            stops=STIB_STOPS,  # Now using the provider-specific config
            initial_load=True,
            route_colors=route_colors,
            DELIJN_STOP_IDS=delijn_config["stops"],
            DELIJN_MONITORED_LINES=delijn_config["monitored_lines"],
            map_config=MAP_CONFIG,
            refresh_interval=REFRESH_INTERVAL,
            location_update_interval=LOCATION_UPDATE_INTERVAL,
            walking_speed=WALKING_SPEED,
        )
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return f"Error: Error in index route", 500


# Add error handling for missing API key
# if not API_KEY:
#     raise ValueError(
#         "STIB_API_KEY not found in environment variables. Please add it to your .env file."
#     )


# Add this function near the top of your file, after creating the Flask app
@app.template_filter("proper_title")
def proper_title(text):
    """Convert text to title case, handling special cases"""
    # List of words that should remain uppercase
    uppercase_words = {"uz", "vub", "ulb"}

    # Split on spaces and hyphens
    words = text.lower().replace("-", " - ").split()

    # Process each word
    formatted_words = []
    for word in words:
        # Handle words with periods (abbreviations)
        if "." in word:
            # Split by period and capitalize each part
            parts = word.split(".")
            formatted_parts = [
                p.upper() if p.lower() in uppercase_words else p.capitalize()
                for p in parts
            ]
            formatted_words.append(".".join(formatted_parts))
        elif word in uppercase_words:
            formatted_words.append(word.upper())
        else:
            formatted_words.append(word.capitalize())

    return " ".join(formatted_words)


# Update the get_data route to recalculate times before sending
@app.route("/api/data")
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
        if "error" in v2_response:
            return {"error": v2_response["error"]}, 500

        # Convert v2 format to v1 format
        v1_response = convert_v2_to_v1_format(v2_response)

        return v1_response
    except Exception as e:
        logger.error(f"Error in data route: {e}")
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"error": "Error in data route"}, 500


@app.route("/api/stop_coordinates/<stop_id>")
async def get_stop_coordinates(stop_id):
    """Legacy v1 endpoint to get stop coordinates from cache"""
    try:
        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider

        provider = StibProvider()

        # Get data from v2 endpoint
        v2_response = await provider.get_stop_coordinates(stop_id)

        # Check for error
        if "error" in v2_response:
            return v2_response, 500

        # Add deprecation notice
        v2_response["_deprecated"] = (
            "This endpoint is deprecated. Please use /api/stib/stop/{id}/coordinates instead."
        )

        # Return coordinates with deprecation notice
        return v2_response
    except Exception as e:
        logger.error(f"Error getting coordinates for stop {html.escape(stop_id)}: {e}")
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {
            "error": f"Error getting coordinates for stop {html.escape(stop_id)}"
        }, 500


@app.route("/api/stop_names", methods=["POST"])
async def get_stop_names_api():
    """Legacy v1 endpoint to get stop names from cache"""
    try:
        # Get stop IDs from request body
        stop_ids = request.get_json()
        if not isinstance(stop_ids, list):
            return {"error": "Expected list of stop IDs"}, 400

        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider

        provider = StibProvider()

        # Get data from v2 endpoint
        v2_response = await provider.get_stops(stop_ids)

        # Check for error
        if "error" in v2_response:
            return v2_response, 500

        # Convert v2 format to v1 format
        v1_response = {}
        for stop_id, stop_data in v2_response.get("stops", {}).items():
            v1_response[stop_id] = {
                "name": stop_data["name"],
                "coordinates": stop_data["coordinates"],
            }

        # Add deprecation notice
        return {
            "stops": v1_response,
            "_deprecated": "This endpoint is deprecated. Please use /api/stib/stops instead.",
        }
    except Exception as e:
        logger.error(f"Error getting stop names: {e}")
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"error": "Error fetching stop names"}, 500


@app.route("/api/static_data")
async def get_static_data():
    """Legacy v1 endpoint for static data like routes, stops, and colors"""
    try:
        # Create StibProvider instance
        from transit_providers.be.stib import StibProvider

        provider = StibProvider()

        # Get data from v2 endpoint
        v2_response = await provider.get_static_data()

        # Check for error
        if "error" in v2_response:
            return {"error": v2_response["error"]}, 500

        # Add deprecation notice to v2 response
        v2_response["_deprecated"] = (
            "This endpoint is deprecated. Please use /api/stib/static instead."
        )

        # Return v2 response with deprecation notice
        return v2_response

    except Exception as e:
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")
        logger.error(f"Error fetching static data: {e}")
        return {"error": "Error fetching static data"}, 500


@app.route("/css/<path:path>")
def serve_css(path):
    return send_from_directory("templates/css", path)


@app.route("/js/<path:path>")
def serve_js(path):
    return send_from_directory("templates/js", path)


@app.route("/images/<path:path>")
def serve_images(path):
    return send_from_directory("templates/images", path)


@app.route("/api/providers")
def get_providers():
    providers_data = {}
    for provider_name, provider in PROVIDERS.items():
        providers_data[provider_name] = {"endpoints": list(provider.endpoints.keys())}
    return jsonify(providers_data)


# Store valid tokens with their expiration time
# In a production environment, you might want to use Redis or a similar solution
valid_tokens = {}


def generate_token():
    """Generate a new token and store it with expiration time"""
    token = secrets.token_urlsafe(32)
    valid_tokens[token] = datetime.now() + timedelta(
        minutes=30
    )  # Token expires in 30 minutes
    return token


def clean_expired_tokens():
    """Remove expired tokens"""
    now = datetime.now()
    expired = [token for token, expiry in valid_tokens.items() if expiry < now]
    for token in expired:
        valid_tokens.pop(token)


def require_valid_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not check_token():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    return decorated_function


@app.route("/api/auth/token")
def get_token():
    """Endpoint to get a new token. This should only be called once when the frontend loads."""
    # Basic protection: only allow requests from our own domain
    origin = request.headers.get("Origin", "")
    referer = request.headers.get("Referer", "")

    if not (
        origin.startswith(request.host_url) or referer.startswith(request.host_url)
    ):
        logger.warning(f"Token request from unauthorized origin: {origin}")
        return jsonify({"error": "Unauthorized"}), 403

    token = generate_token()
    return jsonify({"token": token})


def get_settings_token():
    """Get the settings token from config or generate a new one"""
    token = get_config("SETTINGS_TOKEN")
    if not token:
        # Generate a random token if none exists
        token = secrets.token_urlsafe(32)
        # We should ideally save this to config, but for now just keep in memory
    return token


def check_token():
    """Check if the request has a valid settings token"""
    if request.args.get("debug") == "true":
        return True

    token = request.headers.get("X-Settings-Token")
    clean_expired_tokens()  # Clean expired tokens first
    return token in valid_tokens  # Check if token exists in our valid tokens


@app.route("/api/settings")
def get_settings():
    """Get application settings"""
    if not check_token():
        return jsonify({"error": "Unauthorized"}), 401

    # Get base settings
    settings = {
        "refresh_interval": REFRESH_INTERVAL,
        "location_update_interval": LOCATION_UPDATE_INTERVAL,
        "walking_speed": WALKING_SPEED,
        "language_precedence": get_config("LANGUAGE_PRECEDENCE"),
        "enabled_providers": get_config("ENABLED_PROVIDERS"),
        "port": get_config("PORT"),
        "timezone": get_config("TIMEZONE"),
        "map_config": get_config("MAP_CONFIG"),
        "providers": [],
    }

    # Get enabled providers from the registration system
    enabled = settings["enabled_providers"]

    from transit_providers import PROVIDERS, get_provider_path

    for provider_name in enabled:
        if provider_name in PROVIDERS:
            provider = PROVIDERS[provider_name]
            settings["providers"].append(
                {
                    "name": provider_name,
                    "path": get_provider_path(provider_name),
                    "endpoints": list(provider.endpoints.keys()),
                }
            )

    return jsonify(settings)


# Add provider-specific asset endpoints
@app.route("/api/<provider>/assets")
def get_provider_assets(provider):
    """Get provider-specific assets"""
    if not check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if provider not in PROVIDERS:
        return jsonify({"error": "Provider not found"}), 404

    # Get provider instance
    provider_instance = PROVIDERS[provider]

    # Each provider should implement get_assets() method
    if not hasattr(provider_instance, "get_assets"):
        return jsonify({"error": "Provider does not support assets endpoint"}), 501

    return jsonify(provider_instance.get_assets())


def validate_static_path(base_dir: str, filename: str, allowed_extensions: set) -> bool:
    """Validate a static file path for security.

    Args:
        base_dir: The base directory to serve files from
        filename: The requested filename
        allowed_extensions: Set of allowed file extensions

    Returns:
        bool: True if path is valid, False otherwise
    """
    if not filename or ".." in filename:
        return False

    # Get file extension
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        return False

    # Construct absolute paths
    base_path = os.path.abspath(base_dir)
    file_path = os.path.abspath(os.path.join(base_dir, filename))

    # Check if the file path is within the base directory
    if not file_path.startswith(base_path):
        return False

    # Check if file exists
    if not os.path.isfile(file_path):
        return False

    return True


def is_valid_provider_path(provider_path: str) -> bool:
    """Validate provider path structure.

    Args:
        provider_path: The provider path to validate (e.g. 'be/stib')

    Returns:
        bool: True if path is valid, False otherwise
    """
    # Only allow alphanumeric characters, forward slashes, and underscores
    import re

    if not re.match(r"^[a-zA-Z0-9/_-]+$", provider_path):
        return False

    # No double slashes or leading/trailing slashes
    if (
        "//" in provider_path
        or provider_path.startswith("/")
        or provider_path.endswith("/")
    ):
        return False

    # Maximum two path components (e.g. 'be/stib')
    if len(provider_path.split("/")) > 2:
        return False

    return True


def get_static_provider_dir(provider_path: str, asset_type: str) -> str:
    """Get the static provider directory for a given provider and asset type.

    Args:
        provider_path: The provider path (e.g. 'be/stib')
        asset_type: The asset type ('js' or 'css')

    Returns:
        str: The absolute path to the static provider directory
    """
    # Validate provider path structure
    if not is_valid_provider_path(provider_path):
        abort(403)

    # Get and validate provider
    provider = get_provider_from_path(provider_path)
    if not provider or provider not in PROVIDERS:
        abort(404)

    # Only allow js and css directories
    if asset_type not in {"js", "css"}:
        abort(403)

    # Construct and validate the absolute provider directory path
    provider_dir = os.path.abspath(
        os.path.join("transit_providers", provider_path, asset_type)
    )
    base_dir = os.path.abspath("transit_providers")

    # Ensure the provider directory is within the base directory
    if not provider_dir.startswith(base_dir):
        abort(403)

    return provider_dir


@app.route("/transit_providers/<path:provider_path>/js/<path:filename>")
def serve_provider_js(provider_path, filename):
    # Get the validated provider directory
    provider_dir = get_static_provider_dir(provider_path, "js")

    # Validate file path
    if not validate_static_path(provider_dir, filename, {".js"}):
        abort(403)

    return send_from_directory(
        provider_dir, filename, mimetype="application/javascript"
    )


@app.route("/transit_providers/<path:provider_path>/css/<path:filename>")
def serve_provider_css(provider_path, filename):
    # Get the validated provider directory
    provider_dir = get_static_provider_dir(provider_path, "css")

    # Validate file path
    if not validate_static_path(provider_dir, filename, {".css"}):
        abort(403)

    return send_from_directory(provider_dir, filename, mimetype="text/css")


@app.route("/static/css/<path:filename>")
def serve_static_css(filename):
    # Validate file path
    if not validate_static_path("static/css", filename, {".css"}):
        abort(403)

    return send_from_directory("static/css", filename, mimetype="text/css")


@app.route("/static/js/core/<path:filename>")
def serve_static_core_js(filename):
    """Serve core JavaScript files"""
    # Validate file path
    if not validate_static_path("templates/js/core", filename, {".js"}):
        abort(403)

    return send_from_directory(
        "templates/js/core", filename, mimetype="application/javascript"
    )


@app.route("/static/js/config/<path:filename>")
def serve_static_config_js(filename):
    """Serve config JavaScript files"""
    # Validate file path
    if not validate_static_path("templates/js/config", filename, {".js"}):
        abort(403)

    return send_from_directory(
        "templates/js/config", filename, mimetype="application/javascript"
    )


# Remove conflicting route and use static_folder instead
app.static_folder = "static"

# Add these routes after your existing routes

# Get the registered provider


@app.route("/api/<provider>/<endpoint>", methods=["GET", "POST"])
@app.route("/api/<provider>/<endpoint>/<param1>", methods=["GET", "POST"])
@app.route("/api/<provider>/<endpoint>/<param1>/<param2>", methods=["GET", "POST"])
async def provider_endpoint(provider, endpoint, param1=None, param2=None):
    """Generic endpoint for accessing transit provider data"""
    logger.debug(
        f"Provider endpoint called: {provider}/{endpoint} with params: {param1}, {param2}"
    )

    try:
        # First check if this is a provider with a dash (e.g., mdb-1234)
        if "-" in provider:
            # Build the redirect URL
            schedule_explorer_url = f"http://{SCHEDULE_EXPLORER_HOST}:{SCHEDULE_EXPLORER_PORT}"
            subpath = endpoint
            if param1:
                subpath = f"{subpath}/{param1}"
            if param2:
                subpath = f"{subpath}/{param2}"
            url = f"{schedule_explorer_url}/api/{provider}/{subpath}"
            
            # Add query parameters
            params = request.args.to_dict()
            if params:
                url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
            
            # Redirect to the schedule explorer
            return redirect(url)

        # If not a proxied provider, check if it's a legacy provider
        if provider not in PROVIDERS:
            available_providers = list(PROVIDERS.keys())
            return (
                jsonify(
                    {
                        "error": f'Provider "{provider}" not found',
                        "available_providers": available_providers,
                        "example_urls": [f"/api/{p}/data" for p in available_providers],
                        "documentation": "/api/docs/v2",
                    }
                ),
                404,
            )

        provider_data = PROVIDERS[provider]

        if endpoint not in provider_data.endpoints:
            available_endpoints = list(provider_data.endpoints.keys())
            return (
                jsonify(
                    {
                        "error": f'Endpoint "{endpoint}" not found for provider "{provider}"',
                        "available_endpoints": available_endpoints,
                        "example_urls": [
                            f"/api/{provider}/{ep}" for ep in available_endpoints
                        ],
                    }
                ),
                404,
            )

        func = provider_data.endpoints[endpoint]

        # Handle different endpoint types
        if endpoint == "waiting_times":
            # Get stop_id from query parameter or path parameter
            stop_id = request.args.get("stop_id", param1)
            if stop_id:
                # Handle comma-separated stop IDs
                if "," in stop_id:
                    stop_id = [s.strip() for s in stop_id.split(",")]
                result = await func(stop_id)
            else:
                result = await func()

            # Check for rate limit exceeded
            if result.get("rate_limit_exceeded"):
                return jsonify({
                    "error": "Rate limit exceeded",
                    "reset_time": result.get("reset_time"),
                    "remaining": result.get("remaining")
                }), 429
        elif endpoint == "stops":
            # For POST requests with stop IDs
            if request.method == "POST":
                stop_ids = request.get_json()
                result = await func(stop_ids)
            # For GET requests (all stops)
            else:
                result = await func()
        elif endpoint == "stop":
            # Use param1 as stop_id
            if param1:
                result = await func(param1)
            else:
                return (
                    jsonify({"error": f"Stop ID required for {endpoint} endpoint"}),
                    400,
                )
        elif endpoint == "vehicles":
            # First check query parameters
            line = request.args.get("line", param1)  # Use param1 as fallback
            direction = request.args.get("direction", param2)  # Use param2 as fallback

            # Handle line and direction
            if line and direction:  # Both line and direction provided
                result = await func(line, direction)
            elif line:  # Only line provided
                result = await func(line)
            else:
                result = await func()
        elif endpoint in ["route", "colors"]:
            # Use param1 as line number
            if param1:
                result = await func(param1)
            else:
                return (
                    jsonify({"error": f"Line number required for {endpoint} endpoint"}),
                    400,
                )
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
        return (
            jsonify({"error": f"Error in provider endpoint {provider}/{endpoint}"}),
            500,
        )


@app.route("/api/<provider>/lines/<line>/<endpoint>")
async def provider_line_endpoint(provider, line, endpoint):
    """Route handler for line-specific endpoints"""
    logger.debug(f"Line-specific endpoint called: {provider}/lines/{line}/{endpoint}")
    return await provider_endpoint(provider, endpoint, line)


@app.route("/api/health")
@app.route("/health")
def health_check():
    """Health check endpoint for Docker container."""
    return jsonify({"status": "healthy"}), 200


@app.route("/api/docs")  # For backwards compatibility
@app.route("/api/docs/v2")
async def api_docs_v2():
    """Enhanced documentation endpoint that dynamically discovers all provider endpoints"""

    # Get provider documentation
    provider_docs = await get_provider_docs()

    api_spec = {"version": "2.0.0", "base_url": "/api", "endpoints": {}}

    # Convert each category's endpoints to a dictionary format
    for category_name, endpoints in provider_docs.items():
        api_spec["endpoints"][category_name] = {}
        for path, endpoint_doc in endpoints.items():
            # Check if endpoint_doc is a dataclass instance
            if hasattr(endpoint_doc, "__dataclass_fields__"):
                # Convert dataclass to dict
                endpoint_dict = asdict(endpoint_doc)
            elif isinstance(endpoint_doc, dict):
                # Already a dict, use as is
                endpoint_dict = endpoint_doc
            else:
                # Convert to dict manually
                endpoint_dict = {
                    "method": getattr(endpoint_doc, "method", "GET"),
                    "description": getattr(endpoint_doc, "description", ""),
                    "parameters": getattr(endpoint_doc, "parameters", None),
                    "returns": getattr(endpoint_doc, "returns", None),
                    "body": getattr(endpoint_doc, "body", None),
                    "example_response": getattr(endpoint_doc, "example_response", None),
                    "config": getattr(endpoint_doc, "config", None),
                }
            api_spec["endpoints"][category_name][path] = endpoint_dict
        # Add system endpoints
    api_spec["endpoints"]["System Endpoints"] = {
        "/api/docs/v2": {
            "method": "GET",
            "description": "Enhanced API documentation with dynamic provider discovery",
            "returns": "Complete API specification with examples",
        },
        "/health": {
            "method": "GET",
            "description": "Health check endpoint",
            "returns": {"status": "Current system status"},
        },
    }

    # If the request wants HTML (browser), render the template
    if request.headers.get("Accept", "").find("text/html") != -1:
        return render_template("api_docs.html", api_spec=api_spec)

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
        if hasattr(provider, "config"):
            provider_config = (
                await provider.config()
                if inspect.iscoroutinefunction(provider.config)
                else provider.config()
            )

        # Create a category name for each provider
        category_name = f"{provider_name.upper()} Endpoints"

        for endpoint_name, endpoint_func in provider.endpoints.items():
            try:
                # Get function signature
                sig = signature(endpoint_func)
                params = {}

                # Get return type annotation
                return_type = (
                    sig.return_annotation
                    if sig.return_annotation != Parameter.empty
                    else None
                )

                # Parse docstring to get return value description
                docstring = endpoint_func.__doc__ or ""
                return_desc = ""
                for line in docstring.split("\n"):
                    if ":return:" in line or ":returns:" in line:
                        return_desc = line.split(":", 2)[-1].strip()
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
                        if "line" in sig.parameters and hasattr(
                            provider, "monitored_lines"
                        ):
                            kwargs["line"] = next(iter(provider.monitored_lines))
                        if "stop_id" in sig.parameters and hasattr(
                            provider, "stop_ids"
                        ):
                            kwargs["stop_id"] = next(iter(provider.stop_ids))
                        if kwargs:
                            example_response = await endpoint_func(**kwargs)
                        else:
                            example_response = await endpoint_func()
                    else:
                        example_response = endpoint_func()

                    if example_response:
                        returns["example_structure"] = {
                            "type": type(example_response).__name__,
                            "structure": _describe_structure(example_response),
                        }
                except Exception as e:
                    logger.warning(
                        f"Could not get example response for {provider_name}/{endpoint_name}: {e}"
                    )

                # Store under the provider-specific category
                if category_name not in docs:
                    docs[category_name] = {}
                docs[category_name][f"/api/{provider_name}/{endpoint_name}"] = (
                    EndpointDoc(
                        method="GET",
                        description=docstring,
                        parameters=params if params else None,
                        returns=returns,
                        example_response=example_response,
                        config=(
                            provider_config.get(endpoint_name)
                            if provider_config
                            else None
                        ),
                    )
                )

            except Exception as e:
                logger.error(f"Error documenting endpoint {endpoint_name}: {e}")
                continue

    # Add system endpoints as a separate category
    docs["System Endpoints"] = {
        "/api/docs/v2": {
            "method": "GET",
            "description": "Enhanced API documentation with dynamic provider discovery",
            "returns": "Complete API specification with examples",
        },
        "/health": {
            "method": "GET",
            "description": "Health check endpoint",
            "returns": {"status": "Current system status"},
        },
    }

    return docs


def _describe_structure(obj, max_depth=3, current_depth=0):
    """Helper function to describe the structure of an object"""
    if current_depth >= max_depth:
        return "..."

    if isinstance(obj, dict):
        return {
            k: _describe_structure(v, max_depth, current_depth + 1)
            for k, v in (list(obj.items())[:5] if len(obj) > 5 else obj.items())
        }
    elif isinstance(obj, (list, tuple)):
        if not obj:
            return "[]"
        return [_describe_structure(obj[0], max_depth, current_depth + 1)] + (
            ["..."] if len(obj) > 1 else []
        )
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


# Serve the v2 frontend
@app.route("/v2/")
@app.route("/v2")
def index_v2():
    """Serve the v2 frontend"""
    # Get base configuration
    config = {
        "map_config": get_config("MAP_CONFIG", {}),
        "walking_speed": WALKING_SPEED,
        "location_update_interval": LOCATION_UPDATE_INTERVAL,
        "refresh_interval": REFRESH_INTERVAL,
        "route_colors": {},  # This will be populated by providers
        "stops": [],  # This will be populated by providers
        "DELIJN_STOP_IDS": [],  # This will be populated by De Lijn provider
    }

    return render_template("index_new.html", **config)


# Provider-specific files
@app.route("/transit_providers/<path:path>")
def serve_provider_files(path):
    """Serve provider-specific files"""
    return send_from_directory("transit_providers", path)


@app.route("/favicon.ico")
def favicon():
    """Handle favicon requests without a 404"""
    return "", 204


if __name__ == "__main__":
    app.debug = True
    config = Config()

    # Add debug logging
    import socket
    import psutil

    # Get all network interfaces
    hostname = socket.gethostname()
    
    # Find the first non-loopback IPv4 address
    network_ip = None
    for interface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET:  # IPv4 addresses
                ip = addr.address
                if not ip.startswith('127.'):  # Skip loopback addresses
                    network_ip = ip
                    break
        if network_ip:
            break

    if not network_ip:
        network_ip = "Unable to detect network IP"

    print(f"\nServer Information:")
    print(f"Hostname: {hostname}")
    print(f"Network IP: {network_ip}")

    config.bind = [f"0.0.0.0:{PORT}"]
    config.accesslog = "-"
    config.errorlog = "-"

    print(f"\nTry accessing the server at:")
    print(f"  Local: http://127.0.0.1:{PORT}")
    print(f"  Network: http://{network_ip}:{PORT}")

    asyncio.run(serve(app, config))
