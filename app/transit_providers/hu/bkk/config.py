"""BKK transit provider configuration"""

import os
from pathlib import Path
from transit_providers.config import register_provider_config

# Get the app directory (two levels up from this file)
APP_DIR = Path(__file__).parent.parent.parent.parent

# Default configuration
DEFAULT_CONFIG = {
    'PROVIDER_ID': 'mdb-990',  # BKK's ID in Mobility Database
    'API_KEY': os.getenv('BKK_API_KEY'),
    'CACHE_DIR': APP_DIR / 'cache' / 'bkk',
    'GTFS_DIR': APP_DIR / 'cache' / 'bkk' / 'gtfs',
    'STOP_IDS': [],  # Should be set in local config
    'MONITORED_LINES': [],  # Should be set in local config
    'RATE_LIMIT_DELAY': 0.5,  # seconds between API calls
    'GTFS_CACHE_DURATION': 86400 * 7,  # 7 days in seconds
}

# Register configuration
register_provider_config('bkk', DEFAULT_CONFIG) 