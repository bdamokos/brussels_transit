"""STIB transit provider"""

# First import the config to ensure defaults are registered
from . import config

from dataclasses import dataclass
from typing import Dict, Any, Callable, Awaitable, List
from transit_providers.config import get_provider_config
from config import get_config
import logging
from transit_providers import TransitProvider
from .gtfs import ensure_gtfs_data

from .api import (
    get_waiting_times,
    get_vehicle_positions,
    get_service_messages,
    get_route_colors,
    get_route_data,
    find_nearest_stops,
    get_stop_by_name
)

from transit_providers.nearest_stop import get_stop_by_name as generic_get_stop_by_name, ingest_gtfs_stops
from dataclasses import asdict

logger = logging.getLogger('stib')

provider_config = get_provider_config('stib')
GTFS_DIR = provider_config.get('GTFS_DIR')

class StibProvider(TransitProvider):
    """STIB/MIVB transit provider"""
    
    def __init__(self):
        self.name = "stib"
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
            'config': self.get_config, # Working
            'data': self.get_data, # Working
            'stops': self.get_stop_details, # Working
            'route': get_route_data, # ??
            'colors': get_route_colors, # Working
            'vehicles': get_vehicle_positions, # Not working yet
            'messages': get_service_messages, # Not working yet
            'waiting_times': get_waiting_times, # Not working yet
             
            'get_stop_by_name': self.get_stop_by_name,
            'get_nearest_stops': self.get_nearest_stops,
            'search_stops': self.search_stops,
        }
        logger.info(f"STIB provider initialized with endpoints: {list(self.endpoints.keys())}")

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
            logger.error(f"Error getting STIB data: {e}")
            return {
                "stops": {},
                "messages": [],
                "vehicles": {},
                "colors": {},
                "error": str(e)
            }

    async def get_stop_details(self, stop_id: str):
        """Get details for a specific STIB stop.
        
        Example of a valid stop_id: 8122 (ROODEBEEK)
        """
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
            logger.error(f"Error getting STIB stop details: {e}")
            return {
                "id": stop_id,
                "name": "Unknown Stop",
                "coordinates": None,
                "lines": {},
                "error": str(e)
            }

    async def get_nearest_stops(self, lat: float, lon: float, limit: int = 5, max_distance: float = 2.0):
        """Get nearest STIB stops to coordinates."""
        return await find_nearest_stops(lat, lon, limit, max_distance)
        
    async def search_stops(self, query: str, limit: int = 5):
        """Search for STIB stops by name."""
        return get_stop_by_name(query, limit)

    async def get_stop_by_name(self, name: str, limit: int = 5) -> List[Dict]:
        """Search for stops by name using the generic function."""
        try:
            # Get all stops
            stops = ingest_gtfs_stops(GTFS_DIR)
            if not stops:
                logger.error("No stops data available")
                return []
            
            # Use the generic function
            matching_stops = generic_get_stop_by_name(stops, name, limit)
            
            # Convert Stop objects to dictionaries
            return [asdict(stop) for stop in matching_stops] if matching_stops else []
            
        except Exception as e:
            logger.error(f"Error in get_stop_by_name: {e}")
            return []

# Create provider instance and register if enabled
if 'stib' in get_config('ENABLED_PROVIDERS', []):
    try:
        provider = StibProvider()
        from transit_providers import register_provider
        register_provider('stib', provider)  # Register the provider instance
        logger.info("STIB provider registered successfully")
    except Exception as e:
        logger.error(f"Failed to register STIB provider: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
else:
    logger.warning("STIB provider is not enabled in configuration")