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

def test_original_implementation(data_dir: Path, start_id: str, end_id: str) -> Dict[str, Any]:
    """Test the original GTFS loader implementation."""
    metrics = {}
    
    # Measure initial memory
    metrics['initial_memory'] = measure_memory()
    
    # Measure load time
    start_time = time.time()
    feed = gtfs_loader.load_feed(data_dir)
    load_time = time.time() - start_time
    metrics['load_time'] = load_time
    
    # Measure memory after loading
    metrics['after_load_memory'] = measure_memory()
    
    # Measure route search time
    start_time = time.time()
    routes = feed.find_routes_between_stations(start_id, end_id)
    search_time = time.time() - start_time
    metrics['search_time'] = search_time
    
    # Record results
    metrics['num_routes_found'] = len(routes)
    metrics['final_memory'] = measure_memory()
    
    return metrics

def test_parquet_implementation(data_dir: Path, start_id: str, end_id: str) -> Dict[str, Any]:
    """Test the new Parquet-based GTFS loader implementation."""
    metrics = {}
    
    # Measure initial memory
    metrics['initial_memory'] = measure_memory()
    
    # Initialize loader and measure conversion time
    start_time = time.time()
    loader = gtfs_parquet.ParquetGTFSLoader(data_dir)
    loader.load_feed()
    load_time = time.time() - start_time
    metrics['load_time'] = load_time
    
    # Measure memory after loading
    metrics['after_load_memory'] = measure_memory()
    
    # Measure route search time
    start_time = time.time()
    routes = loader.find_routes_between_stations(start_id, end_id)
    search_time = time.time() - start_time
    metrics['search_time'] = search_time
    
    # Record results
    metrics['num_routes_found'] = len(routes)
    metrics['final_memory'] = measure_memory()
    
    # Clean up
    loader.close()
    
    return metrics

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

def run_comparison(data_dir: Path, test_original: bool = True) -> None:
    """Run performance comparison between original and Parquet implementations."""
    logger.info("Starting performance comparison")
    logger.info(f"Data directory: {data_dir}")
    
    # Test original implementation first
    original_feed = None
    if test_original:
        t0 = time.time()
        translations = gtfs_loader.load_translations(data_dir)
        original_time = time.time() - t0
        original_num_translations = sum(len(trans) for trans in translations.values())
        original_num_records = len(translations)
        logger.info(f"\n=== Translation Loading Comparison ===")
        logger.info(f"Original: {{'time': {original_time}, 'num_translations': {original_num_translations}, 'num_records': {original_num_records}}}")
        
        # Load original feed
        t0 = time.time()
        original_feed = gtfs_loader.load_feed(data_dir)
        original_load_time = time.time() - t0
        logger.info(f"Original implementation load time: {original_load_time:.2f}s")
    
    # Test Parquet implementation
    t0 = time.time()
    parquet_translations = gtfs_parquet.load_translations(data_dir)
    parquet_time = time.time() - t0
    parquet_num_translations = sum(len(trans) for trans in parquet_translations.values())
    parquet_num_records = len(parquet_translations)
    logger.info(f"Parquet: {{'time': {parquet_time}, 'num_translations': {parquet_num_translations}, 'num_records': {parquet_num_records}}}")
    
    # Compare translations
    if test_original and translations == parquet_translations:
        logger.info("No differences found in translations")
    elif test_original:
        logger.warning("Found differences in translations")
        # Add detailed comparison if needed
    
    # Test Parquet implementation for full feed loading
    logger.info("\n=== Testing Parquet Implementation ===")
    t0 = time.time()
    parquet_loader = gtfs_parquet.ParquetGTFSLoader(data_dir)
    parquet_loader.load_feed()
    load_time = time.time() - t0
    
    # Test route search
    t0 = time.time()
    routes = parquet_loader.find_routes_between_stations("8814001", "8833001")
    search_time = time.time() - t0
    
    # Get memory usage
    process = psutil.Process()
    peak_memory = process.memory_info().rss / (1024 * 1024)  # Convert to MB
    
    logger.info("Parquet implementation results:")
    logger.info(f"Load time: {load_time:.2f}s")
    logger.info(f"Search time: {search_time:.2f}s")
    logger.info(f"Peak memory: {peak_memory:.2f}MB")
    logger.info(f"Routes found: {len(routes)}")
    
    # Compare stops if original implementation was tested
    if test_original and original_feed:
        compare_stops(original_feed.stops, parquet_loader.stops)
    
    parquet_loader.close()

if __name__ == "__main__":
    # Get data directory from environment or use default
    data_dir = Path(os.getenv("GTFS_DATA_DIR", "/Users/bence/Developer/STIB/downloads/mdb-1859_Societe_nationale_des_chemins_de_fer_belges_NMBS_SNCB/mdb-1859-202501020029"))
    
    # Test both implementations by default
    run_comparison(data_dir, test_original=True) 