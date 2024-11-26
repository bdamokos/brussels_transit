"""De Lijn transit provider"""

# First import the config to ensure defaults are registered
from . import config

from dataclasses import dataclass
from typing import Dict, Any, Callable, Awaitable, List
from transit_providers.config import get_provider_config
from config import get_config
import logging
from logging.config import dictConfig
from transit_providers.nearest_stop import get_stop_by_name as generic_get_stop_by_name, get_cached_stops
from dataclasses import asdict
from pathlib import Path
from transit_providers import get_provider_docs
# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('delijn')

from .api import (
    get_formatted_arrivals,
    get_line_shape,
    get_line_color,
    get_vehicle_positions,
    get_service_messages,
    get_nearest_stop,
    find_nearest_stops,
    get_stop_by_name,
)

provider_config = get_provider_config('delijn')
GTFS_DIR = provider_config.get('GTFS_DIR')
CACHE_DIR = provider_config.get('CACHE_DIR')

@dataclass
class DelijnProvider:
    name: str = "De Lijn"
    endpoints: Dict[str, Callable[..., Awaitable[Any]]] = None
    monitored_lines: list = None
    stop_ids: list = None
    cache_dir: Path = CACHE_DIR

    def __post_init__(self):
        # Get merged configuration
        config = get_provider_config('delijn')
        self.monitored_lines = config['MONITORED_LINES']
        self.stop_ids = config['STOP_IDS'] if isinstance(config['STOP_IDS'], list) else [config['STOP_IDS']]
        
        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Define all endpoints
        self.endpoints = {
            'config': self.get_config,
            'data': self.get_data,
            'stops': self.get_stop_details,
            'route': get_line_shape,
            'colors': get_line_color,
            'vehicles': get_vehicle_positions,
            'messages': get_service_messages,
            'waiting_times': get_formatted_arrivals,
            'nearest_stop': get_nearest_stop,
            'get_stop_by_name': self.get_stop_by_name,
        }
        logger.info(f"De Lijn provider initialized with endpoints: {list(self.endpoints.keys())}")

    async def get_config(self):
        """Get De Lijn configuration including monitored stops and lines"""
        stops_config = []
        for stop_id in self.stop_ids:
            stop_data = await get_formatted_arrivals([stop_id])
            stop_info = {
                "id": stop_id,
                "name": stop_data.get('stops', {}).get(stop_id, {}).get('name', 'Unknown Stop'),
                "coordinates": stop_data.get('stops', {}).get(stop_id, {}).get('coordinates', {
                    "lat": 50.85,
                    "lon": 4.38
                }),
                "lines": {line: [] for line in self.monitored_lines}  # Empty list means all destinations
            }
            stops_config.append(stop_info)

        return {
            "stops": stops_config,
            "monitored_lines": self.monitored_lines
        }

    async def get_data(self):
        """Get all real-time data for monitored De Lijn stops/lines"""
        data = await get_formatted_arrivals(self.stop_ids)
        if not data:
            return {
                "stops": {
                    stop_id: {
                        "name": "Unknown Stop",
                        "coordinates": {
                            "lat": 50.85,
                            "lon": 4.38
                        },
                        "lines": {}
                    } for stop_id in self.stop_ids
                }
            }
        return data

    async def get_stop_details(self, stop_id: str):
        """Get details for a specific De Lijn stop"""
        arrivals = await get_formatted_arrivals([stop_id])
        
        if not arrivals or stop_id not in arrivals.get("stops", {}):
            return {
                "id": stop_id,
                "name": "Unknown Stop",
                "coordinates": {
                    "lat": 50.85,
                    "lon": 4.38
                },
                "lines": {}
            }

        stop_data = arrivals["stops"][stop_id]
        stop_details = {
            "id": stop_id,
            "name": stop_data["name"],
            "coordinates": stop_data["coordinates"],
            "lines": {}
        }

        # Extract unique lines and their destinations
        for line, destinations in stop_data.get("lines", {}).items():
            stop_details["lines"][line] = list(destinations.keys())

        return stop_details

    async def get_nearest_stops(self, lat: float, lon: float, limit: int = 5, max_distance: float = 2.0):
        """
        Get nearest De Lijn stops to the given coordinates.
        
        Args:
            lat: Latitude
            lon: Longitude
            limit: Maximum number of stops to return
            max_distance: Maximum distance in kilometers to consider
            
        Returns:
            List of dictionaries containing stop information and distance
        """
        return await find_nearest_stops(lat, lon, limit, max_distance)

    async def get_stop_by_name(self, name: str, limit: int = 5) -> List[Dict]:
        """Search for stops by name using the generic function."""
        try:
            # Get cached stops
            stops = get_cached_stops(self.cache_dir / 'stops.json')
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

# Only create and register provider if it's enabled
if 'delijn' in get_config('ENABLED_PROVIDERS', []):
    provider = DelijnProvider()
    from transit_providers import register_provider
    register_provider('delijn', provider.endpoints)
