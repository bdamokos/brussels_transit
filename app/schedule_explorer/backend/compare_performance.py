#!/usr/bin/env python3
"""
Compare performance between the original GTFS loader and the new Parquet-based loader.
"""

import logging
import time
import psutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from . import gtfs_loader
from . import gtfs_parquet
from .gtfs_loader import Stop
import os
from app.schedule_explorer.backend.gtfs_loader import RouteStop
from app.schedule_explorer.backend import gtfs_loader, gtfs_parquet
from app.schedule_explorer.backend.gtfs_loader import FlixbusFeed

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("schedule_explorer.compare_performance")

def measure_memory() -> Dict[str, float]:
    """Get current memory usage."""
    process = psutil.Process()
    memory_info = process.memory_info()
    return {
        'rss': memory_info.rss / 1024 / 1024,  # MB
        'vms': memory_info.vms / 1024 / 1024   # MB
    }

def test_original_implementation(data_dir: str) -> Optional[FlixbusFeed]:
    """Test the original implementation."""
    logger = logging.getLogger(__name__)
    
    try:
        # Load feed
        start_time = time.time()
        feed = gtfs_loader.load_feed(data_dir)
        end_time = time.time()
        
        if not feed:
            logger.error("Failed to load original feed")
            return None
        
        logger.info(f"Original load time: {end_time - start_time:.4f} seconds")
        return feed
    except Exception as e:
        logger.error(f"Error testing original implementation: {e}")
        return None

def test_parquet_implementation(data_dir: str) -> Optional[FlixbusFeed]:
    """Test the Parquet implementation."""
    logger = logging.getLogger(__name__)
    
    try:
        # Initialize loader
        loader = gtfs_parquet.ParquetGTFSLoader(data_dir)
        
        # Load feed
        start_time = time.time()
        feed = loader.load_feed()
        end_time = time.time()
        
        if not feed:
            logger.error("Failed to load Parquet feed")
            return None
        
        logger.info(f"Parquet load time: {end_time - start_time:.4f} seconds")
        return feed
    except Exception as e:
        logger.error(f"Error testing Parquet implementation: {e}")
        return None

def compare_translations(data_dir: Path) -> Dict[str, Any]:
    """Compare translation loading between implementations."""
    results = {
        'original': None,
        'parquet': None,
        'differences': None
    }
    
    # Test original implementation
    try:
        from .gtfs_loader import load_translations as load_translations_original
        start_time = time.time()
        orig_translations = load_translations_original(data_dir)
        results['original'] = {
            'time': time.time() - start_time,
            'num_translations': sum(len(v) for v in orig_translations.values()),
            'num_records': len(orig_translations)
        }
    except Exception as e:
        logger.error(f"Error testing original translation loading: {e}")
        results['original'] = {'error': str(e)}
    
    # Test Parquet implementation
    try:
        from .gtfs_parquet import load_translations as load_translations_parquet
        start_time = time.time()
        parquet_translations = load_translations_parquet(data_dir)
        results['parquet'] = {
            'time': time.time() - start_time,
            'num_translations': sum(len(v) for v in parquet_translations.values()),
            'num_records': len(parquet_translations)
        }
        
        # Compare results
        if results['original'] and 'error' not in results['original']:
            differences = []
            for record_id in set(orig_translations.keys()) | set(parquet_translations.keys()):
                if record_id not in orig_translations:
                    differences.append(f"Record {record_id} missing from original")
                elif record_id not in parquet_translations:
                    differences.append(f"Record {record_id} missing from parquet")
                else:
                    orig_langs = set(orig_translations[record_id].keys())
                    parq_langs = set(parquet_translations[record_id].keys())
                    if orig_langs != parq_langs:
                        differences.append(f"Languages differ for record {record_id}")
                    else:
                        for lang in orig_langs:
                            if orig_translations[record_id][lang] != parquet_translations[record_id][lang]:
                                differences.append(f"Translation differs for record {record_id}, language {lang}")
            
            results['differences'] = differences if differences else None
            
    except Exception as e:
        logger.error(f"Error testing Parquet translation loading: {e}")
        results['parquet'] = {'error': str(e)}
    
    return results

def compare_stops(original_stops: Dict[str, Stop], parquet_stops: Dict[str, Stop]) -> None:
    """Compare stops between original and Parquet implementations."""
    logger.info("\n=== Stop Loading Comparison ===")
    
    # Compare number of stops
    logger.info(f"Original: {len(original_stops)} stops")
    logger.info(f"Parquet: {len(parquet_stops)} stops")
    
    # Compare stop IDs
    original_ids = set(original_stops.keys())
    parquet_ids = set(parquet_stops.keys())
    
    missing_in_parquet = original_ids - parquet_ids
    missing_in_original = parquet_ids - original_ids
    
    if missing_in_parquet:
        logger.warning(f"Stops missing in Parquet: {missing_in_parquet}")
    if missing_in_original:
        logger.warning(f"Extra stops in Parquet: {missing_in_original}")
        
    # Compare stop attributes for common stops
    common_ids = original_ids & parquet_ids
    differences = []
    
    for stop_id in common_ids:
        orig_stop = original_stops[stop_id]
        parq_stop = parquet_stops[stop_id]
        
        # Compare each attribute
        if orig_stop.name != parq_stop.name:
            differences.append(f"Stop {stop_id}: Name mismatch - Original: {orig_stop.name}, Parquet: {parq_stop.name}")
        if abs(orig_stop.lat - parq_stop.lat) > 1e-6:
            differences.append(f"Stop {stop_id}: Latitude mismatch - Original: {orig_stop.lat}, Parquet: {parq_stop.lat}")
        if abs(orig_stop.lon - parq_stop.lon) > 1e-6:
            differences.append(f"Stop {stop_id}: Longitude mismatch - Original: {orig_stop.lon}, Parquet: {parq_stop.lon}")
        if orig_stop.translations != parq_stop.translations:
            differences.append(f"Stop {stop_id}: Translation mismatch - Original: {orig_stop.translations}, Parquet: {parq_stop.translations}")
        if orig_stop.location_type != parq_stop.location_type:
            differences.append(f"Stop {stop_id}: Location type mismatch - Original: {orig_stop.location_type}, Parquet: {parq_stop.location_type}")
        if orig_stop.parent_station != parq_stop.parent_station:
            differences.append(f"Stop {stop_id}: Parent station mismatch - Original: {orig_stop.parent_station}, Parquet: {parq_stop.parent_station}")
        if orig_stop.platform_code != parq_stop.platform_code:
            differences.append(f"Stop {stop_id}: Platform code mismatch - Original: {orig_stop.platform_code}, Parquet: {parq_stop.platform_code}")
        if orig_stop.timezone != parq_stop.timezone:
            differences.append(f"Stop {stop_id}: Timezone mismatch - Original: {orig_stop.timezone}, Parquet: {parq_stop.timezone}")
    
    if differences:
        logger.warning("Found differences in stops:")
        for diff in differences:
            logger.warning(diff)
    else:
        logger.info("No differences found in stops")

def compare_route_stops(original_feed: FlixbusFeed, parquet_feed: FlixbusFeed) -> None:
    """Compare route stops between original and Parquet implementations."""
    logger.info("\n=== Route Stop Comparison ===")
    
    # Compare total number of routes
    logger.info(f"Original: {len(original_feed.routes)} routes")
    logger.info(f"Parquet: {len(parquet_feed.routes)} routes")
    
    # Create maps of route_id -> list of routes (for variants)
    original_routes = {}
    for route in original_feed.routes:
        if route.route_id not in original_routes:
            original_routes[route.route_id] = []
        original_routes[route.route_id].append(route)
    
    parquet_routes = {}
    for route in parquet_feed.routes:
        if route.route_id not in parquet_routes:
            parquet_routes[route.route_id] = []
        parquet_routes[route.route_id].append(route)
    
    # Compare route IDs
    original_route_ids = set(original_routes.keys())
    parquet_route_ids = set(parquet_routes.keys())
    
    missing_in_parquet = original_route_ids - parquet_route_ids
    missing_in_original = parquet_route_ids - original_route_ids
    
    if missing_in_parquet:
        logger.warning(f"Routes missing in Parquet: {missing_in_parquet}")
    if missing_in_original:
        logger.warning(f"Extra routes in Parquet: {missing_in_original}")
    
    # Compare common routes
    common_route_ids = original_route_ids & parquet_route_ids
    logger.info(f"Comparing {len(common_route_ids)} common routes...")
    
    for route_id in common_route_ids:
        orig_variants = original_routes[route_id]
        parq_variants = parquet_routes[route_id]
        
        logger.info(f"\nRoute {route_id}:")
        logger.info(f"Original variants: {len(orig_variants)}")
        logger.info(f"Parquet variants: {len(parq_variants)}")
        
        # Compare each variant
        for orig_route in orig_variants:
            # Find matching variant in parquet routes
            matching_variant = None
            for parq_route in parq_variants:
                if (orig_route.direction_id == parq_route.direction_id and 
                    orig_route.trip_id == parq_route.trip_id):
                    matching_variant = parq_route
                    break
            
            if not matching_variant:
                logger.warning(f"No matching variant found for route {route_id} direction {orig_route.direction_id} trip {orig_route.trip_id}")
                continue
            
            # Compare stops
            if len(orig_route.stops) != len(matching_variant.stops):
                logger.error(f"Different number of stops for route {route_id} direction {orig_route.direction_id}:")
                logger.error(f"Original: {len(orig_route.stops)} stops")
                logger.error(f"Parquet: {len(matching_variant.stops)} stops")
                continue
            
            # Compare each stop
            stop_differences = []
            for i, (orig_stop, parq_stop) in enumerate(zip(orig_route.stops, matching_variant.stops)):
                if orig_stop.stop.id != parq_stop.stop.id:
                    stop_differences.append(f"Stop {i}: ID mismatch - Original: {orig_stop.stop.id}, Parquet: {parq_stop.stop.id}")
                elif orig_stop.arrival_time != parq_stop.arrival_time:
                    stop_differences.append(f"Stop {i} ({orig_stop.stop.id}): Arrival time mismatch - Original: {orig_stop.arrival_time}, Parquet: {parq_stop.arrival_time}")
                elif orig_stop.departure_time != parq_stop.departure_time:
                    stop_differences.append(f"Stop {i} ({orig_stop.stop.id}): Departure time mismatch - Original: {orig_stop.departure_time}, Parquet: {parq_stop.departure_time}")
                elif orig_stop.stop_sequence != parq_stop.stop_sequence:
                    stop_differences.append(f"Stop {i} ({orig_stop.stop.id}): Sequence mismatch - Original: {orig_stop.stop_sequence}, Parquet: {parq_stop.stop_sequence}")
            
            if stop_differences:
                logger.error(f"Found differences in route {route_id} direction {orig_route.direction_id}:")
                for diff in stop_differences:
                    logger.error(diff)
            
            # Compare service days
            if set(orig_route.service_days) != set(matching_variant.service_days):
                logger.error(f"Service days mismatch for route {route_id} direction {orig_route.direction_id}:")
                logger.error(f"Original: {orig_route.service_days}")
                logger.error(f"Parquet: {matching_variant.service_days}")
            
            # Compare service IDs
            if set(orig_route.service_ids) != set(matching_variant.service_ids):
                logger.error(f"Service IDs mismatch for route {route_id} direction {orig_route.direction_id}:")
                logger.error(f"Original: {orig_route.service_ids}")
                logger.error(f"Parquet: {matching_variant.service_ids}")
            
            # Compare trips
            if len(orig_route.trips) != len(matching_variant.trips):
                logger.error(f"Different number of trips for route {route_id} direction {orig_route.direction_id}:")
                logger.error(f"Original: {len(orig_route.trips)} trips")
                logger.error(f"Parquet: {len(matching_variant.trips)} trips")
            else:
                orig_trip_ids = {t.id for t in orig_route.trips}
                parq_trip_ids = {t.id for t in matching_variant.trips}
                if orig_trip_ids != parq_trip_ids:
                    logger.error(f"Trip ID mismatch for route {route_id} direction {orig_route.direction_id}:")
                    logger.error(f"Missing in Parquet: {orig_trip_ids - parq_trip_ids}")
                    logger.error(f"Extra in Parquet: {parq_trip_ids - orig_trip_ids}")

def run_comparison(data_dir: str, test_original: bool = True):
    """Run a performance comparison between the original and Parquet implementations."""
    logger = logging.getLogger(__name__)
    
    # Test Parquet implementation first
    logger.info("Testing Parquet implementation...")
    parquet_feed = test_parquet_implementation(data_dir)
    if not parquet_feed:
        logger.error("Parquet implementation test failed")
        return
    
    if not test_original:
        logger.info("Skipping original implementation test")
        return
    
    # Test original implementation
    logger.info("Testing original implementation...")
    original_feed = test_original_implementation(data_dir)
    if not original_feed:
        logger.error("Original implementation test failed")
        return
    
    # Compare results
    logger.info("Testing route stops...")
    
    # Get a route from each implementation
    original_route = original_feed.routes[0] if isinstance(original_feed.routes, list) else next(iter(original_feed.routes.values()))
    parquet_route = parquet_feed.routes[0]
    
    # Log route details
    logger.info(f"\nOriginal route details:")
    logger.info(f"  Route ID: {original_route.route_id}")
    logger.info(f"  Route name: {original_route.route_name}")
    logger.info(f"  Trip ID: {original_route.trip_id}")
    logger.info(f"  Direction ID: {original_route.direction_id}")
    logger.info(f"  Number of stops: {len(original_route.stops)}")
    logger.info(f"  Has shape: {original_route.shape is not None}")
    
    logger.info(f"\nParquet route details:")
    logger.info(f"  Route ID: {parquet_route.route_id}")
    logger.info(f"  Route name: {parquet_route.route_name}")
    logger.info(f"  Trip ID: {parquet_route.trip_id}")
    logger.info(f"  Direction ID: {parquet_route.direction_id}")
    logger.info(f"  Number of stops: {len(parquet_route.stops)}")
    logger.info(f"  Has shape: {parquet_route.shape is not None}")
    
    # Compare route stops
    original_stops = original_route.stops
    parquet_stops = parquet_route.stops
    
    if len(original_stops) != len(parquet_stops):
        logger.error(f"Route stop count mismatch - Original: {len(original_stops)}, Parquet: {len(parquet_stops)}")
        
        # Log stop details
        logger.info("\nOriginal stops:")
        for i, stop in enumerate(original_stops):
            logger.info(f"  {i}: {stop.stop.id} - {stop.stop.name} (seq: {stop.stop_sequence})")
        
        logger.info("\nParquet stops:")
        for i, stop in enumerate(parquet_stops):
            logger.info(f"  {i}: {stop.stop.id} - {stop.stop.name} (seq: {stop.stop_sequence})")
        
        return
    
    for i, (original_stop, parquet_stop) in enumerate(zip(original_stops, parquet_stops)):
        if original_stop.stop.id != parquet_stop.stop.id:
            logger.error(f"Stop {i} ID mismatch - Original: {original_stop.stop.id}, Parquet: {parquet_stop.stop.id}")
            return
        
        if original_stop.arrival_time != parquet_stop.arrival_time:
            logger.error(f"Stop {i} arrival time mismatch - Original: {original_stop.arrival_time}, Parquet: {parquet_stop.arrival_time}")
            return
        
        if original_stop.departure_time != parquet_stop.departure_time:
            logger.error(f"Stop {i} departure time mismatch - Original: {original_stop.departure_time}, Parquet: {parquet_stop.departure_time}")
            return
        
        if original_stop.stop_sequence != parquet_stop.stop_sequence:
            logger.error(f"Stop {i} sequence mismatch - Original: {original_stop.stop_sequence}, Parquet: {parquet_stop.stop_sequence}")
            return
    
    logger.info("Route stops match")

    # Compare shapes
    logger.info("Testing shapes...")
    if original_route.shape is None and parquet_route.shape is None:
        logger.info("Both implementations have no shapes")
    elif original_route.shape is None:
        logger.error("Original implementation has no shape but Parquet implementation does")
        return
    elif parquet_route.shape is None:
        logger.error("Parquet implementation has no shape but Original implementation does")
        return
    else:
        if original_route.shape.shape_id != parquet_route.shape.shape_id:
            logger.error(f"Shape ID mismatch - Original: {original_route.shape.shape_id}, Parquet: {parquet_route.shape.shape_id}")
            return
        
        if len(original_route.shape.points) != len(parquet_route.shape.points):
            logger.error(f"Shape point count mismatch - Original: {len(original_route.shape.points)}, Parquet: {len(parquet_route.shape.points)}")
            return
        
        for i, (original_point, parquet_point) in enumerate(zip(original_route.shape.points, parquet_route.shape.points)):
            if len(original_point) != 2 or len(parquet_point) != 2:
                logger.error(f"Shape point format mismatch at index {i}")
                return
            
            # Compare lat/lon with small tolerance for floating point differences
            if abs(original_point[0] - parquet_point[0]) > 1e-6 or abs(original_point[1] - parquet_point[1]) > 1e-6:
                logger.error(f"Shape point mismatch at index {i} - Original: {original_point}, Parquet: {parquet_point}")
                return
        
        logger.info("Shapes match")

if __name__ == "__main__":
    # Get data directory from environment or use default
    data_dir = Path(os.getenv("GTFS_DATA_DIR", "downloads/mdb-990_Budapesti_Kozlekedesi_Kozpont_BKK/mdb-990-202412300019"))
    
    # Test both implementations by default
    run_comparison(data_dir, test_original=True) 