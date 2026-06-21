"""Le TEC transit provider."""

from . import config  # noqa: F401

import logging
from pathlib import Path
from typing import Any, Dict, List

from config import get_config
from transit_providers import PROVIDERS, TransitProvider, register_provider
from transit_providers.config import canonical_provider_name, get_provider_config

from .api import (
    CACHE_DIR,
    find_nearest_stops,
    get_line_info,
    get_service_alerts,
    get_static_data,
    get_stop_by_name,
    get_waiting_times,
    letec_config,
)

logger = logging.getLogger("letec")


class LeTECProvider(TransitProvider):
    """Le TEC transit provider."""

    def __init__(self):
        provider_config = get_provider_config("letec")
        self.stop_ids = provider_config.get("STOP_IDS", [])
        self.monitored_lines = provider_config.get("MONITORED_LINES", [])
        self.cache_dir = Path(CACHE_DIR)
        endpoints = {
            "config": self.get_config,
            "data": self.get_data,
            "waiting_times": get_waiting_times,
            "static_data": get_static_data,
            "line_info": get_line_info,
            "service_alerts": get_service_alerts,
            "messages": get_service_alerts,
            "get_nearest_stops": self.get_nearest_stops,
            "get_stop_by_name": self.get_stop_by_name,
        }
        super().__init__(name="Le TEC", endpoints=endpoints)

    async def get_config(self) -> Dict[str, Any]:
        return await letec_config()

    async def get_data(self) -> Dict[str, Any]:
        return await get_waiting_times(self.stop_ids)

    async def get_nearest_stops(
        self, lat: float, lon: float, limit: int = 5, max_distance: float = 2.0
    ) -> List[Dict[str, Any]]:
        return await find_nearest_stops(lat, lon, limit, max_distance)

    async def get_stop_by_name(self, name: str, limit: int = 5) -> List[Dict[str, Any]]:
        return await get_stop_by_name(name, limit)


enabled_providers = {
    canonical_provider_name(provider)
    for provider in get_config("ENABLED_PROVIDERS", [])
}

if "letec" in enabled_providers and "letec" not in PROVIDERS:
    try:
        register_provider("letec", LeTECProvider())
        logger.info("Le TEC provider registered successfully")
    except Exception as exc:
        logger.error("Failed to register Le TEC provider: %s", exc, exc_info=True)


__all__ = [
    "LeTECProvider",
    "get_waiting_times",
    "get_static_data",
    "get_line_info",
    "get_service_alerts",
]
