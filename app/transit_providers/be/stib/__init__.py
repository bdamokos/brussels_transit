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
import json

logger = logging.getLogger('stib')

provider_config = get_provider_config('stib')
GTFS_DIR = provider_config.get('GTFS_DIR')
STOPS_CACHE_FILE = provider_config.get('STOPS_CACHE_FILE')

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
            'config': self.get_config,
            'data': self.get_data,
            'stops': self.get_stops,
            'stop': self.get_stop_details,  # /api/stib/stop/{id}
            'route': get_route_data,
            'colors': get_route_colors,
            'vehicles': get_vehicle_positions,
            'messages': get_service_messages,
            'waiting_times': get_waiting_times,
            'get_stop_by_name': self.get_stop_by_name,
            'get_nearest_stops': self.get_nearest_stops,
            'search_stops': self.search_stops,
            'static': self.get_static_data,
            'realtime': self.get_realtime_data,
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

    async def get_stops(self, stop_ids: List[str] = None) -> Dict[str, Any]:
        """Get details for multiple stops.
        
        Args:
            stop_ids: List of stop IDs to fetch details for
            
        Returns:
            Dictionary containing stop details in the format:
            {
                "stops": {
                    "stop_id": {
                        "name": "Stop Name",
                        "coordinates": {"lat": float, "lon": float}
                    }
                }
            }
        """
        try:
            if not stop_ids:
                return {"stops": {}}
            
            # Use existing get_stop_names function which already has caching
            from .get_stop_names import get_stop_names
            stops_data = get_stop_names(stop_ids)
            
            # Format response to match v1
            return {
                "stops": {
                    stop_id: {
                        "name": data["name"],
                        "coordinates": data["coordinates"]
                    }
                    for stop_id, data in stops_data.items()
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting stops data: {e}")
            return {"error": str(e)}

    async def get_stop_details(self, stop_id: str):
        """Get details for a specific STIB stop.
        
        Example of a valid stop_id: 8122 (ROODEBEEK)
        """
        try:
            # Get coordinates from cache
            coordinates = None
            try:
                with open(STOPS_CACHE_FILE, 'r') as f:
                    stops_data = json.load(f)
                
                # First try the original stop ID
                if stop_id in stops_data:
                    coordinates = stops_data[stop_id].get('coordinates', None)
                else:
                    # Try with letter suffixes
                    for suffix in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                        modified_id = f"{stop_id}{suffix}"
                        if modified_id in stops_data:
                            coordinates = stops_data[modified_id].get('coordinates', None)
                            break
            except Exception as e:
                logger.error(f"Error reading coordinates from cache: {e}")
            
            # Check if this is a coordinates request by looking at the request path
            from flask import request
            if request.path.endswith('/coordinates'):
                return {'coordinates': coordinates}
            
            # Get waiting times for this stop
            waiting_times = await get_waiting_times(stop_id)
            
            if not waiting_times or stop_id not in waiting_times.get("stops", {}):
                return {
                    "id": stop_id,
                    "name": "Unknown Stop",
                    "coordinates": coordinates,
                    "lines": {}
                }

            stop_data = waiting_times["stops"][stop_id]
            stop_details = {
                "id": stop_id,
                "name": stop_data["name"],
                "coordinates": coordinates,
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

    async def get_stop_coordinates(self, stop_id: str):
        """Get coordinates for a specific stop"""
        try:
            # Use the same cache file as v1
            with open(STOPS_CACHE_FILE, 'r') as f:
                stops_data = json.load(f)
                
            # First try the original stop ID
            if stop_id in stops_data:
                return {'coordinates': stops_data[stop_id].get('coordinates', None)}
                    
            # If not found, try appending letters A-G
            for suffix in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                modified_id = f"{stop_id}{suffix}"
                if modified_id in stops_data:
                    return {'coordinates': stops_data[modified_id].get('coordinates', None)}
                        
            logger.warning(f"Stop {stop_id} not found in cache (including letter suffixes)")
            return {'coordinates': None}
                
        except Exception as e:
            logger.error(f"Error getting coordinates for stop {stop_id}: {e}")
            return {'coordinates': None}

    async def get_static_data(self):
        """Get static data like routes, stops, and colors"""
        try:
            # Get route shapes
            shapes_data = {}
            shape_errors = []
            
            for line in self.monitored_lines:
                try:
                    route_data = await get_route_data(line)
                    if route_data:
                        filtered_variants = []
                        for variant in route_data[line]:
                            is_monitored_direction = False
                            for stop in self.config['STIB_STOPS']:
                                if (line in stop.get('lines', {}) and 
                                    stop.get('direction') == variant['direction']):
                                    is_monitored_direction = True
                                    break
                            
                            if is_monitored_direction:
                                filtered_variants.append(variant)
                        
                        if filtered_variants:
                            shapes_data[line] = filtered_variants
                except Exception as e:
                    shape_errors.append(f"Error fetching route data for line {line}: {e}")

            # Get route colors
            route_colors = await get_route_colors(self.monitored_lines)

            return {
                'display_stops': self.config['STIB_STOPS'],
                'shapes': shapes_data,
                'route_colors': route_colors,
                'errors': shape_errors
            }
            
        except Exception as e:
            logger.error(f"Error fetching static data: {e}")
            return {"error": str(e)}

    async def get_realtime_data(self):
        """Get all real-time data including waiting times, messages, and vehicle positions"""
        try:
            data = await self.get_data()
            return {
                'stops_data': data['stops'],
                'messages': data['messages'],
                'processed_vehicles': data.get('processed_vehicles', []),
                'errors': data.get('errors', [])
            }
        except Exception as e:
            logger.error(f"Error in realtime data endpoint: {e}")
            return {"error": str(e)}
        
def get_stops():
    pass

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
