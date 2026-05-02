# app/transit_providers/be/stib/config.py

import os
from pathlib import Path
import logging
from transit_providers.config import get_config, register_provider_config
from datetime import timedelta

# Get logger
logger = logging.getLogger("stib")

# Get project root from environment variable (set by start.py)
PROJECT_ROOT = Path(os.environ["PROJECT_ROOT"])

from .mobility import mobility_url

# Register default configuration
DEFAULT_CONFIG = {
    "STIB_STOPS": [
        {
            "id": "5710",  # Example stop - VERBOECKHOVEN (different from global default)
            "name": "VERBOECKHOVEN",
            "lines": {
                "55": ["DA VINCI", "ROGIER"],
                "92": ["SCHAERBEEK GARE", "FORT-JACO"],
            },
            "direction": "City",  # or "Suburb"
        }  # Example stop, different from default.py to track config precedence
    ],
    # Legacy app token (Open Data Soft); optional fallback if mobility keys unset
    "API_KEY": os.getenv("STIB_API_KEY"),
    "MOBILITY_API_PRIMARY_KEY": os.getenv("MOBILITY_API_PRIMARY_KEY"),
    "MOBILITY_API_SECONDARY_KEY": os.getenv("MOBILITY_API_SECONDARY_KEY"),
    "_AVAILABLE_LANGUAGES": [
        "en",
        "fr",
        "nl",
    ],  # Languages available in STIB API responses
    # Belgian Mobility Open Data Portal (Azure APIM) — Explore-compatible dataset paths
    "API_URL": mobility_url("/api/datasets/stibmivb"),
    "STIB_API_URL_BASE": mobility_url("/api/datasets/stibmivb"),
    "STIB_STOPS_API_URL": mobility_url("/api/datasets/stibmivb/static/stopDetails"),
    "STIB_WAITING_TIME_API_URL": mobility_url("/api/datasets/stibmivb/rt/WaitingTimes"),
    "STIB_MESSAGES_API_URL": mobility_url(
        "/api/datasets/stibmivb/rt/TravellersInformation"
    ),
    "STIB_VEHICLE_POSITIONS_API_URL": mobility_url(
        "/api/datasets/stibmivb/rt/VehiclePositions"
    ),
    "STIB_STOPS_BY_LINE_API_URL": mobility_url(
        "/api/datasets/stibmivb/static/stopsByLine"
    ),
    "STIB_SHAPEFILES_API_URL": mobility_url(
        "/api/datasets/stibmivb/static/shape-files"
    ),
    "GTFS_STATIC_FEED_URL": mobility_url("/api/gtfs/feed/stibmivb/static"),
    "GTFS_API_URL": mobility_url("/api/gtfs/feed/stibmivb/static"),
    "GTFS_DIR": PROJECT_ROOT / "cache" / "stib" / "gtfs",
    "CACHE_DIR": PROJECT_ROOT / "cache" / "stib",
    "STOPS_CACHE_FILE": PROJECT_ROOT / "cache" / "stib" / "stops.json",
    "CACHE_DURATION": timedelta(days=30),
    "RATE_LIMIT_DELAY": 0.5,  # seconds between API calls
    "GTFS_CACHE_DURATION": 86400 * 30,  # 30 days in seconds
    "GTFS_USED_FILES": [
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "shapes.txt",
        "translations.txt",
    ],
}

logger.debug("Registering STIB default configuration")
# Register this provider's default configuration
register_provider_config("stib", DEFAULT_CONFIG)
logger.debug("STIB default configuration registered")
