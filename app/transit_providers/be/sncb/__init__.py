"""SNCB transit provider"""

# First import the config to ensure defaults are registered
from . import config

from dataclasses import dataclass
from typing import Dict, Any, Callable, Awaitable, List
from transit_providers.config import get_provider_config
from config import get_config
import logging
from transit_providers import TransitProvider, register_provider, PROVIDERS
from flask import request
import asyncio


# Get logger
logger = logging.getLogger("sncb")

from .api import (
    sncb_config,
    get_waiting_times,
    get_static_data,
    get_line_info,
)

provider_config = get_provider_config("sncb")
logger.info("=== SNCB CONFIG DEBUG ===")
logger.info(f"Raw config: {provider_config}")
logger.info("=== END SNCB CONFIG DEBUG ===")

GTFS_DIR = provider_config.get("GTFS_DIR")
CACHE_DIR = provider_config.get("CACHE_DIR")


class SNCBProvider(TransitProvider):
    """SNCB transit provider"""

    def __init__(self):
        # Initialize monitored lines and stops from config
        self.monitored_lines = []
        self.stop_ids = []

        config = get_provider_config("sncb")
        self.stop_ids = config.get("STOP_IDS", [])
        self.monitored_lines = config.get("MONITORED_LINES", [])

        # Define all endpoints
        self.endpoints = {
            "waiting_times": get_waiting_times,
            "static_data": get_static_data,
            "line_info": get_line_info,
        }

        # Call parent class constructor
        super().__init__(name="sncb", endpoints=self.endpoints)
        logger.info(
            f"SNCB provider initialized with endpoints: {list(self.endpoints.keys())}"
        )

        # Initialize caches
        loop = asyncio.get_event_loop()
        loop.run_until_complete(api._ensure_caches_initialized())

    async def get_waiting_times(self, stop_id: str) -> Dict[str, Any]:
        """Get waiting times for a stop"""
        return await get_waiting_times(stop_id)


# Only create and register provider if it's enabled and not already registered
if "sncb" in get_config("ENABLED_PROVIDERS", []) and "sncb" not in PROVIDERS:
    try:
        provider = SNCBProvider()
        register_provider("sncb", provider)
        logger.info("SNCB provider registered successfully")
    except Exception as e:
        logger.error(f"Failed to register SNCB provider: {e}")
        import traceback

        logger.error(traceback.format_exc())

__all__ = [
    "sncb_config",
    "get_waiting_times",
    "get_static_data",
    "get_line_info",
]
