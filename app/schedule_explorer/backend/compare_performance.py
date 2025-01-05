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
from app.schedule_explorer.backend import gtfs_loader, gtfs_parquet
from app.schedule_explorer.backend.gtfs_loader import RouteStop, Stop
from app.schedule_explorer.backend.models import BoundingBox, StationResponse, Location
import os
from app.schedule_explorer.backend import gtfs_loader, gtfs_parquet
from app.schedule_explorer.backend.gtfs_loader import FlixbusFeed

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("schedule_explorer.compare_performance")


def measure_memory() -> Dict[str, float]:
    """Get current memory usage."""
    process = psutil.Process()
    memory_info = process.memory_info()
    return {
        "rss": memory_info.rss / 1024 / 1024,  # MB
        "vms": memory_info.vms / 1024 / 1024,  # MB
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


def compare_translations(original_feed: FlixbusFeed, parquet_feed: FlixbusFeed) -> None:
    """Compare translations between original and Parquet implementations."""
    logger.info("\n=== Translation Loading Comparison ===")

    # Get translations from both feeds
    original_translations = {}
    parquet_translations = {}

    # Collect translations from stops
    for stop_id, stop in original_feed.stops.items():
        if stop.translations:
            original_translations[stop_id] = stop.translations

    for stop_id, stop in parquet_feed.stops.items():
        if stop.translations:
            parquet_translations[stop_id] = stop.translations

    # Compare number of stops with translations
    logger.info(f"Original: {len(original_translations)} stops with translations")
    logger.info(f"Parquet: {len(parquet_translations)} stops with translations")

    # Compare stop IDs with translations
    original_stop_ids = set(original_translations.keys())
    parquet_stop_ids = set(parquet_translations.keys())

    missing_in_parquet = original_stop_ids - parquet_stop_ids
    missing_in_original = parquet_stop_ids - original_stop_ids

    if missing_in_parquet:
        logger.warning(f"Stops with translations missing in Parquet: {missing_in_parquet}")
    if missing_in_original:
        logger.warning(f"Extra stops with translations in Parquet: {missing_in_original}")

    # Compare translations for common stops
    common_stops = original_stop_ids & parquet_stop_ids
    differences = []

    for stop_id in common_stops:
        orig_trans = original_translations[stop_id]
        parq_trans = parquet_translations[stop_id]

        # Compare languages
        orig_langs = set(orig_trans.keys())
        parq_langs = set(parq_trans.keys())

        if orig_langs != parq_langs:
            differences.append(f"Stop {stop_id}: Language set mismatch - Original: {orig_langs}, Parquet: {parq_langs}")
            continue

        # Compare translations for each language
        for lang in orig_langs:
            if orig_trans[lang] != parq_trans[lang]:
                differences.append(f"Stop {stop_id}, Language {lang}: Translation mismatch - Original: {orig_trans[lang]}, Parquet: {parq_trans[lang]}")

    if differences:
        logger.warning("Found differences in translations:")
        for diff in differences[:10]:  # Show only first 10 differences to avoid overwhelming output
            logger.warning(diff)
        if len(differences) > 10:
            logger.warning(f"... and {len(differences) - 10} more differences")
    else:
        logger.info("No differences found in translations")


def compare_stops(
    original_stops: Dict[str, Stop], parquet_stops: Dict[str, Stop]
) -> None:
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
            differences.append(
                f"Stop {stop_id}: Name mismatch - Original: {orig_stop.name}, Parquet: {parq_stop.name}"
            )
        if abs(orig_stop.lat - parq_stop.lat) > 1e-6:
            differences.append(
                f"Stop {stop_id}: Latitude mismatch - Original: {orig_stop.lat}, Parquet: {parq_stop.lat}"
            )
        if abs(orig_stop.lon - parq_stop.lon) > 1e-6:
            differences.append(
                f"Stop {stop_id}: Longitude mismatch - Original: {orig_stop.lon}, Parquet: {parq_stop.lon}"
            )
        if orig_stop.translations != parq_stop.translations:
            differences.append(
                f"Stop {stop_id}: Translation mismatch - Original: {orig_stop.translations}, Parquet: {parq_stop.translations}"
            )
        if orig_stop.location_type != parq_stop.location_type:
            differences.append(
                f"Stop {stop_id}: Location type mismatch - Original: {orig_stop.location_type}, Parquet: {parq_stop.location_type}"
            )
        if orig_stop.parent_station != parq_stop.parent_station:
            differences.append(
                f"Stop {stop_id}: Parent station mismatch - Original: {orig_stop.parent_station}, Parquet: {parq_stop.parent_station}"
            )
        if orig_stop.platform_code != parq_stop.platform_code:
            differences.append(
                f"Stop {stop_id}: Platform code mismatch - Original: {orig_stop.platform_code}, Parquet: {parq_stop.platform_code}"
            )
        if orig_stop.timezone != parq_stop.timezone:
            differences.append(
                f"Stop {stop_id}: Timezone mismatch - Original: {orig_stop.timezone}, Parquet: {parq_stop.timezone}"
            )
    
    if differences:
        logger.warning("Found differences in stops:")
        for diff in differences:
            logger.warning(diff)
    else:
        logger.info("No differences found in stops")


def compare_route_stops(original_feed: FlixbusFeed, parquet_feed: FlixbusFeed) -> None:
    """Compare route stops between original and Parquet implementations."""
    logger.info("\n=== Route Stop Comparison ===")

    # Get a route from each implementation
    original_route = (
        original_feed.routes[0]
        if isinstance(original_feed.routes, list)
        else next(iter(original_feed.routes.values()))
    )
    parquet_route = parquet_feed.routes[0]

    # Compare route stops
    original_stops = original_route.stops
    parquet_stops = parquet_route.stops
    stop_differences = []
    if len(original_stops) != len(parquet_stops):
        stop_differences.append(
            f"Route stop count mismatch - Original: {len(original_stops)}, Parquet: {len(parquet_stops)}"
        )
    if stop_differences:
        logger.error("Found differences in route stops. Printing first 10 differences:")
        for diff in stop_differences[:10]:
            logger.error(diff)
        return

    for i, (original_stop, parquet_stop) in enumerate(
        zip(original_stops, parquet_stops)
    ):
        if original_stop.stop.id != parquet_stop.stop.id:
            logger.error(
                f"Stop {i} ID mismatch - Original: {original_stop.stop.id}, Parquet: {parquet_stop.stop.id}"
            )
            return

        if original_stop.arrival_time != parquet_stop.arrival_time:
            logger.error(
                f"Stop {i} arrival time mismatch - Original: {original_stop.arrival_time}, Parquet: {parquet_stop.arrival_time}"
            )
            return

        if original_stop.departure_time != parquet_stop.departure_time:
            logger.error(
                f"Stop {i} departure time mismatch - Original: {original_stop.departure_time}, Parquet: {parquet_stop.departure_time}"
            )
            return

        if original_stop.stop_sequence != parquet_stop.stop_sequence:
            logger.error(
                f"Stop {i} sequence mismatch - Original: {original_stop.stop_sequence}, Parquet: {parquet_stop.stop_sequence}"
            )
            return

    logger.info("Route stops match")


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
    original_trips_with_times = sum(
        1 for trip in original_trips.values() if trip.stop_times
    )
    parquet_trips_with_times = sum(
        1 for trip in parquet_trips.values() if trip.stop_times
    )

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
            stop_times_differences.append(
                f"Trip {trip_id} has different number of stop times\n  Original: {len(orig_trip.stop_times)}\n  Parquet: {len(parquet_trip.stop_times)}"
            )
            continue

        # Compare each stop time
        for i, (orig_stop, parquet_stop) in enumerate(
            zip(orig_trip.stop_times, parquet_trip.stop_times)
        ):
            if (
                orig_stop.arrival_time != parquet_stop.arrival_time
                or orig_stop.departure_time != parquet_stop.departure_time
                or orig_stop.stop_id != parquet_stop.stop_id
                or orig_stop.stop_sequence != parquet_stop.stop_sequence
            ):
                differences += 1
                stop_times_differences.append(f"Trip {trip_id} has different stop times at index {i}:")
                stop_times_differences.append(f"  Original: {orig_stop}")
                stop_times_differences.append(f"  Parquet: {parquet_stop}")
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
    differences_in_trips = []
    if missing_in_parquet:
        differences_in_trips.append(f"Trips missing in Parquet: {missing_in_parquet}")
    if missing_in_original:
        differences_in_trips.append(f"Extra trips in Parquet: {missing_in_original}")
    if differences_in_trips:
        logger.warning("Found differences in trips:")
        for diff in differences_in_trips[:10]:
            logger.warning(diff)
        if len(differences_in_trips) > 10:
            logger.warning(f"... and {len(differences_in_trips) - 10} more differences")
    else:
        logger.info("No differences found in trips")

    # Compare trip attributes for common trips
    common_ids = original_ids & parquet_ids
    differences = []

    for trip_id in common_ids:
        orig_trip = original_feed.trips[trip_id]
        parq_trip = parquet_feed.trips[trip_id]

        # Compare each attribute
        if orig_trip.route_id != parq_trip.route_id:
            differences.append(
                f"Trip {trip_id}: Route ID mismatch - Original: {orig_trip.route_id}, Parquet: {parq_trip.route_id}"
            )
        if orig_trip.service_id != parq_trip.service_id:
            differences.append(
                f"Trip {trip_id}: Service ID mismatch - Original: {orig_trip.service_id}, Parquet: {parq_trip.service_id}"
            )
        if orig_trip.headsign != parq_trip.headsign:
            differences.append(
                f"Trip {trip_id}: Headsign mismatch - Original: {orig_trip.headsign}, Parquet: {parq_trip.headsign}"
            )
        if orig_trip.direction_id != parq_trip.direction_id:
            differences.append(
                f"Trip {trip_id}: Direction ID mismatch - Original: {orig_trip.direction_id}, Parquet: {parq_trip.direction_id}"
            )
        if orig_trip.block_id != parq_trip.block_id:
            differences.append(
                f"Trip {trip_id}: Block ID mismatch - Original: {orig_trip.block_id}, Parquet: {parq_trip.block_id}"
            )
        if orig_trip.shape_id != parq_trip.shape_id:
            differences.append(
                f"Trip {trip_id}: Shape ID mismatch - Original: {orig_trip.shape_id}, Parquet: {parq_trip.shape_id}"
            )

        # Compare stop times
        if len(orig_trip.stop_times) != len(parq_trip.stop_times):
            differences.append(
                f"Trip {trip_id}: Different number of stop times - Original: {len(orig_trip.stop_times)}, Parquet: {len(parq_trip.stop_times)}"
            )
        else:
            for i, (orig_st, parq_st) in enumerate(
                zip(orig_trip.stop_times, parq_trip.stop_times)
            ):
                if orig_st.stop_id != parq_st.stop_id:
                    differences.append(
                        f"Trip {trip_id}, Stop {i}: Stop ID mismatch - Original: {orig_st.stop_id}, Parquet: {parq_st.stop_id}"
                    )
                if orig_st.arrival_time != parq_st.arrival_time:
                    differences.append(
                        f"Trip {trip_id}, Stop {i}: Arrival time mismatch - Original: {orig_st.arrival_time}, Parquet: {parq_st.arrival_time}"
                    )
                if orig_st.departure_time != parq_st.departure_time:
                    differences.append(
                        f"Trip {trip_id}, Stop {i}: Departure time mismatch - Original: {orig_st.departure_time}, Parquet: {parq_st.departure_time}"
                    )
                if orig_st.stop_sequence != parq_st.stop_sequence:
                    differences.append(
                        f"Trip {trip_id}, Stop {i}: Stop sequence mismatch - Original: {orig_st.stop_sequence}, Parquet: {parq_st.stop_sequence}"
                    )

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
        logger.info(f"\nAnalyzing service {service_id}:")
        orig_cal = original_calendars[service_id]
        parq_cal = parquet_calendars[service_id]

        # Compare service days
        orig_days = []
        parq_days = []
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            if getattr(orig_cal, day):
                orig_days.append(day)
            if getattr(parq_cal, day):
                parq_days.append(day)
        
        if orig_days != parq_days:
            logger.warning("Service days mismatch:")
            logger.warning(f"  Original: {orig_days}")
            logger.warning(f"  Parquet:  {parq_days}")
        else:
            logger.info(f"Service days match: {orig_days}")

        # Compare validity period
        if orig_cal.start_date != parq_cal.start_date or orig_cal.end_date != parq_cal.end_date:
            logger.warning("Validity period mismatch:")
            logger.warning(f"  Original: {orig_cal.start_date} to {orig_cal.end_date}")
            logger.warning(f"  Parquet:  {parq_cal.start_date} to {parq_cal.end_date}")
        else:
            logger.info(f"Validity period matches: {orig_cal.start_date} to {orig_cal.end_date}")

    # Compare calendar dates (exceptions)
    logger.info("\nComparing calendar dates (exceptions)...")
    original_dates = original_feed.calendar_dates
    parquet_dates = parquet_feed.calendar_dates

    logger.info(f"Original: {len(original_dates)} exceptions")
    logger.info(f"Parquet: {len(parquet_dates)} exceptions")

    # Group exceptions by service ID for better comparison
    orig_exceptions = {}
    parq_exceptions = {}

    for cd in original_dates:
        if cd.service_id not in orig_exceptions:
            orig_exceptions[cd.service_id] = {"added": [], "removed": []}
        if cd.exception_type == 1:
            orig_exceptions[cd.service_id]["added"].append(cd.date)
        else:
            orig_exceptions[cd.service_id]["removed"].append(cd.date)

    for cd in parquet_dates:
        if cd.service_id not in parq_exceptions:
            parq_exceptions[cd.service_id] = {"added": [], "removed": []}
        if cd.exception_type == 1:
            parq_exceptions[cd.service_id]["added"].append(cd.date)
        else:
            parq_exceptions[cd.service_id]["removed"].append(cd.date)

    # Compare exceptions for each service
    all_service_ids = set(orig_exceptions.keys()) | set(parq_exceptions.keys())
    for service_id in all_service_ids:
        logger.info(f"\nExceptions for service {service_id}:")
        
        orig_exc = orig_exceptions.get(service_id, {"added": [], "removed": []})
        parq_exc = parq_exceptions.get(service_id, {"added": [], "removed": []})

        # Compare added dates
        orig_added = set(orig_exc["added"])
        parq_added = set(parq_exc["added"])
        if orig_added != parq_added:
            logger.warning("Added dates mismatch:")
            logger.warning(f"  Missing in Parquet: {orig_added - parq_added}")
            logger.warning(f"  Extra in Parquet: {parq_added - orig_added}")
        else:
            logger.info(f"Added dates match: {sorted(orig_added)}")

        # Compare removed dates
        orig_removed = set(orig_exc["removed"])
        parq_removed = set(parq_exc["removed"])
        if orig_removed != parq_removed:
            logger.warning("Removed dates mismatch:")
            logger.warning(f"  Missing in Parquet: {orig_removed - parq_removed}")
            logger.warning(f"  Extra in Parquet: {parq_removed - orig_removed}")
        else:
            logger.info(f"Removed dates match: {sorted(orig_removed)}")

    # Compare route service days
    logger.info("\nComparing route service days...")
    for route in original_feed.routes:
        logger.info(f"\nRoute {route.route_id}:")
        # Find matching route in parquet feed
        parq_route = next((r for r in parquet_feed.routes if r.route_id == route.route_id), None)
        if not parq_route:
            logger.warning(f"Route {route.route_id} not found in Parquet implementation")
            continue

        # Compare service days
        if set(route.service_days) != set(parq_route.service_days):
            logger.warning("Service days mismatch:")
            logger.warning(f"  Original: {route.service_days}")
            logger.warning(f"  Parquet:  {parq_route.service_days}")
        else:
            logger.info(f"Service days match: {route.service_days}")

        # Compare service calendar
        if route.service_calendar != parq_route.service_calendar:
            logger.warning("Service calendar mismatch:")
            logger.warning(f"  Original: {route.service_calendar}")
            logger.warning(f"  Parquet:  {parq_route.service_calendar}")
        else:
            logger.info(f"Service calendar matches: {route.service_calendar}")

        # Compare valid calendar days
        orig_days = set(d.date() for d in route.valid_calendar_days)
        parq_days = set(d.date() for d in parq_route.valid_calendar_days)
        if orig_days != parq_days:
            logger.warning("Valid calendar days mismatch:")
            logger.warning(f"  Missing in Parquet: {orig_days - parq_days}")
            logger.warning(f"  Extra in Parquet: {parq_days - orig_days}")
        else:
            logger.info(f"Valid calendar days match: {len(orig_days)} days")


def compare_bbox_queries(data_dir: Path) -> None:
    """Compare bounding box queries between original and Parquet implementations."""
    logger.info("Testing bounding box queries...")
    
    # Load both implementations
    parquet_feed = test_parquet_implementation(data_dir)
    if not parquet_feed:
        logger.error("Failed to load Parquet implementation")
        return
    
    original_feed = test_original_implementation(data_dir)
    if not original_feed:
        logger.error("Failed to load original implementation")
        return
    
    # Test bounding box for STIB/MIVB
    bbox = BoundingBox(
        min_lat=50.67209461471226,
        max_lat=51.01893827029199,
        min_lon=3.6254882812500004,
        max_lon=5.158081054687501
    )
    
    # Get stops from both implementations
    original_stops = original_feed.get_stops_in_bbox(bbox)
    parquet_stops = parquet_feed.get_stops_in_bbox(bbox)
    
    # Compare results
    logger.info(f"Original implementation found {len(original_stops)} stops")
    logger.info(f"Parquet implementation found {len(parquet_stops)} stops")
    
    if len(original_stops) != len(parquet_stops):
        logger.error("Different number of stops found!")
        return
    
    # Compare stop details
    original_stops_dict = {stop.id: stop for stop in original_stops}
    parquet_stops_dict = {stop.id: stop for stop in parquet_stops}
    
    for stop_id in original_stops_dict:
        if stop_id not in parquet_stops_dict:
            logger.error(f"Stop {stop_id} found in original but not in Parquet")
            continue
            
        original_stop = original_stops_dict[stop_id]
        parquet_stop = parquet_stops_dict[stop_id]
        
        if original_stop.name != parquet_stop.name:
            logger.error(f"Stop {stop_id} has different names: {original_stop.name} vs {parquet_stop.name}")
        
        if original_stop.lat != parquet_stop.lat or original_stop.lon != parquet_stop.lon:
            logger.error(f"Stop {stop_id} has different coordinates: ({original_stop.lat}, {original_stop.lon}) vs ({parquet_stop.lat}, {parquet_stop.lon})")
        
        # Compare service days for each route serving this stop
        original_routes = [r for r in original_feed.routes if any(s.stop.id == stop_id for s in r.stops)]
        parquet_routes = [r for r in parquet_feed.routes if any(s.stop.id == stop_id for s in r.stops)]
        
        logger.info(f"\nComparing service days for stop {stop_id}:")
        logger.info(f"Original implementation has {len(original_routes)} routes")
        logger.info(f"Parquet implementation has {len(parquet_routes)} routes")
        
        # Create dictionaries mapping route IDs to service days
        original_service_days = {r.id: set(r.service_days) for r in original_routes}
        parquet_service_days = {r.id: set(r.service_days) for r in parquet_routes}
        
        # Compare service days for each route
        all_route_ids = set(original_service_days.keys()) | set(parquet_service_days.keys())
        for route_id in all_route_ids:
            if route_id not in original_service_days:
                logger.error(f"Route {route_id} missing in original implementation")
                continue
            if route_id not in parquet_service_days:
                logger.error(f"Route {route_id} missing in Parquet implementation")
                continue
            
            orig_days = original_service_days[route_id]
            parq_days = parquet_service_days[route_id]
            
            if orig_days != parq_days:
                logger.error(f"Service days mismatch for route {route_id}:")
                logger.error(f"  Original: {sorted(list(orig_days))}")
                logger.error(f"  Parquet:  {sorted(list(parq_days))}")
                logger.error(f"  Missing in Parquet: {orig_days - parq_days}")
                logger.error(f"  Extra in Parquet: {parq_days - orig_days}")
    
    for stop_id in parquet_stops_dict:
        if stop_id not in original_stops_dict:
            logger.error(f"Stop {stop_id} found in Parquet but not in original")

def compare_waiting_times(data_dir: Path) -> None:
    """Compare waiting times between original and Parquet implementations."""
    logger.info("Testing waiting times...")
    
    # Load both implementations
    parquet_feed = test_parquet_implementation(data_dir)
    if not parquet_feed:
        logger.error("Failed to load Parquet implementation")
        return
    
    original_feed = test_original_implementation(data_dir)
    if not original_feed:
        logger.error("Failed to load original implementation")
        return
    
    # Test waiting times for BKK stop F01111
    stop_id = "F01111"
    
    # Get waiting times from both implementations
    original_waiting_times = original_feed.get_waiting_times(stop_id)
    parquet_waiting_times = parquet_feed.get_waiting_times(stop_id)
    
    # Compare results
    logger.info(f"Original implementation found {len(original_waiting_times)} waiting times")
    logger.info(f"Parquet implementation found {len(parquet_waiting_times)} waiting times")
    
    if len(original_waiting_times) != len(parquet_waiting_times):
        logger.error("Different number of waiting times found!")
        return
    
    # Compare waiting time details
    for orig_wt, parq_wt in zip(original_waiting_times, parquet_waiting_times):
        if orig_wt.line != parq_wt.line:
            logger.error(f"Different line: {orig_wt.line} vs {parq_wt.line}")
        
        if orig_wt.destination != parq_wt.destination:
            logger.error(f"Different destination: {orig_wt.destination} vs {parq_wt.destination}")
        
        if orig_wt.minutes != parq_wt.minutes:
            logger.error(f"Different minutes: {orig_wt.minutes} vs {parq_wt.minutes}")
        
        if orig_wt.scheduled_time != parq_wt.scheduled_time:
            logger.error(f"Different scheduled time: {orig_wt.scheduled_time} vs {parq_wt.scheduled_time}")
        
        if orig_wt.service_days != parq_wt.service_days:
            logger.error(f"Different service days: {orig_wt.service_days} vs {parq_wt.service_days}")
        
        if orig_wt.service_calendar != parq_wt.service_calendar:
            logger.error(f"Different service calendar: {orig_wt.service_calendar} vs {parq_wt.service_calendar}")

def compare_shapes(original_feed: FlixbusFeed, parquet_feed: FlixbusFeed) -> None:
    """Compare shapes between original and Parquet implementations."""
    logger.info("\n=== Shape Comparison ===")

    # Get a route from each implementation
    original_route = (
        original_feed.routes[0]
        if isinstance(original_feed.routes, list)
        else next(iter(original_feed.routes.values()))
    )
    parquet_route = parquet_feed.routes[0]

    # Compare shapes
    logger.info("Testing shapes...")
    if original_route.shape is None and parquet_route.shape is None:
        logger.info("Both implementations have no shapes")
    elif original_route.shape is None:
        logger.error(
            "Original implementation has no shape but Parquet implementation does"
        )
        return
    elif parquet_route.shape is None:
        logger.error(
            "Parquet implementation has no shape but Original implementation does"
        )
        return
    else:
        if original_route.shape.shape_id != parquet_route.shape.shape_id:
            logger.error(
                f"Shape ID mismatch - Original: {original_route.shape.shape_id}, Parquet: {parquet_route.shape.shape_id}"
            )
            return

        if len(original_route.shape.points) != len(parquet_route.shape.points):
            logger.error(
                f"Shape point count mismatch - Original: {len(original_route.shape.points)}, Parquet: {len(parquet_route.shape.points)}"
            )
            return

        for i, (original_point, parquet_point) in enumerate(
            zip(original_route.shape.points, parquet_route.shape.points)
        ):
            if len(original_point) != 2 or len(parquet_point) != 2:
                logger.error(f"Shape point format mismatch at index {i}")
                return

            # Compare lat/lon with small tolerance for floating point differences
            if (
                abs(original_point[0] - parquet_point[0]) > 1e-6
                or abs(original_point[1] - parquet_point[1]) > 1e-6
            ):
                logger.error(
                    f"Shape point mismatch at index {i} - Original: {original_point}, Parquet: {parquet_point}"
                )
                return

        logger.info("Shapes match")


def compare_implementations(data_dir: Path) -> None:
    """Compare the original and Parquet implementations."""
    logger.info("Testing Parquet implementation...")
    parquet_feed = test_parquet_implementation(data_dir)
    if not parquet_feed:
        logger.error("Parquet implementation test failed")
        return
    
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

    # Compare translations
    compare_translations(original_feed, parquet_feed)
    
    # Compare route stops
    compare_route_stops(original_feed, parquet_feed)

    # Compare shapes
    compare_shapes(original_feed, parquet_feed)

    # Compare calendars
    compare_calendars(original_feed, parquet_feed)


def run_comparison():
    """Run the comparison between original and Parquet implementations."""
    workspace_root = Path(__file__).parent.parent.parent.parent
    
    logger.info("\n=== Testing STIB/MIVB dataset ===")
    stib_dir = workspace_root / "downloads/mdb-1088_Societe_des_Transports_Intercommunaux_de_Bruxelles_Maatschappij_voor_het_Intercommunaal_Vervoer_te_Brussel_STIB_MIVB/mdb-1088-202412260045"
    if not stib_dir.exists():
        logger.error(f"Dataset directory not found: {stib_dir}")
    else:
        compare_implementations(stib_dir)
        compare_bbox_queries(stib_dir)
        compare_waiting_times(stib_dir)
    
    logger.info("\n=== Testing BKK dataset ===")
    bkk_dir = workspace_root / "downloads/mdb-990_Budapesti_Kozlekedesi_Kozpont_BKK/mdb-990-202412300019"
    if not bkk_dir.exists():
        logger.error(f"Dataset directory not found: {bkk_dir}")
    else:
        compare_implementations(bkk_dir)
        compare_bbox_queries(bkk_dir)
        compare_waiting_times(bkk_dir)


if __name__ == "__main__":
    run_comparison() 
