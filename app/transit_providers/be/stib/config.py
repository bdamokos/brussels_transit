# app/transit_providers/be/delijn/config.py

import os
from pathlib import Path
from transit_providers.config import register_provider_config
import logging
from logging.config import dictConfig
from transit_providers.config import get_config
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
        'id': '8122',  # Example stop - ROODEBEEK
        'name': 'ROODEBEEK',
        'lines': {
            '1': ['STOCKEL', "GARE DE L'OUEST"],
            '5': ['STOCKEL', "GARE DE L'OUEST"]
        },
        "direction": "Suburb"  # or "City"
    } # Example stop, update in local.py
], 
 "API_KEY": os.getenv('STIB_API_KEY'),
    "STIB_API_URL_BASE": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets",
    "STIB_STOPS_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/stop-details-production/records",
    "STIB_WAITING_TIME_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/waiting-time-rt-production/records",
    "STIB_MESSAGES_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/travellers-information-rt-production/records",

    'GTFS_DIR': Path('cache/stib/gtfs'),
    'CACHE_DIR': Path('cache/stib'),
    'CACHE_DURATION': timedelta(days=30),
    'RATE_LIMIT_DELAY': 0.5,  # seconds between API calls
    'GTFS_CACHE_DURATION': 86400*30,  # 30 days in seconds

}

logger.debug("Registering STIB default configuration")
# Register this provider's default configuration
register_provider_config('delijn', DEFAULT_CONFIG)
logger.debug("De Lijn default configuration registered")