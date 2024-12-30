"""BKK transit provider"""

# First import the config to ensure defaults are registered
from . import config

from dataclasses import dataclass
from typing import Dict, Any, Callable, Awaitable, List
from transit_providers.config import get_provider_config
from config import get_config
import logging
from logging.config import dictConfig
from transit_providers import TransitProvider, register_provider
import asyncio

# Setup logging using configuration
logging_config = get_config("LOGGING_CONFIG")
dictConfig(logging_config)

# Get logger
logger = logging.getLogger("bkk")

from .api import (
    bkk_config,
    get_waiting_times,
    get_service_alerts,
    get_vehicle_positions,
    get_static_data,
    get_line_info,
    get_route_shapes,
    get_route_variants_api,
    get_line_colors,
)

provider_config = get_provider_config("bkk")
logger.info("=== BKK CONFIG DEBUG ===")
logger.info(f"Raw config: {provider_config}")
logger.info("=== END BKK CONFIG DEBUG ===")

GTFS_DIR = provider_config.get("GTFS_DIR")
CACHE_DIR = provider_config.get("CACHE_DIR")


class BKKProvider(TransitProvider):
    """BKK transit provider"""

    def __init__(self):
        # Initialize monitored lines and stops from config
        self.monitored_lines = []
        self.stop_ids = []

        config = get_provider_config("bkk")
        self.stop_ids = config.get("STOP_IDS", [])
        self.monitored_lines = config.get("MONITORED_LINES", [])

        # Define all endpoints
        endpoints = {
            "config": bkk_config,
            "waiting_times": get_waiting_times,
            "messages": get_service_alerts,
            "vehicles": get_vehicle_positions,
            "static_data": get_static_data,
            "line_info": get_line_info,
            "route": get_route_variants_api,
            "colors": get_line_colors,
        }

        # Call parent class constructor
        super().__init__(name="bkk", endpoints=endpoints)
        logger.info(
            f"BKK provider initialized with endpoints: {list(self.endpoints.keys())}"
        )

        # Initialize caches
        loop = asyncio.get_event_loop()
        loop.run_until_complete(api._ensure_caches_initialized())

    async def get_waiting_times(self, stop_id: str) -> Dict[str, Any]:
        """Get waiting times for a stop"""
        return await get_waiting_times(stop_id)


# Only create and register provider if it's enabled
if "bkk" in get_config("ENABLED_PROVIDERS", []):
    try:
        provider = BKKProvider()
        register_provider("bkk", provider)
        logger.info("BKK provider registered successfully")
    except Exception as e:
        logger.error(f"Failed to register BKK provider: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
else:
    logger.warning("BKK provider is not enabled in configuration")

__all__ = [
    "bkk_config",
    "get_waiting_times",
    "get_service_alerts",
    "get_vehicle_positions",
    "get_static_data",
    "get_line_info",
    "get_route_variants_api",
    "get_line_colors",
]
