''' Generic function to get the nearest stop to a given point from GTFS stops.txt.

Each provider module can rely on this function to analyze the nearest stop to a given point.

'''

import csv
import math
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import logging
from logging.config import dictConfig
from config import get_config

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
dictConfig(logging_config)

logger = logging.getLogger('transit_providers.nearest_stop')

@dataclass
class Stop:
    id: str
    name: str
    lat: float
    lon: float
    location_type: Optional[str] = None
    parent_station: Optional[str] = None

def ingest_gtfs_stops(gtfs_stops_path: str) -> Dict[str, Stop]:
    """Ingest GTFS stops.txt into a dictionary of Stop objects."""
    stops = {}
    stops_path = Path(gtfs_stops_path) / 'stops.txt'
    
    try:
        with open(stops_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip parent stations (location_type = 1)
                if row.get('location_type') == '1':
                    continue
                    
                try:
                    stop = Stop(
                        id=row['stop_id'],
                        name=row['stop_name'],
                        lat=float(row['stop_lat']),
                        lon=float(row['stop_lon']),
                        location_type=row.get('location_type'),
                        parent_station=row.get('parent_station')
                    )
                    stops[stop.id] = stop
                except (ValueError, KeyError) as e:
                    logger.error(f"Error processing stop {row.get('stop_id')}: {e}")
                    continue
                    
        logger.info(f"Successfully loaded {len(stops)} stops from GTFS data")
        return stops
        
    except Exception as e:
        logger.error(f"Error reading stops.txt: {e}")
        return {}

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points using Haversine formula."""
    R = 6371  # Earth's radius in km

    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c

def get_nearest_stops(stops: Dict[str, Stop], point: Tuple[float, float], limit: int = 5, max_distance: float = 2.0) -> List[Dict]:
    """
    Get the nearest stops to a given point from a dictionary of stops.
    
    Args:
        stops: Dictionary of Stop objects
        point: Tuple of (latitude, longitude)
        limit: Maximum number of stops to return
        max_distance: Maximum distance in kilometers to consider
        
    Returns:
        List of dictionaries containing stop information and distance
    """
    lat, lon = point
    stops_with_distances = []
    
    for stop in stops.values():
        distance = calculate_distance(lat, lon, stop.lat, stop.lon)
        if distance <= max_distance:
            stops_with_distances.append({
                **asdict(stop),
                'distance': round(distance, 3)
            })
    
    # Sort by distance and return the nearest stops
    stops_with_distances.sort(key=lambda x: x['distance'])
    return stops_with_distances[:limit]

def cache_stops(stops: Dict[str, Stop], cache_path: Path) -> None:
    """Cache the stops on disk."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            # Convert Stop objects to dictionaries
            stops_dict = {k: asdict(v) for k, v in stops.items()}
            json.dump(stops_dict, f, indent=2)
        logger.info(f"Successfully cached {len(stops)} stops to {cache_path}")
    except Exception as e:
        logger.error(f"Error caching stops: {e}")

def get_cached_stops(cache_path: Path) -> Optional[Dict[str, Stop]]:
    """Get the cached stops from disk."""
    try:
        if not cache_path.exists():
            return None
            
        with open(cache_path, 'r', encoding='utf-8') as f:
            stops_dict = json.load(f)
            # Convert dictionaries back to Stop objects
            stops = {k: Stop(**v) for k, v in stops_dict.items()}
            logger.info(f"Successfully loaded {len(stops)} stops from cache")
            return stops
    except Exception as e:
        logger.error(f"Error loading cached stops: {e}")
        return None
