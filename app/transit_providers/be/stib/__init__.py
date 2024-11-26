"""STIB transit provider"""

# First import the config to ensure defaults are registered
from . import config

from dataclasses import dataclass
from typing import Dict, Any, Callable, Awaitable
from transit_providers.config import get_provider_config
from config import get_config

from .api import (
    get_waiting_times,
    get_vehicle_positions,
    get_service_messages,
    get_route_colors,
    get_route_data
)

@dataclass
class STIBProvider:
    name: str = "STIB"
    endpoints: Dict[str, Callable[..., Awaitable[Any]]] = None
    monitored_lines: set = None
    stop_ids: set = None

    def __post_init__(self):
        # Get merged configuration
        self.config = get_provider_config('stib')
        
        # Initialize monitored lines and stops from STIB_STOPS config
        self.monitored_lines = set()
        self.stop_ids = set()
        
        stib_stops = self.config.get('STIB_STOPS', [])
        for stop in stib_stops:
            if 'lines' in stop:
                self.monitored_lines.update(stop['lines'].keys())
            self.stop_ids.add(stop['id'])

        # Define all endpoints
        self.endpoints = {
            'config': self.get_config,
            'data': self.get_data,
            'stops': self.get_stop_details,
            'route': get_route_data,
            'colors': get_route_colors,
            'vehicles': get_vehicle_positions,
            'messages': get_service_messages,
            'waiting_times': get_waiting_times,
        }

    async def get_config(self):
        """Get STIB configuration including monitored stops and lines"""
        return {
            "stops": self.config.get('STIB_STOPS', []),
            "monitored_lines": list(self.monitored_lines),
            "stop_ids": list(self.stop_ids)
        }

    async def get_data(self):
        """Get all real-time data for monitored STIB stops/lines"""
        try:
            # Get waiting times for all monitored stops
            waiting_times = await get_waiting_times()
            
            # Get service messages
            messages = await get_service_messages(
                monitored_lines=self.monitored_lines,
                monitored_stops=self.stop_ids
            )
            
            # Get vehicle positions
            vehicles = await get_vehicle_positions()
            
            # Get route colors
            colors = await get_route_colors(self.monitored_lines)
            
            return {
                "stops": waiting_times.get('stops', {}),
                "messages": messages.get('messages', []),
                "vehicles": vehicles,
                "colors": colors
            }
        except Exception as e:
            import logging
            logger = logging.getLogger('stib')
            logger.error(f"Error getting STIB data: {e}")
            return {
                "stops": {},
                "messages": [],
                "vehicles": {},
                "colors": {},
                "error": str(e)
            }

    async def get_stop_details(self, stop_id: str):
        """Get details for a specific STIB stop"""
        try:
            # Get waiting times for this stop
            waiting_times = await get_waiting_times(stop_id)
            
            if not waiting_times or stop_id not in waiting_times.get("stops", {}):
                return {
                    "id": stop_id,
                    "name": "Unknown Stop",
                    "coordinates": None,
                    "lines": {}
                }

            stop_data = waiting_times["stops"][stop_id]
            stop_details = {
                "id": stop_id,
                "name": stop_data["name"],
                "coordinates": stop_data.get("coordinates"),
                "lines": {}
            }

            # Extract unique lines and their destinations
            for line, destinations in stop_data.get("lines", {}).items():
                stop_details["lines"][line] = list(destinations.keys())

            return stop_details
            
        except Exception as e:
            import logging
            logger = logging.getLogger('stib')
            logger.error(f"Error getting STIB stop details: {e}")
            return {
                "id": stop_id,
                "name": "Unknown Stop",
                "coordinates": None,
                "lines": {},
                "error": str(e)
            }

# Only create and register provider if it's enabled
if 'stib' in get_config('ENABLED_PROVIDERS', []):
    provider = STIBProvider()
    from transit_providers import register_provider
    register_provider('stib', provider.endpoints)
