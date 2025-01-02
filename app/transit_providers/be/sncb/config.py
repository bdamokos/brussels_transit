"""SNCB transit provider configuration"""

import os
from pathlib import Path
from transit_providers.config import register_provider_config

# Get the project root from environment variable (set by start.py)
PROJECT_ROOT = Path(os.environ["PROJECT_ROOT"])

# Default configuration
DEFAULT_CONFIG = {
    "PROVIDER_ID": "mdb-1859",  # SNCB's ID in Mobility Database
    "API_KEY": os.getenv("SNCB_API_KEY"),
    "CACHE_DIR": PROJECT_ROOT / "cache" / "sncb",
    "GTFS_DIR": PROJECT_ROOT / "downloads",
    "STOP_IDS": [
        "8813003"  # Brussels Central as a test stop
    ],  # Should be set in local config
    "MONITORED_LINES": [],  # Should be set in local config
    "RATE_LIMIT_DELAY": 0.5,  # seconds between API calls
    "GTFS_CACHE_DURATION": 86400 * 7,  # 7 days in seconds
    "REALTIME_URL": os.getenv("SNCB_GTFS_REALTIME_API_URL"),
}

# Register configuration
register_provider_config("sncb", DEFAULT_CONFIG)
