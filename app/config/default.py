"""
Default configuration settings.
These are the base settings that can be overridden by local.py
"""

import dotenv
import os
from datetime import timedelta
from pathlib import Path
import pytz

dotenv.load_dotenv(override=True)

# Get project root from environment variable (set by start.py)
PROJECT_ROOT = Path(os.environ["PROJECT_ROOT"])

# Provider Configuration
ENABLED_PROVIDERS = [
    "delijn",
    "stib",
    "bkk",
    "sncb",
]  # List of enabled transit providers

# Language Configuration
LANGUAGE_PRECEDENCE = ["en", "hu", "fr", "nl", "de"]  # Default language fallback chain

# Port
PORT = os.getenv(
    "PORT", 5001
)  # If changed, the Dockerfile and docker-compose.yaml need to be updated manually

# API Keys
STIB_API_KEY = os.getenv("STIB_API_KEY")
BKK_API_KEY = os.getenv("BKK_API_KEY")

# Logging Configuration
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"},
        "simple": {"format": "%(levelname)s - %(message)s"},
    },
    "handlers": {
        "legacy_app": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str((PROJECT_ROOT / "logs" / "legacy_app.log").absolute()),
            "maxBytes": 1024 * 1024,  # 1MB
            "backupCount": 3,
            "formatter": "standard",
            "level": "DEBUG",
            "mode": "a",
        },
        "schedule_explorer": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(
                (PROJECT_ROOT / "logs" / "schedule_explorer.log").absolute()
            ),
            "maxBytes": 1024 * 1024,  # 1MB
            "backupCount": 3,
            "formatter": "standard",
            "level": "DEBUG",
            "mode": "a",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
            "level": "INFO",
        },
    },
    "loggers": {
        "": {"handlers": ["console"], "level": "INFO"},  # Root logger
        "app": {  # Legacy app logger
            "handlers": ["legacy_app", "console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "schedule_explorer": {  # Schedule explorer logger
            "handlers": ["schedule_explorer", "console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "bkk": {
            "handlers": ["legacy_app", "console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "transit_providers": {
            "handlers": ["legacy_app", "console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
    "log_dir": PROJECT_ROOT / "logs",  # This is now relative to the project root
}

# Map default settings
MAP_CONFIG = {
    "center": {"lat": 50.85, "lon": 4.35},
    "zoom": 15,
    "min_zoom": 11,
    "max_zoom": 19,
}

# API Configuration
API_CONFIG = {
    "STIB_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets",
    "STIB_STOPS_API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets/stop-details-production/records",
    "DELIJN_API_URL": "https://api.delijn.be/DLKernOpenData/api/v1",
    "DELIJN_GTFS_URL": "https://api.delijn.be/gtfs/static/v3/gtfs_transit.zip",
}

# Cache Configuration
CACHE_DIR = PROJECT_ROOT / "cache"
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

PROVIDER_CONFIG = {
    "bkk": {
        "provider_specific": {
            "PROVIDER_ID": "mdb-990",  # BKK's ID in Mobility DB
            "API_KEY": os.getenv("BKK_API_KEY"),
            "CACHE_DIR": CACHE_DIR / "bkk",
            "GTFS_DIR": PROJECT_ROOT / "downloads",
            "RATE_LIMIT_DELAY": 0.5,  # 500ms between API calls
            "GTFS_CACHE_DURATION": 7 * 24 * 60 * 60,  # 7 days in seconds
        },
        "stops": [
            {
                "id": "F01111-default.py",  # Wesselényi utca / Erzsébet körút
                "name": "Wesselényi utca / Erzsébet körút",
                "lines": {
                    "3060": [
                        {  # This feature is not used by the app, but could be in the future
                            "type": "direction_name",
                            "value": "Széll Kálmán tér M",
                        }
                    ]
                },
            }
        ],
        "monitored_lines": ["3060"],
    },
    "stib": {
        "provider_specific": {
            "API_KEY": os.getenv("STIB_API_KEY"),
            "_AVAILABLE_LANGUAGES": ["en", "fr", "nl"],
            "API_URL": "https://data.stib-mivb.brussels/api/explore/v2.1/catalog/datasets",
            "GTFS_DIR": PROJECT_ROOT / "cache" / "stib" / "gtfs",
            "CACHE_DIR": PROJECT_ROOT / "cache" / "stib",
            "STOPS_CACHE_FILE": PROJECT_ROOT / "cache" / "stib" / "stops.json",
            "CACHE_DURATION": timedelta(days=30),
            "RATE_LIMIT_DELAY": 0.5,
            "GTFS_CACHE_DURATION": 86400 * 30,  # 30 days in seconds
            "GTFS_USED_FILES": [
                "stops.txt",
                "routes.txt",
                "trips.txt",
                "shapes.txt",
                "translations.txt",
            ],
        },
        "stops": [
            {
                "id": "8122",
                "name": "ROODEBEEK",
                "lines": {
                    "1": [
                        {"type": "stop_name", "value": "STOCKEL"},
                        {"type": "stop_name", "value": "GARE DE L'OUEST"},
                    ],
                    "5": [
                        {"type": "stop_name", "value": "STOCKEL"},
                        {"type": "stop_name", "value": "GARE DE L'OUEST"},
                    ],
                },
                "direction": "Suburb",
            }
        ],
    },
    "delijn": {
        "provider_specific": {
            "API_URL": "https://api.delijn.be/DLKernOpenData/api/v1",
            "_AVAILABLE_LANGUAGES": ["nl"],
            "GTFS_URL": "https://api.delijn.be/gtfs/static/v3/gtfs_transit.zip",
            "GTFS_DIR": CACHE_DIR / "delijn/gtfs",
            "CACHE_DIR": CACHE_DIR / "delijn",
            "RATE_LIMIT_DELAY": 0.5,
            "GTFS_CACHE_DURATION": 86400 * 30,  # 30 days in seconds
            "API_KEY": os.getenv("DELIJN_API_KEY"),
            "GTFS_STATIC_API_KEY": os.getenv("DELIJN_GTFS_STATIC_API_KEY"),
            "GTFS_REALTIME_API_KEY": os.getenv("DELIJN_GTFS_REALTIME_API_KEY"),
            "GTFS_USED_FILES": ["stops.txt", "routes.txt", "trips.txt", "shapes.txt"],
        },
        "stops": [
            {
                "id": "307250",
                "name": "Haren",
                "lines": {
                    "272": [{"type": "direction_name", "value": "Heen"}],
                    "282": [{"type": "direction_name", "value": "Heen"}],
                },
            },
            {
                "id": "307251",
                "name": "Haren",
                "lines": {
                    "272": [{"type": "direction_name", "value": "Terug"}],
                    "282": [{"type": "direction_name", "value": "Terug"}],
                },
            },
        ],
        "monitored_lines": ["116", "117", "118", "144"],
    },
}
