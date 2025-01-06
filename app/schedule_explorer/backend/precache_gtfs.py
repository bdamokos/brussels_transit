import psutil
import time
import logging
import argparse
from pathlib import Path
from typing import Optional
import msgpack
from dataclasses import asdict
from .gtfs_loader import load_feed, bytes_to_mb

logger = logging.getLogger("schedule_explorer.precache_gtfs")

def precache_gtfs(data_dir: str | Path, max_cpu_percent: float = 85.0, check_interval: float = 1.0) -> None:
    """
    Pre-calculate GTFS cache with CPU usage limits.
    
    Args:
        data_dir: Path to the GTFS data directory
        max_cpu_percent: Maximum CPU usage percentage (0-100)
        check_interval: How often to check CPU usage (seconds)
    """
    logger.info(f"Starting GTFS pre-cache for directory: {data_dir}")
    logger.info(f"CPU limit: {max_cpu_percent}%")
    
    start_time = time.time()
    
    # Convert data_dir to Path if it's a string
    data_path = Path(data_dir)
    
    if not data_path.exists():
        raise ValueError(f"Data directory does not exist: {data_path}")
    
    def check_cpu_usage():
        """Check CPU usage and sleep if necessary"""
        while True:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            if cpu_percent > max_cpu_percent:
                logger.info(f"CPU usage {cpu_percent}% > {max_cpu_percent}%, sleeping...")
                time.sleep(check_interval)
            else:
                break
    
    # Load the feed with CPU checks
    logger.info("Loading GTFS feed...")
    feed = load_feed(data_path)
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

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Pre-calculate GTFS cache with CPU limits")
    parser.add_argument("data_dir", help="Path to GTFS data directory")
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
    
    args = parser.parse_args()
    
    try:
        precache_gtfs(args.data_dir, args.max_cpu, args.check_interval)
    except Exception as e:
        logger.error(f"Error during pre-cache: {e}", exc_info=True)
        exit(1) 