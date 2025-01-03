"""
Performance profiling utilities for GTFS data loading and querying.
"""

import logging
import time
import psutil
import tracemalloc
from pathlib import Path
from typing import Dict, Any, Optional
import cProfile
import pstats
import io

logger = logging.getLogger("schedule_explorer.profiler")

class PerformanceMetrics:
    """Collects and logs performance metrics."""
    
    def __init__(self):
        self.start_time = time.time()
        self.metrics = {}
        tracemalloc.start()
        self.process = psutil.Process()
    
    def measure_memory(self) -> Dict[str, float]:
        """Get current memory usage in MB."""
        memory_info = self.process.memory_info()
        current, peak = tracemalloc.get_traced_memory()
        return {
            'rss': memory_info.rss / 1024 / 1024,
            'vms': memory_info.vms / 1024 / 1024,
            'peak': peak / 1024 / 1024,
            'current': current / 1024 / 1024
        }
    
    def log_metrics(self, name: str, value: Any):
        """Log a metric with its value."""
        self.metrics[name] = value
        if isinstance(value, (int, float)):
            logger.info(f"{name}: {value:.2f}")
        else:
            logger.info(f"{name}: {value}")
    
    def profile_function(self, func, *args, **kwargs) -> Any:
        """Profile a function execution."""
        pr = cProfile.Profile()
        result = pr.runcall(func, *args, **kwargs)
        
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
        ps.print_stats(20)  # Top 20 functions
        
        self.log_metrics(f"{func.__name__}_profile", s.getvalue())
        return result

def profile_feed_loading(data_dir: Path) -> Dict[str, Any]:
    """Profile GTFS feed loading process."""
    metrics = PerformanceMetrics()
    
    # Measure initial state
    initial_memory = metrics.measure_memory()
    metrics.log_metrics("initial_memory_mb", initial_memory['rss'])
    
    # Profile feed loading
    from .gtfs_loader import load_feed
    feed = metrics.profile_function(load_feed, data_dir)
    
    # Measure final state
    final_memory = metrics.measure_memory()
    load_time = time.time() - metrics.start_time
    
    # Log results
    metrics.log_metrics("load_time_seconds", load_time)
    metrics.log_metrics("peak_memory_mb", final_memory['peak'])
    metrics.log_metrics("memory_increase_mb", final_memory['rss'] - initial_memory['rss'])
    
    # Log feed statistics
    metrics.log_metrics("num_stops", len(feed.stops))
    metrics.log_metrics("num_routes", len(feed.routes))
    metrics.log_metrics("num_trips", len(feed.trips))
    metrics.log_metrics("num_calendar_dates", len(feed.calendar_dates) if feed.calendar_dates else 0)
    
    return metrics.metrics

def profile_route_search(feed, start_id: str, end_id: str) -> Dict[str, Any]:
    """Profile route search operation."""
    metrics = PerformanceMetrics()
    
    # Measure initial state
    initial_memory = metrics.measure_memory()
    metrics.log_metrics("initial_memory_mb", initial_memory['rss'])
    
    # Profile route search
    routes = metrics.profile_function(feed.find_routes_between_stations, start_id, end_id)
    
    # Measure final state
    final_memory = metrics.measure_memory()
    search_time = time.time() - metrics.start_time
    
    # Log results
    metrics.log_metrics("search_time_seconds", search_time)
    metrics.log_metrics("peak_memory_mb", final_memory['peak'])
    metrics.log_metrics("memory_increase_mb", final_memory['rss'] - initial_memory['rss'])
    metrics.log_metrics("routes_found", len(routes))
    
    return metrics.metrics

def run_full_profile(data_dir: Path, start_id: str, end_id: str) -> Dict[str, Any]:
    """Run complete profiling session."""
    results = {
        'feed_loading': profile_feed_loading(data_dir),
        'route_search': None
    }
    
    # Only profile route search if feed loading succeeded
    if 'feed' in results['feed_loading']:
        results['route_search'] = profile_route_search(
            results['feed_loading']['feed'],
            start_id,
            end_id
        )
    
    return results 