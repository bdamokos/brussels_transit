"""BKK transit provider configuration"""

import os
from pathlib import Path
from transit_providers.config import register_provider_config

# Get the project root from environment variable (set by start.py)
PROJECT_ROOT = Path(os.environ["PROJECT_ROOT"])

# Default configuration
DEFAULT_CONFIG = {
    "PROVIDER_ID": "mdb-990",  # BKK's ID in Mobility Database
    "API_KEY": os.getenv("BKK_API_KEY"),
    "CACHE_DIR": PROJECT_ROOT / "cache" / "bkk",
    "GTFS_DIR": PROJECT_ROOT / "downloads",
    "STOP_IDS": [
        "F01110-config.py"
    ],  # Should be set in local config - F01110 is a test stop
    "MONITORED_LINES": [],  # Should be set in local config
    "RATE_LIMIT_DELAY": 0.5,  # seconds between API calls
    "GTFS_CACHE_DURATION": 86400 * 7,  # 7 days in seconds
}

# Register configuration
register_provider_config("bkk", DEFAULT_CONFIG)
