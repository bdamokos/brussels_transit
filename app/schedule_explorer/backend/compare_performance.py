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

def compare_stop_times(original_feed: FlixbusFeed, parquet_feed: FlixbusFeed) -> None:
    """Compare stop times between original and Parquet implementations."""
    logger.info("\n=== Stop Times Comparison ===")
    
    # Get all trips from both feeds
    original_trips = {}
    parquet_trips = {}
    
    # Original feed
    for route in original_feed.routes:
        for trip in route.trips:
            original_trips[trip.id] = trip
            
    # Parquet feed
    for route in parquet_feed.routes:
        for trip in route.trips:
            parquet_trips[trip.id] = trip
    
    # Compare total number of trips
    logger.info(f"Original feed: {len(original_trips)} total trips")
    logger.info(f"Parquet feed: {len(parquet_trips)} total trips")
    
    # Compare total number of trips with stop times
    original_trips_with_times = sum(1 for trip in original_trips.values() if trip.stop_times)
    parquet_trips_with_times = sum(1 for trip in parquet_trips.values() if trip.stop_times)
    
    logger.info(f"Original: {original_trips_with_times} trips with stop times")
    logger.info(f"Parquet: {parquet_trips_with_times} trips with stop times")
    
    # Compare stop times for each trip
    common_trip_ids = set(original_trips.keys()) & set(parquet_trips.keys())
    logger.info(f"Found {len(common_trip_ids)} common trips")
    
    # Log some sample trip IDs
    sample_trips = list(common_trip_ids)[:5]
    logger.info("Sample trip IDs:")
    for trip_id in sample_trips:
        logger.info(f"  {trip_id}")
    
    # Compare stop times for each trip
    differences = 0
    for trip_id in common_trip_ids:
        orig_trip = original_trips[trip_id]
        parquet_trip = parquet_trips[trip_id]
        
        stop_times_differences = []
        # Compare number of stop times
        if len(orig_trip.stop_times) != len(parquet_trip.stop_times):
            differences += 1
            stop_times_differences.append(f"Trip {trip_id} has different number of stop times\n  Original: {len(orig_trip.stop_times)}\n  Parquet: {len(parquet_trip.stop_times)}")
            continue
            
        # Compare each stop time
        for i, (orig_stop, parquet_stop) in enumerate(zip(orig_trip.stop_times, parquet_trip.stop_times)):
            if (orig_stop.arrival_time != parquet_stop.arrival_time or
                orig_stop.departure_time != parquet_stop.departure_time or
                orig_stop.stop_id != parquet_stop.stop_id or
                orig_stop.stop_sequence != parquet_stop.stop_sequence):
                differences += 1
                logger.error(f"Trip {trip_id} has different stop times at index {i}:")
                logger.error(f"  Original: {orig_stop}")
                logger.error(f"  Parquet: {parquet_stop}")
                break
                
    if differences == 0:
        logger.info("No differences found in stop times")
    else:
        logger.error(f"Found {differences} trips with differences in stop times")
        for diff in stop_times_differences[:10]:
            logger.error(diff)

def compare_trips(original_feed: FlixbusFeed, parquet_feed: FlixbusFeed) -> None:
    """Compare trips between original and Parquet implementations."""
    logger.info("\n=== Trip Loading Comparison ===")
    
    # Compare total number of trips
    logger.info(f"Original: {len(original_feed.trips)} trips")
    logger.info(f"Parquet: {len(parquet_feed.trips)} trips")
    
    # Compare trip IDs
    original_ids = set(original_feed.trips.keys())
    parquet_ids = set(parquet_feed.trips.keys())
    
    missing_in_parquet = original_ids - parquet_ids
    missing_in_original = parquet_ids - original_ids
    
    if missing_in_parquet:
        logger.warning(f"Trips missing in Parquet: {missing_in_parquet}")
    if missing_in_original:
        logger.warning(f"Extra trips in Parquet: {missing_in_original}")
        
    # Compare trip attributes for common trips
    common_ids = original_ids & parquet_ids
    differences = []
    
    for trip_id in common_ids:
        orig_trip = original_feed.trips[trip_id]
        parq_trip = parquet_feed.trips[trip_id]
        
        # Compare each attribute
        if orig_trip.route_id != parq_trip.route_id:
            differences.append(f"Trip {trip_id}: Route ID mismatch - Original: {orig_trip.route_id}, Parquet: {parq_trip.route_id}")
        if orig_trip.service_id != parq_trip.service_id:
            differences.append(f"Trip {trip_id}: Service ID mismatch - Original: {orig_trip.service_id}, Parquet: {parq_trip.service_id}")
        if orig_trip.headsign != parq_trip.headsign:
            differences.append(f"Trip {trip_id}: Headsign mismatch - Original: {orig_trip.headsign}, Parquet: {parq_trip.headsign}")
        if orig_trip.direction_id != parq_trip.direction_id:
            differences.append(f"Trip {trip_id}: Direction ID mismatch - Original: {orig_trip.direction_id}, Parquet: {parq_trip.direction_id}")
        if orig_trip.block_id != parq_trip.block_id:
            differences.append(f"Trip {trip_id}: Block ID mismatch - Original: {orig_trip.block_id}, Parquet: {parq_trip.block_id}")
        if orig_trip.shape_id != parq_trip.shape_id:
            differences.append(f"Trip {trip_id}: Shape ID mismatch - Original: {orig_trip.shape_id}, Parquet: {parq_trip.shape_id}")
        
        # Compare stop times
        if len(orig_trip.stop_times) != len(parq_trip.stop_times):
            differences.append(f"Trip {trip_id}: Different number of stop times - Original: {len(orig_trip.stop_times)}, Parquet: {len(parq_trip.stop_times)}")
        else:
            for i, (orig_st, parq_st) in enumerate(zip(orig_trip.stop_times, parq_trip.stop_times)):
                if orig_st.stop_id != parq_st.stop_id:
                    differences.append(f"Trip {trip_id}, Stop {i}: Stop ID mismatch - Original: {orig_st.stop_id}, Parquet: {parq_st.stop_id}")
                if orig_st.arrival_time != parq_st.arrival_time:
                    differences.append(f"Trip {trip_id}, Stop {i}: Arrival time mismatch - Original: {orig_st.arrival_time}, Parquet: {parq_st.arrival_time}")
                if orig_st.departure_time != parq_st.departure_time:
                    differences.append(f"Trip {trip_id}, Stop {i}: Departure time mismatch - Original: {orig_st.departure_time}, Parquet: {parq_st.departure_time}")
                if orig_st.stop_sequence != parq_st.stop_sequence:
                    differences.append(f"Trip {trip_id}, Stop {i}: Stop sequence mismatch - Original: {orig_st.stop_sequence}, Parquet: {parq_st.stop_sequence}")
    
    if differences:
        logger.warning("Found differences in trips. Printing first 10 differences:")
        for diff in differences[:10]:
            logger.warning(diff)
    else:
        logger.info("No differences found in trips")

def compare_calendars(original_feed: FlixbusFeed, parquet_feed: FlixbusFeed) -> None:
    """Compare calendar data between original and Parquet implementations."""
    logger.info("\n=== Calendar Loading Comparison ===")
    
    # Compare regular calendars
    logger.info("Comparing regular calendars...")
    original_calendars = original_feed.calendars
    parquet_calendars = parquet_feed.calendars
    
    # Compare number of calendars
    logger.info(f"Original: {len(original_calendars)} calendars")
    logger.info(f"Parquet: {len(parquet_calendars)} calendars")
    
    # Compare service IDs
    original_service_ids = set(original_calendars.keys())
    parquet_service_ids = set(parquet_calendars.keys())
    
    missing_in_parquet = original_service_ids - parquet_service_ids
    missing_in_original = parquet_service_ids - original_service_ids
    
    if missing_in_parquet:
        logger.warning(f"Services missing in Parquet: {missing_in_parquet}")
    if missing_in_original:
        logger.warning(f"Extra services in Parquet: {missing_in_original}")
    
    # Compare calendar attributes for common services
    common_ids = original_service_ids & parquet_service_ids
    differences = []
    
    for service_id in common_ids:
        orig_cal = original_calendars[service_id]
        parq_cal = parquet_calendars[service_id]
        
        # Compare each attribute
        if orig_cal.monday != parq_cal.monday:
            differences.append(f"Service {service_id}: Monday mismatch - Original: {orig_cal.monday}, Parquet: {parq_cal.monday}")
        if orig_cal.tuesday != parq_cal.tuesday:
            differences.append(f"Service {service_id}: Tuesday mismatch - Original: {orig_cal.tuesday}, Parquet: {parq_cal.tuesday}")
        if orig_cal.wednesday != parq_cal.wednesday:
            differences.append(f"Service {service_id}: Wednesday mismatch - Original: {orig_cal.wednesday}, Parquet: {parq_cal.wednesday}")
        if orig_cal.thursday != parq_cal.thursday:
            differences.append(f"Service {service_id}: Thursday mismatch - Original: {orig_cal.thursday}, Parquet: {parq_cal.thursday}")
        if orig_cal.friday != parq_cal.friday:
            differences.append(f"Service {service_id}: Friday mismatch - Original: {orig_cal.friday}, Parquet: {parq_cal.friday}")
        if orig_cal.saturday != parq_cal.saturday:
            differences.append(f"Service {service_id}: Saturday mismatch - Original: {orig_cal.saturday}, Parquet: {parq_cal.saturday}")
        if orig_cal.sunday != parq_cal.sunday:
            differences.append(f"Service {service_id}: Sunday mismatch - Original: {orig_cal.sunday}, Parquet: {parq_cal.sunday}")
        if orig_cal.start_date != parq_cal.start_date:
            differences.append(f"Service {service_id}: Start date mismatch - Original: {orig_cal.start_date}, Parquet: {parq_cal.start_date}")
        if orig_cal.end_date != parq_cal.end_date:
            differences.append(f"Service {service_id}: End date mismatch - Original: {orig_cal.end_date}, Parquet: {parq_cal.end_date}")
    
    if differences:
        logger.warning("Found differences in calendars:")
        for diff in differences:
            logger.warning(diff)
    else:
        logger.info("No differences found in regular calendars")
    
    # Compare calendar dates (exceptions)
    logger.info("\nComparing calendar dates (exceptions)...")
    original_dates = original_feed.calendar_dates
    parquet_dates = parquet_feed.calendar_dates
    
    logger.info(f"Original: {len(original_dates)} exceptions")
    logger.info(f"Parquet: {len(parquet_dates)} exceptions")
    
    # Create sets of (service_id, date, exception_type) tuples for comparison
    original_date_set = {(cd.service_id, cd.date.date(), cd.exception_type) for cd in original_dates}
    parquet_date_set = {(cd.service_id, cd.date.date(), cd.exception_type) for cd in parquet_dates}
    
    missing_exceptions = original_date_set - parquet_date_set
    extra_exceptions = parquet_date_set - original_date_set
    
    if missing_exceptions:
        logger.warning("Exceptions missing in Parquet:")
        for service_id, date, exception_type in missing_exceptions:
            logger.warning(f"  Service {service_id}: {date} (type {exception_type})")
    
    if extra_exceptions:
        logger.warning("Extra exceptions in Parquet:")
        for service_id, date, exception_type in extra_exceptions:
            logger.warning(f"  Service {service_id}: {date} (type {exception_type})")
    
    if not (missing_exceptions or extra_exceptions):
        logger.info("No differences found in calendar dates")

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
    
    # Compare trips
    compare_trips(original_feed, parquet_feed)
    
    # Compare stop times
    compare_stop_times(original_feed, parquet_feed)
    
    # Get a route from each implementation
    original_route = original_feed.routes[0] if isinstance(original_feed.routes, list) else next(iter(original_feed.routes.values()))
    parquet_route = parquet_feed.routes[0]
    
    # Compare route stops
    original_stops = original_route.stops
    parquet_stops = parquet_route.stops
    stop_differences = []
    if len(original_stops) != len(parquet_stops):
        stop_differences.append(f"Route stop count mismatch - Original: {len(original_stops)}, Parquet: {len(parquet_stops)}")
    if stop_differences:
        logger.error("Found differences in route stops. Printing first 10 differences:")
        for diff in stop_differences[:10]:
            logger.error(diff)
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

    # Compare calendars
    compare_calendars(original_feed, parquet_feed)

if __name__ == "__main__":
    # Get data directory from environment or use default
    data_dir = Path(os.getenv("GTFS_DATA_DIR", "downloads/mdb-990_Budapesti_Kozlekedesi_Kozpont_BKK/mdb-990-202412300019"))
    
    # Test both implementations by default
    run_comparison(data_dir, test_original=True) 