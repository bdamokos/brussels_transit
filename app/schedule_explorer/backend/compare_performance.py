#!/usr/bin/env python3
"""
Compare performance between the original GTFS loader and the new Parquet-based loader.
"""

import logging
import time
import psutil
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from .gtfs_loader import load_feed as load_feed_original
from .gtfs_parquet import ParquetGTFSLoader

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
    feed = load_feed_original(data_dir)
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
    loader = ParquetGTFSLoader(data_dir)
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

def run_comparison(data_dir: Path, start_id: str, end_id: str, test_original: bool = False) -> Dict[str, Any]:
    """Run performance comparison between both implementations."""
    logger.info("Starting performance comparison")
    logger.info(f"Data directory: {data_dir}")
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'data_dir': str(data_dir),
        'translations': compare_translations(data_dir),
        'test_route': {
            'start_id': start_id,
            'end_id': end_id
        }
    }
    
    # Log translation comparison results
    if results['translations']['original'] and results['translations']['parquet']:
        logger.info("\n=== Translation Loading Comparison ===")
        logger.info(f"Original: {results['translations']['original']}")
        logger.info(f"Parquet: {results['translations']['parquet']}")
        if results['translations']['differences']:
            logger.warning(f"Found differences: {results['translations']['differences']}")
        else:
            logger.info("No differences found in translations")
    
    # Test Parquet implementation first
    logger.info("\n=== Testing Parquet Implementation ===")
    try:
        results['parquet'] = test_parquet_implementation(data_dir, start_id, end_id)
        logger.info("Parquet implementation results:")
        logger.info(f"Load time: {results['parquet']['load_time']:.2f}s")
        logger.info(f"Search time: {results['parquet']['search_time']:.2f}s")
        logger.info(f"Peak memory: {results['parquet']['after_load_memory']['rss']:.2f}MB")
        logger.info(f"Routes found: {results['parquet']['num_routes_found']}")
    except Exception as e:
        logger.error(f"Error testing Parquet implementation: {e}")
        results['parquet'] = {'error': str(e)}
    
    # Optionally test original implementation
    if test_original:
        logger.info("\n=== Testing Original Implementation ===")
        try:
            results['original'] = test_original_implementation(data_dir, start_id, end_id)
            logger.info("Original implementation results:")
            logger.info(f"Load time: {results['original']['load_time']:.2f}s")
            logger.info(f"Search time: {results['original']['search_time']:.2f}s")
            logger.info(f"Peak memory: {results['original']['after_load_memory']['rss']:.2f}MB")
            logger.info(f"Routes found: {results['original']['num_routes_found']}")
        except Exception as e:
            logger.error(f"Error testing original implementation: {e}")
            results['original'] = {'error': str(e)}
    
    return results

if __name__ == "__main__":
    # Example usage
    data_dir = Path(__file__).parent.parent.parent.parent / "downloads" / "mdb-1859_Societe_nationale_des_chemins_de_fer_belges_NMBS_SNCB" / "mdb-1859-202501020029"
    start_id = "8811304"  # Brussels-Luxembourg
    end_id = "8811601"    # Ottignies
    
    # Only test Parquet implementation by default
    results = run_comparison(data_dir, start_id, end_id, test_original=False) 