"""
Default configuration settings.
These are the base settings that can be overridden by local.py
"""

import dotenv
import os
from datetime import timedelta
from pathlib import Path
import pytz
dotenv.load_dotenv()

# Provider Configuration
ENABLED_PROVIDERS = [
    'delijn',  # List of enabled transit providers
    'stib',
    'bkk'
]

# Port
PORT = os.getenv('PORT', 5001) # If changed, the Dockerfile and docker-compose.yaml need to be updated manually

# API Keys
STIB_API_KEY = os.getenv('STIB_API_KEY')
BKK_API_KEY = os.getenv('BKK_API_KEY')

# Logging Configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        },
        'simple': {
            'format': '%(levelname)s - %(message)s'
        }
    },
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/app.log',
            'maxBytes': 1024 * 1024,  # 1MB
            'backupCount': 5,
            'formatter': 'standard',
            'level': 'DEBUG'
        },
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'level': 'INFO'
        }
    },
    'loggers': {
        '': {  # Root logger - this will be used as default for any undefined logger
            'handlers': ['console', 'file'],
            'level': 'INFO'
        },
        'main.api': {  # Only specify loggers that need different settings from default
            'level': 'WARNING',
            'propagate': True
        },
        'bkk': {
            'level': 'DEBUG',
            'propagate': False
        },
        'transit_providers': {
            'level': 'DEBUG',
            'propagate': False
        }
    },
    'log_dir': Path('logs')
}

# Map default settings
MAP_CONFIG = {
    "center": {
        "lat": 50.85,
        "lon": 4.35
    },
    "zoom": 15,
    "min_zoom": 11,
    "max_zoom": 19
}

# STIB/MIVB Configuration
STIB_STOPS = [
    {
        'id': '8122',  # Example stop - ROODEBEEK
        'name': 'ROODEBEEK',
        'lines': {
            '1': ['STOCKEL', "GARE DE L'OUEST"],
            '5': ['STOCKEL', "GARE DE L'OUEST"]
        },
        "direction": "Suburb"  # or "City"
    }
]



# API Configuration
API_CONFIG = {
    "STIB_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets",
    "STIB_STOPS_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/stop-details-production/records",
    "DELIJN_API_URL": "https://api.delijn.be/DLKernOpenData/api/v1",
    "DELIJN_GTFS_URL": "https://api.delijn.be/gtfs/static/v3/gtfs_transit.zip"
}

# Cache Configuration
CACHE_DIR = Path("cache")
STOPS_CACHE_FILE = CACHE_DIR / "stops.json"
CACHE_DURATION = timedelta(days=30)
GTFS_CACHE_DURATION = timedelta(days=30)
REALTIME_CACHE_DURATION = 30  # seconds

# Refresh intervals
REFRESH_INTERVAL = 60  # seconds
LOCATION_UPDATE_INTERVAL = 300  # seconds (5 minutes)

# Walking speed for distance calculations
WALKING_SPEED = 1.4  # meters per second (5 km/h)

# Timezone
TIMEZONE = "Europe/Brussels"

# Rate limiting for outside API calls
RATE_LIMIT_DELAY = 1.0  # Delay in seconds between API calls