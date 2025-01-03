import cProfile
import pstats
import io
import psutil
import time
import logging
import tracemalloc
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from .gtfs_loader import load_feed, FlixbusFeed

logger = logging.getLogger("schedule_explorer.profiler")

class PerformanceMetrics:
    def __init__(self):
        self.start_time = time.time()
        self.measurements: Dict[str, Any] = {}
        
    def measure_memory(self, label: str):
        process = psutil.Process()
        memory_info = process.memory_info()
        self.measurements[f"{label}_memory_rss"] = memory_info.rss / 1024 / 1024  # MB
        self.measurements[f"{label}_memory_vms"] = memory_info.vms / 1024 / 1024  # MB
        
    def measure_time(self, label: str):
        self.measurements[f"{label}_time"] = time.time() - self.start_time
        
    def log_metrics(self):
        logger.info("Performance Metrics:")
        for key, value in self.measurements.items():
            if isinstance(value, (int, float)):
                if "memory" in key:
                    logger.info(f"{key}: {value:.2f} MB")
                else:
                    logger.info(f"{key}: {value:.2f} seconds")
            else:
                logger.info(f"{key}: {value}")

def profile_feed_loading(data_dir: Path) -> Dict[str, float]:
    """Profile the GTFS feed loading process."""
    metrics = PerformanceMetrics()
    
    # Start memory tracking
    tracemalloc.start()
    
    # Measure initial state
    metrics.measure_memory("initial")
    metrics.measure_time("start")
    
    # Profile the load_feed function
    pr = cProfile.Profile()
    pr.enable()
    
    # Load the feed
    feed = load_feed(data_dir)
    
    pr.disable()
    
    # Measure after loading
    metrics.measure_memory("after_load")
    metrics.measure_time("load_complete")
    
    # Get memory snapshot
    current, peak = tracemalloc.get_traced_memory()
    metrics.measurements["peak_memory"] = peak / 1024 / 1024  # MB
    metrics.measurements["current_memory"] = current / 1024 / 1024  # MB
    
    # Stop memory tracking
    tracemalloc.stop()
    
    # Get detailed stats
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(20)  # Print top 20 functions
    metrics.measurements["profile_stats"] = s.getvalue()
    
    # Analyze feed contents
    metrics.measurements["num_stops"] = len(feed.stops)
    metrics.measurements["num_routes"] = len(feed.routes)
    metrics.measurements["num_trips"] = len(feed.trips)
    metrics.measurements["num_calendar_dates"] = len(feed.calendar_dates)
    
    # Log all metrics
    metrics.log_metrics()
    
    # Log detailed profiling stats
    logger.info("\nDetailed Profile Stats:")
    logger.info(metrics.measurements["profile_stats"])
    
    return metrics.measurements

def profile_route_search(feed: FlixbusFeed, start_id: str, end_id: str) -> Dict[str, float]:
    """Profile route search operations."""
    metrics = PerformanceMetrics()
    
    # Measure initial state
    metrics.measure_memory("initial")
    metrics.measure_time("start")
    
    # Profile the search operation
    pr = cProfile.Profile()
    pr.enable()
    
    routes = feed.find_routes_between_stations(start_id, end_id)
    
    pr.disable()
    
    # Measure after search
    metrics.measure_memory("after_search")
    metrics.measure_time("search_complete")
    
    # Get detailed stats
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(20)
    metrics.measurements["profile_stats"] = s.getvalue()
    
    # Record results
    metrics.measurements["num_routes_found"] = len(routes)
    
    # Log all metrics
    metrics.log_metrics()
    
    # Log detailed profiling stats
    logger.info("\nDetailed Profile Stats:")
    logger.info(metrics.measurements["profile_stats"])
    
    return metrics.measurements

def run_full_profile(data_dir: Path, sample_start_id: str, sample_end_id: str):
    """Run a full profiling session."""
    logger.info("Starting full profiling session")
    logger.info(f"Data directory: {data_dir}")
    
    # Profile feed loading
    logger.info("\n=== Profiling Feed Loading ===")
    load_metrics = profile_feed_loading(data_dir)
    
    # Get the feed again for route search profiling
    feed = load_feed(data_dir)
    
    # Profile route search
    logger.info("\n=== Profiling Route Search ===")
    search_metrics = profile_route_search(feed, sample_start_id, sample_end_id)
    
    # Combine metrics
    all_metrics = {
        "load": load_metrics,
        "search": search_metrics,
        "timestamp": datetime.now().isoformat()
    }
    
    return all_metrics 