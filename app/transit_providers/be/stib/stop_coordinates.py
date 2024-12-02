"""Handle stop coordinates with GTFS fallback.

This module provides functions to get stop coordinates from the STIB API,
with a fallback to GTFS data if the API returns null coordinates.

Stop ID Suffix Behavior:
-----------------------
STIB stop IDs can have letter suffixes (e.g., 5710F, 5710G) which indicate different
physical stops that are logically part of the same stop group. Different STIB APIs
handle these suffixes differently:

- Some APIs require the full stop ID with suffix (e.g., waiting times API)
- Some APIs work only with the base stop ID without suffix
- Some APIs accept both formats

This module handles both formats by:
1. First trying the exact stop ID as provided
2. If not found and the ID has no suffix, trying common suffixes (F, G)
3. If not found and the ID has a suffix, trying the base ID without suffix

When a different stop ID format is used than what was provided, a warning is
included in the response metadata to help clients adapt their behavior.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any
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

# Common stop ID suffixes used by STIB
STOP_SUFFIXES = ['A', 'B', 'C', 'D', 'E', 'F', 'G']

@dataclass
class StopCoordinates:
    """Stop coordinates with source information."""
    lat: float
    lon: float
    source: str  # 'api', 'gtfs', or 'derived'
    original_id: Optional[str] = None  # If coordinates come from a different stop ID

def normalize_stop_id(stop_id: str) -> str:
    """Remove any suffix (letters) from a stop ID.
    
    Args:
        stop_id: The stop ID to normalize (e.g., "5710F")
        
    Returns:
        The normalized stop ID (e.g., "5710")
    """
    return ''.join(c for c in stop_id if c.isdigit())

def get_stop_id_variants(stop_id: str) -> List[str]:
    """Get all possible variants of a stop ID.
    
    Args:
        stop_id: The stop ID to get variants for
        
    Returns:
        List of stop ID variants to try, in order of preference
    """
    base_id = normalize_stop_id(stop_id)
    
    # If the original ID has a suffix, try:
    # 1. Original ID (e.g., 5710F)
    # 2. Base ID (e.g., 5710)
    if base_id != stop_id:
        return [stop_id, base_id]
    
    # If the original ID has no suffix, try:
    # 1. Original ID (e.g., 5710)
    # 2. ID with suffixes (e.g., 5710F, 5710G)
    return [stop_id] + [f"{base_id}{suffix}" for suffix in STOP_SUFFIXES]

def get_cached_coordinates() -> Dict[str, StopCoordinates]:
    """Get cached stop coordinates."""
    try:
        if not STOPS_CACHE_FILE.exists():
            return {}
            
        with open(STOPS_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if data:
                return {
                    stop_id: StopCoordinates(**coords)
                    for stop_id, coords in data.items()
                }
            else:
                logger.warning(f"Stops cache file {STOPS_CACHE_FILE} is empty")
                return {}
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
            
        # Try all stop ID variants
        for variant_id in get_stop_id_variants(stop_id):
            # Load stops from GTFS
            stops = ingest_gtfs_stops(GTFS_DIR)
            if not stops:
                logger.error("Could not load stops from GTFS")
                import os
                logger.debug(f"Current directory: {os.getcwd()}")
                logger.debug(f"GTFS directory: {GTFS_DIR}")
                if os.path.exists(GTFS_DIR):
                    logger.debug(f"GTFS directory contents: {os.listdir(GTFS_DIR)}")
                else:
                    logger.debug("GTFS directory does not exist")
                return None
            
            # Get stop coordinates
            stop = stops.get(variant_id)
            if stop:
                coords = StopCoordinates(
                    lat=stop.lat,
                    lon=stop.lon,
                    source='gtfs',
                    original_id=variant_id if variant_id != stop_id else None
                )
                logger.debug(f"Found coordinates in GTFS for stop variant {variant_id}")
                return coords
        
        logger.warning(f"Stop {stop_id} and variants not found in GTFS data")
        return None
            
    except Exception as e:
        logger.error(f"Error getting coordinates from GTFS: {e}")
        return None

def get_stop_coordinates(stop_id: str, api_coordinates: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    """Get stop coordinates with cache-first, GTFS-second, API-last approach.
    
    Args:
        stop_id: The stop ID to get coordinates for
        api_coordinates: Optional tuple of (lat, lon) from the API
        
    Returns:
        Dictionary with:
        - coordinates: Dict with 'lat' and 'lon' keys, or None if not found
        - metadata: Dict with additional information:
            - source: Where the coordinates came from ('cache', 'gtfs', 'api')
            - original_id: If coordinates came from a different stop ID variant
            - warning: Any warnings about stop ID format
    """
    result = {
        'coordinates': None,
        'metadata': {
            'source': None,
            'original_id': None,
            'warning': None
        }
    }
    
    # Try all stop ID variants
    for variant_id in get_stop_id_variants(stop_id):
        # 1. Check cache first
        cached = get_cached_coordinates().get(variant_id)
        if cached:
            logger.debug(f"Using cached coordinates for stop variant {variant_id} (source: {cached.source})")
            result['coordinates'] = {'lat': cached.lat, 'lon': cached.lon}
            result['metadata'].update({
                'source': f'cache_{cached.source}',
                'original_id': cached.original_id or variant_id if variant_id != stop_id else None
            })
            break
    
        # 2. Try GTFS data
        gtfs_coordinates = get_coordinates_from_gtfs(variant_id)
        if gtfs_coordinates:
            logger.debug(f"Found coordinates in GTFS for stop variant {variant_id}")
            result['coordinates'] = {'lat': gtfs_coordinates.lat, 'lon': gtfs_coordinates.lon}
            result['metadata'].update({
                'source': 'gtfs',
                'original_id': gtfs_coordinates.original_id or variant_id if variant_id != stop_id else None
            })
            # Cache the coordinates
            cache = get_cached_coordinates()
            cache[variant_id] = gtfs_coordinates
            cache_coordinates(cache)
            break
    
    # 3. Finally, try API coordinates
    if not result['coordinates'] and api_coordinates and all(c is not None for c in api_coordinates):
        logger.debug(f"Using API coordinates for stop {stop_id}")
        coordinates = StopCoordinates(
            lat=api_coordinates[0],
            lon=api_coordinates[1],
            source='api'
        )
        result['coordinates'] = {'lat': coordinates.lat, 'lon': coordinates.lon}
        result['metadata']['source'] = 'api'
        # Cache the coordinates
        cache = get_cached_coordinates()
        cache[stop_id] = coordinates
        cache_coordinates(cache)
    
    # Add warning if we used a different stop ID
    if result['metadata']['original_id']:
        result['metadata']['warning'] = (
            f"Stop ID format changed: coordinates taken from stop {result['metadata']['original_id']} "
            f"instead of {stop_id}"
        )
    
    if not result['coordinates']:
        logger.warning(f"Could not find coordinates for stop {stop_id} or variants in cache, GTFS, or API")
    
    return result