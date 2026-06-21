"""Le TEC transit provider configuration."""

import os
from pathlib import Path

from transit_providers.be.mobility import mobility_url
from transit_providers.config import register_provider_config

PROJECT_ROOT = Path(os.environ["PROJECT_ROOT"])
LETEC_CACHE_DIR = PROJECT_ROOT / "cache" / "letec"

APIM_FEED_SLUG = os.getenv("LETEC_APIM_FEED_SLUG", "tec")

DEFAULT_CONFIG = {
    "PROVIDER_ID": "f-u0g-tec",
    "APIM_FEED_SLUG": APIM_FEED_SLUG,
    "MOBILITY_API_PRIMARY_KEY": os.getenv("MOBILITY_API_PRIMARY_KEY"),
    "MOBILITY_API_SECONDARY_KEY": os.getenv("MOBILITY_API_SECONDARY_KEY"),
    "CACHE_DIR": LETEC_CACHE_DIR,
    "GTFS_STATIC_SOURCE": os.getenv("LETEC_GTFS_STATIC_SOURCE", "belgian_mobility"),
    "GTFS_STATIC_URL": os.getenv(
        "LETEC_GTFS_STATIC_URL",
        mobility_url(f"/api/gtfs/feed/{APIM_FEED_SLUG}/static"),
    ),
    "GTFS_STATIC_FALLBACK_URLS": [
        url
        for url in [
            os.getenv("LETEC_GTFS_STATIC_FALLBACK_URL"),
            "https://opendata.tec-wl.be/Current%20GTFS/TEC-GTFS.zip",
        ]
        if url
    ],
    "GTFS_STATIC_DIR": LETEC_CACHE_DIR / "gtfs",
    "GTFS_STATIC_METADATA_FILE": LETEC_CACHE_DIR / "gtfs" / "metadata.json",
    "GTFS_USED_FILES": ["stops.txt", "routes.txt", "trips.txt", "stop_times.txt"],
    "GTFS_CACHE_DURATION": 86400,
    "REALTIME_SOURCE": os.getenv("LETEC_REALTIME_SOURCE", "belgian_mobility"),
    "TRIP_UPDATES_URL": os.getenv(
        "LETEC_GTFS_RT_TRIP_UPDATES_URL",
        mobility_url(f"/api/gtfs/feed/{APIM_FEED_SLUG}/rt/trip-update"),
    ),
    "SERVICE_ALERTS_URL": os.getenv(
        "LETEC_GTFS_RT_SERVICE_ALERTS_URL",
        mobility_url(f"/api/gtfs/feed/{APIM_FEED_SLUG}/rt/alert"),
    ),
    "STOP_IDS": [],
    "MONITORED_LINES": [],
    "RATE_LIMIT_DELAY": 0.5,
}

register_provider_config("letec", DEFAULT_CONFIG)
