# app/transit_providers/be/stib/config.py

import os
from pathlib import Path
import logging
from logging.config import dictConfig
from transit_providers.config import get_config, register_provider_config
from datetime import timedelta
# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)
# Get logger
logger = logging.getLogger('stib')

# Register default configuration
DEFAULT_CONFIG = {
    'STIB_STOPS': [
    {
        'id': '5710',  # Example stop - VERBOECKHOVEN (different from global default)
        'name': 'VERBOECKHOVEN',
        'lines': {
            '55': ['DA VINCI', 'ROGIER'],
            '92': ['SCHAERBEEK GARE', 'FORT-JACO']
        },
        "direction": "City"  # or "Suburb"
    } # Example stop, different from default.py to track config precedence
], 
 "API_KEY": os.getenv('STIB_API_KEY'),
 'API_URL': "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets",
    "STIB_API_URL_BASE": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets",
    "STIB_STOPS_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/stop-details-production/records",
    "STIB_WAITING_TIME_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/waiting-time-rt-production/records",
    "STIB_MESSAGES_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/travellers-information-rt-production/records",
    'GTFS_API_URL': "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/gtfs-files-production/records",
    'GTFS_DIR': Path('cache/stib/gtfs'),
    'CACHE_DIR': Path('cache/stib'),
    'STOPS_CACHE_FILE': Path('cache/stib/stops.json'),
    'CACHE_DURATION': timedelta(days=30),
    'RATE_LIMIT_DELAY': 0.5,  # seconds between API calls
    'GTFS_CACHE_DURATION': 86400*30,  # 30 days in seconds
    'GTFS_USED_FILES': ['stops.txt', 'routes.txt', 'trips.txt', 'shapes.txt']
}

logger.debug("Registering STIB default configuration")
# Register this provider's default configuration
register_provider_config('stib', DEFAULT_CONFIG)
logger.debug("STIB default configuration registered")