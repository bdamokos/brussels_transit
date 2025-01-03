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
    
    # Get a sample trip ID that exists in both feeds
    sample_trip = next(iter(original_feed.trips.keys()))
    
    # Get route stops for this trip from both implementations
    original_route = next((r for r in original_feed.routes if r.trip_id == sample_trip), None)
    parquet_route = next((r for r in parquet_feed.routes if r.trip_id == sample_trip), None)
    
    if not original_route or not parquet_route:
        logger.error(f"Could not find matching route for trip {sample_trip}")
        return
    
    # Compare number of stops
    logger.info(f"Original: {len(original_route.stops)} stops")
    logger.info(f"Parquet: {len(parquet_route.stops)} stops")
    
    if len(original_route.stops) != len(parquet_route.stops):
        logger.error("Different number of stops!")
        return
    
    # Compare each stop in sequence
    differences = []
    for i, (orig_stop, parq_stop) in enumerate(zip(original_route.stops, parquet_route.stops)):
        # Compare stop IDs
        if orig_stop.stop.id != parq_stop.stop.id:
            differences.append(f"Stop {i}: ID mismatch - Original: {orig_stop.stop.id}, Parquet: {parq_stop.stop.id}")
            continue
            
        # Compare times
        if orig_stop.arrival_time != parq_stop.arrival_time:
            differences.append(f"Stop {i} ({orig_stop.stop.id}): Arrival time mismatch - Original: {orig_stop.arrival_time}, Parquet: {parq_stop.arrival_time}")
        
        if orig_stop.departure_time != parq_stop.departure_time:
            differences.append(f"Stop {i} ({orig_stop.stop.id}): Departure time mismatch - Original: {orig_stop.departure_time}, Parquet: {parq_stop.departure_time}")
        
        # Compare sequence
        if orig_stop.stop_sequence != parq_stop.stop_sequence:
            differences.append(f"Stop {i} ({orig_stop.stop.id}): Sequence mismatch - Original: {orig_stop.stop_sequence}, Parquet: {parq_stop.stop_sequence}")
    
    if differences:
        logger.error("Found differences in route stops:")
        for diff in differences:
            logger.error(diff)
    else:
        logger.info("All route stops match exactly")

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
    logger.info("Comparing implementations...")
    compare_stops(original_feed.stops, parquet_feed.stops)
    compare_route_stops(original_feed, parquet_feed)

if __name__ == "__main__":
    # Get data directory from environment or use default
    data_dir = Path(os.getenv("GTFS_DATA_DIR", "/Users/bence/Developer/STIB/downloads/mdb-1859_Societe_nationale_des_chemins_de_fer_belges_NMBS_SNCB/mdb-1859-202501020029"))
    
    # Test both implementations by default
    run_comparison(data_dir, test_original=True) 