# app/transit_providers/be/delijn/config.py

import os
from pathlib import Path
from transit_providers.config import register_provider_config
import logging

# Get logger
logger = logging.getLogger('delijn')

# Register default configuration
DEFAULT_CONFIG = {
    'STOP_IDS': [],  # Default empty, should be set in local config
    'MONITORED_LINES': [],  # Default empty, should be set in local config
    'API_URL': 'https://api.delijn.be/DLKernOpenData/api/v1',
    'GTFS_URL': 'https://api.delijn.be/DLKernOpenData/v1/gtfs/static',
    'GTFS_DIR': Path('cache/delijn/gtfs'),
    'CACHE_DIR': Path('cache/delijn'),
    'RATE_LIMIT_DELAY': 0.5,  # seconds between API calls
    'GTFS_CACHE_DURATION': 86400*30,  # 30 days in seconds
    'API_KEY': os.getenv('DELIJN_API_KEY'),  # Main API key for real-time data
    'GTFS_STATIC_API_KEY': os.getenv('DELIJN_GTFS_STATIC_API_KEY'),  # API key for static GTFS data
    'GTFS_REALTIME_API_KEY': os.getenv('DELIJN_GTFS_REALTIME_API_KEY')  # API key for GTFS-RT data
}

logger.debug("Registering De Lijn default configuration")
# Register this provider's default configuration
register_provider_config('delijn', DEFAULT_CONFIG)
logger.debug("De Lijn default configuration registered")