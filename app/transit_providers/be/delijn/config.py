# app/transit_providers/be/delijn/config.py

import os
from pathlib import Path
import logging
from transit_providers.config import get_config, register_provider_config

# Get logger
logger = logging.getLogger("transit_providers.be.delijn")

# Register default configuration
DEFAULT_CONFIG = {
    "STOP_IDS": ["307250", "307251"],  # Example stops - should be set in local.py
    "MONITORED_LINES": [
        "116",
        "117",
        "118",
        "144",
    ],  # Example lines - should be set in local.py
    "API_URL": "https://api.delijn.be/DLKernOpenData/api/v1",
    "_AVAILABLE_LANGUAGES": ["nl"],  # De Lijn only provides Dutch content
    "GTFS_URL": "https://api.delijn.be/gtfs/static/v3/gtfs_transit.zip",
    "GTFS_DIR": Path("cache/delijn/gtfs"),
    "CACHE_DIR": Path("cache/delijn"),
    "RATE_LIMIT_DELAY": 0.5,  # seconds between API calls
    "GTFS_CACHE_DURATION": 86400 * 30,  # 30 days in seconds
    "API_KEY": os.getenv("DELIJN_API_KEY"),  # Main API key for real-time data
    "GTFS_STATIC_API_KEY": os.getenv(
        "DELIJN_GTFS_STATIC_API_KEY"
    ),  # API key for static GTFS data
    "GTFS_REALTIME_API_KEY": os.getenv(
        "DELIJN_GTFS_REALTIME_API_KEY"
    ),  # API key for GTFS-RT data
    "GTFS_USED_FILES": ["stops.txt", "routes.txt", "trips.txt", "shapes.txt"],
}

logger.debug("Registering De Lijn default configuration")
# Register this provider's default configuration
register_provider_config("delijn", DEFAULT_CONFIG)
logger.debug("De Lijn default configuration registered")
