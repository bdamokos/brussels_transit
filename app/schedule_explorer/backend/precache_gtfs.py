#!/usr/bin/env python3
"""
Pre-calculate GTFS cache with CPU usage limits.
This script is designed to run standalone without any dependencies on the transit provider modules.
"""

import psutil
import time
import logging
import argparse
from pathlib import Path
from typing import Optional, Callable
import msgpack
from dataclasses import asdict
import re
import os
from .gtfs_loader import load_feed, bytes_to_mb

logger = logging.getLogger("schedule_explorer.precache_gtfs")

# Regular expression to match provider-id format (e.g., "abc-1234")
PROVIDER_ID_PATTERN = re.compile(r"^[a-zA-Z]+-\d+$")

def get_gtfs_dir(provider_id: str, downloads_dir: str = "downloads") -> Optional[Path]:
    """
    Get the GTFS directory for a specific provider.
    
    Args:
        provider_id: The provider ID (e.g., 'mdb-1859')
        downloads_dir: Base directory for downloads (default: 'downloads')
        
    Returns:
        Path to the GTFS directory or None if not found
    """
    if not PROVIDER_ID_PATTERN.match(provider_id):
        return None
        
    # Convert downloads_dir to Path
    downloads_path = Path(downloads_dir)
    
    # Look for a directory matching the pattern: {downloads_dir}/{provider_id}_*/{provider_id}-*/
    try:
        # First find the provider directory (e.g., mdb-1859_Societe_nationale...)
        provider_dirs = list(downloads_path.glob(f"{provider_id}_*"))
        if not provider_dirs:
            return None
            
        # Sort by modification time to get the most recent one
        provider_dir = sorted(provider_dirs, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        
        # Then find the GTFS directory inside it (e.g., mdb-1859-202501020029)
        gtfs_dirs = list(provider_dir.glob(f"{provider_id}-*"))
        if not gtfs_dirs:
            return None
            
        # Sort by modification time to get the most recent one
        return sorted(gtfs_dirs, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        
    except Exception as e:
        logger.error(f"Error finding GTFS directory for {provider_id}: {e}")
        return None

def create_cpu_limiter(max_cpu_percent: float = 85.0, check_interval: float = 1.0) -> Callable:
    """
    Create a CPU limiter function that can be passed to other functions.
    
    Args:
        max_cpu_percent: Maximum CPU usage percentage (0-100)
        check_interval: How often to check CPU usage (seconds)
        
    Returns:
        A function that checks CPU usage and sleeps if necessary
    """
    def check_cpu_usage():
        """Check CPU usage and sleep if necessary"""
        while True:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            if cpu_percent > max_cpu_percent:
                logger.info(f"CPU usage {cpu_percent}% > {max_cpu_percent}%, sleeping...")
                time.sleep(check_interval)
            else:
                break
    return check_cpu_usage

def precache_gtfs(data_dir: str | Path, max_cpu_percent: float = 85.0, check_interval: float = 1.0) -> None:
    """
    Pre-calculate GTFS cache with CPU usage limits.
    
    Args:
        data_dir: Path to the GTFS data directory or a provider ID (e.g., 'mdb-1859')
        max_cpu_percent: Maximum CPU usage percentage (0-100)
        check_interval: How often to check CPU usage (seconds)
    """
    logger.info(f"Starting GTFS pre-cache for directory/provider: {data_dir}")
    logger.info(f"CPU limit: {max_cpu_percent}%")
    
    start_time = time.time()
    
    # Create CPU limiter function
    check_cpu_usage = create_cpu_limiter(max_cpu_percent, check_interval)
    
    # Check if data_dir is a provider ID
    if isinstance(data_dir, str) and PROVIDER_ID_PATTERN.match(data_dir):
        provider_dir = get_gtfs_dir(data_dir)
        if provider_dir is None:
            raise ValueError(f"Could not find GTFS directory for provider {data_dir}")
        data_path = provider_dir
        logger.info(f"Using GTFS directory for provider {data_dir}: {data_path}")
    else:
        # Convert data_dir to Path if it's a string
        data_path = Path(data_dir)
    
    if not data_path.exists():
        raise ValueError(f"Data directory does not exist: {data_path}")
    
    # Load the feed with CPU checks
    logger.info("Loading GTFS feed...")
    feed = load_feed(data_path, cpu_check_fn=check_cpu_usage)
    check_cpu_usage()
    
    # Serialize the feed
    logger.info("Serializing feed data...")
    t0 = time.time()
    
    # Create a custom dictionary without _feed references
    data = {
        "stops": {stop_id: asdict(stop) for stop_id, stop in feed.stops.items()},
        "routes": [],
        "calendars": {cal_id: asdict(cal) for cal_id, cal in feed.calendars.items()},
        "calendar_dates": [asdict(cal_date) for cal_date in feed.calendar_dates],
        "trips": {trip_id: asdict(trip) for trip_id, trip in feed.trips.items()},
        "stop_times_dict": feed.stop_times_dict,
        "agencies": {agency_id: asdict(agency) for agency_id, agency in feed.agencies.items()},
    }
    check_cpu_usage()
    
    # Handle routes separately to avoid _feed recursion
    for route in feed.routes:
        route_dict = {
            "route_id": route.route_id,
            "route_name": route.route_name,
            "trip_id": route.trip_id,
            "service_days": route.service_days,
            "stops": [
                {
                    "stop": asdict(rs.stop),
                    "arrival_time": rs.arrival_time,
                    "departure_time": rs.departure_time,
                    "stop_sequence": rs.stop_sequence,
                }
                for rs in route.stops
            ],
            "shape": asdict(route.shape) if route.shape else None,
            "short_name": route.short_name,
            "long_name": route.long_name,
            "route_type": route.route_type,
            "color": route.color,
            "text_color": route.text_color,
            "agency_id": route.agency_id,
            "headsigns": route.headsigns,
            "service_ids": route.service_ids,
            "direction_id": route.direction_id,
            "route_desc": route.route_desc,
            "route_url": route.route_url,
            "route_sort_order": route.route_sort_order,
            "continuous_pickup": route.continuous_pickup,
            "continuous_drop_off": route.continuous_drop_off,
            "trip_ids": [trip.id for trip in route.trips],
            "service_days_explicit": route.service_days_explicit,
            "calendar_dates_additions": [d.isoformat() for d in route.calendar_dates_additions],
            "calendar_dates_removals": [d.isoformat() for d in route.calendar_dates_removals],
            "valid_calendar_days": [d.isoformat() for d in route.valid_calendar_days],
            "service_calendar": route.service_calendar,
        }
        data["routes"].append(route_dict)
        check_cpu_usage()
    
    # Convert datetime objects to ISO format strings
    if "calendars" in data:
        for calendar in data["calendars"].values():
            calendar["start_date"] = calendar["start_date"].isoformat()
            calendar["end_date"] = calendar["end_date"].isoformat()
    check_cpu_usage()
    
    if "calendar_dates" in data:
        for cal_date in data["calendar_dates"]:
            cal_date["date"] = cal_date["date"].isoformat()
    check_cpu_usage()
    
    # Pack with msgpack
    logger.info("Packing data with msgpack...")
    t0 = time.time()
    packed_data = msgpack.packb(data, use_bin_type=True)
    logger.info(f"Packed data size: {bytes_to_mb(len(packed_data))} MB in {time.time() - t0:.2f}s")
    check_cpu_usage()
    
    # Save to cache file
    cache_file = data_path / ".gtfs_cache"
    logger.info(f"Saving to cache file: {cache_file}")
    with open(cache_file, "wb") as f:
        f.write(packed_data)
    
    total_time = time.time() - start_time
    logger.info(f"Pre-cache completed in {total_time:.2f} seconds")

def main():
    """Main entry point for the script"""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Pre-calculate GTFS cache with CPU limits")
    parser.add_argument(
        "data_dir", 
        help="Path to GTFS data directory or provider ID (e.g., 'mdb-1859')"
    )
    parser.add_argument(
        "--max-cpu",
        type=float,
        default=85.0,
        help="Maximum CPU usage percentage (default: 85.0)"
    )
    parser.add_argument(
        "--check-interval",
        type=float,
        default=1.0,
        help="How often to check CPU usage in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--downloads-dir",
        type=str,
        default="downloads",
        help="Base directory for downloads when using provider ID (default: 'downloads')"
    )
    
    args = parser.parse_args()
    
    try:
        # If it's a provider ID, use the downloads directory from args
        if PROVIDER_ID_PATTERN.match(args.data_dir):
            data_dir = get_gtfs_dir(args.data_dir, args.downloads_dir)
            if data_dir is None:
                logger.error(f"Could not find GTFS directory for provider {args.data_dir}")
                exit(1)
        else:
            data_dir = args.data_dir
            
        precache_gtfs(data_dir, args.max_cpu, args.check_interval)
    except Exception as e:
        logger.error(f"Error during pre-cache: {e}", exc_info=True)
        exit(1)

if __name__ == "__main__":
    main() 