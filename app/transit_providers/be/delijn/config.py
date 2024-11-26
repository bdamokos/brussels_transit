# app/transit_providers/be/delijn/config.py

import os
from pathlib import Path
from transit_providers.config import register_provider_config
import logging
from logging.config import dictConfig
from transit_providers.config import get_config

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)
# Get logger
logger = logging.getLogger('delijn')

# Register default configuration
DEFAULT_CONFIG = {
    'STOP_IDS': ["307250", "307251"],  # Example stops - should be set in local.py
    'MONITORED_LINES': ["116","117", '118'],  # Example lines - should be set in local.py
    'API_URL': 'https://api.delijn.be/DLKernOpenData/api/v1',
    'GTFS_URL': 'https://api.delijn.be/gtfs/static/v3/gtfs_transit.zip',
    'GTFS_DIR': Path('cache/delijn/gtfs'),
    'CACHE_DIR': Path('cache/delijn'),
    'RATE_LIMIT_DELAY': 0.5,  # seconds between API calls
    'GTFS_CACHE_DURATION': 86400*30,  # 30 days in seconds
    'API_KEY': os.getenv('DELIJN_API_KEY'),  # Main API key for real-time data
    'GTFS_STATIC_API_KEY': os.getenv('DELIJN_GTFS_STATIC_API_KEY'),  # API key for static GTFS data
    'GTFS_REALTIME_API_KEY': os.getenv('DELIJN_GTFS_REALTIME_API_KEY'),  # API key for GTFS-RT data
    'GTFS_USED_FILES': ['stops.txt', 'routes.txt', 'trips.txt', 'shapes.txt']
}

logger.debug("Registering De Lijn default configuration")
# Register this provider's default configuration
register_provider_config('delijn', DEFAULT_CONFIG)
logger.debug("De Lijn default configuration registered")