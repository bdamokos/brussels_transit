"""Handle stop coordinates with GTFS fallback.

This module provides functions to get stop coordinates from the STIB API,
with a fallback to GTFS data if the API returns null coordinates.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
import json
from dataclasses import dataclass
from transit_providers.config import get_provider_config
from transit_providers.nearest_stop import Stop, ingest_gtfs_stops
from .gtfs import ensure_gtfs_data

# Get logger
logger = logging.getLogger('stib.stop_coordinates')

# Get provider configuration
provider_config = get_provider_config('stib')
CACHE_DIR = provider_config.get('CACHE_DIR')
GTFS_DIR = provider_config.get('GTFS_DIR')
STOPS_CACHE_FILE = CACHE_DIR / 'stops_gtfs.json'

@dataclass
class StopCoordinates:
    """Stop coordinates with source information."""
    lat: float
    lon: float
    source: str  # 'api' or 'gtfs'

def get_cached_coordinates() -> Dict[str, StopCoordinates]:
    """Get cached stop coordinates."""
    try:
        if not STOPS_CACHE_FILE.exists():
            return {}
            
        with open(STOPS_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {
                stop_id: StopCoordinates(**coords)
                for stop_id, coords in data.items()
            }
    except Exception as e:
        logger.error(f"Error loading cached coordinates: {e}")
        return {}

def cache_coordinates(coordinates: Dict[str, StopCoordinates]) -> None:
    """Cache stop coordinates to disk."""
    try:
        STOPS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STOPS_CACHE_FILE, 'w', encoding='utf-8') as f:
            data = {
                stop_id: {
                    'lat': coords.lat,
                    'lon': coords.lon,
                    'source': coords.source
                }
                for stop_id, coords in coordinates.items()
            }
            json.dump(data, f, indent=2)
        logger.info(f"Successfully cached {len(coordinates)} stop coordinates")
    except Exception as e:
        logger.error(f"Error caching coordinates: {e}")

def get_coordinates_from_gtfs(stop_id: str) -> Optional[StopCoordinates]:
    """Get stop coordinates from GTFS data."""
    try:
        # Ensure GTFS data is available
        if not ensure_gtfs_data():
            logger.error("Could not ensure GTFS data")
            return None
            
        # Load stops from GTFS
        stops = ingest_gtfs_stops(GTFS_DIR)
        if not stops:
            logger.error("Could not load stops from GTFS")
            return None
            
        # Get stop coordinates
        stop = stops.get(stop_id)
        if not stop:
            logger.warning(f"Stop {stop_id} not found in GTFS data")
            return None
            
        return StopCoordinates(
            lat=stop.lat,
            lon=stop.lon,
            source='gtfs'
        )
        
    except Exception as e:
        logger.error(f"Error getting coordinates from GTFS: {e}")
        return None

def get_stop_coordinates(stop_id: str, api_coordinates: Optional[Tuple[float, float]] = None) -> Optional[Dict[str, float]]:
    """Get stop coordinates with GTFS fallback.
    
    Args:
        stop_id: The stop ID to get coordinates for
        api_coordinates: Optional tuple of (lat, lon) from the API
        
    Returns:
        Dictionary with 'lat' and 'lon' keys, or None if coordinates not found
    """
    # Check cache first
    cached = get_cached_coordinates().get(stop_id)
    if cached:
        logger.debug(f"Using cached coordinates for stop {stop_id} (source: {cached.source})")
        return {'lat': cached.lat, 'lon': cached.lon}
        
    # Try API coordinates first
    coordinates = None
    if api_coordinates and all(c is not None for c in api_coordinates):
        coordinates = StopCoordinates(
            lat=api_coordinates[0],
            lon=api_coordinates[1],
            source='api'
        )
    
    # Fallback to GTFS if API coordinates are null
    if not coordinates:
        logger.debug(f"API coordinates not available for stop {stop_id}, trying GTFS")
        coordinates = get_coordinates_from_gtfs(stop_id)
        
    if coordinates:
        # Cache the coordinates
        cache = get_cached_coordinates()
        cache[stop_id] = coordinates
        cache_coordinates(cache)
        
        return {'lat': coordinates.lat, 'lon': coordinates.lon}
        
    logger.warning(f"Could not find coordinates for stop {stop_id} in API or GTFS")
    return None 