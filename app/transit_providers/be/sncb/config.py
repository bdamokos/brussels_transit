"""SNCB transit provider configuration"""

import os
from pathlib import Path
from transit_providers.config import register_provider_config
from transit_providers.be.mobility import mobility_url

# Get the project root from environment variable (set by start.py)
PROJECT_ROOT = Path(os.environ["PROJECT_ROOT"])
SNCB_CACHE_DIR = PROJECT_ROOT / "cache" / "sncb"

# Default configuration
DEFAULT_CONFIG = {
    "PROVIDER_ID": "mdb-1859",  # SNCB's ID in Mobility Database
    "API_KEY": os.getenv("SNCB_API_KEY"),
    "MOBILITY_API_PRIMARY_KEY": os.getenv("MOBILITY_API_PRIMARY_KEY"),
    "MOBILITY_API_SECONDARY_KEY": os.getenv("MOBILITY_API_SECONDARY_KEY"),
    "CACHE_DIR": SNCB_CACHE_DIR,
    "GTFS_DIR": PROJECT_ROOT / "downloads",
    "GTFS_STATIC_SOURCE": os.getenv("SNCB_GTFS_STATIC_SOURCE", "belgian_mobility"),
    "GTFS_STATIC_URL": os.getenv(
        "SNCB_GTFS_STATIC_URL",
        mobility_url("/api/gtfs/feed/nmbssncb/static"),
    ),
    "GTFS_STATIC_DIR": SNCB_CACHE_DIR / "gtfs",
    "GTFS_STATIC_METADATA_FILE": SNCB_CACHE_DIR / "gtfs" / "metadata.json",
    "STOP_IDS": [
        "8813003"  # Brussels Central as a test stop
    ],  # Should be set in local config
    "MONITORED_LINES": [],  # Should be set in local config
    "RATE_LIMIT_DELAY": 0.5,  # seconds between API calls
    "GTFS_CACHE_DURATION": 86400 * 7,  # 7 days in seconds
    "REALTIME_SOURCE": os.getenv("SNCB_REALTIME_SOURCE", "belgian_mobility"),
    "APIM_TRIP_UPDATES_URL": os.getenv(
        "SNCB_BELGIAN_MOBILITY_TRIP_UPDATES_URL",
        mobility_url("/api/gtfs/feed/nmbssncb/rt/trip-update"),
    ),
    "LEGACY_REALTIME_URL": os.getenv("SNCB_LEGACY_GTFS_REALTIME_API_URL")
    or os.getenv("SNCB_GTFS_REALTIME_API_URL"),
    "REALTIME_URL": os.getenv(
        "SNCB_BELGIAN_MOBILITY_TRIP_UPDATES_URL",
        mobility_url("/api/gtfs/feed/nmbssncb/rt/trip-update"),
    ),
}

# Register configuration
register_provider_config("sncb", DEFAULT_CONFIG)
