from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set
import pandas as pd
from pathlib import Path
import os
import hashlib
import logging
import msgpack
import lzma
import psutil
import time
from .memory_util import check_memory_for_file


def bytes_to_mb(bytes: int, precision: int = 2) -> int:
    """Convert bytes to megabytes."""
    return round(bytes / (1024 * 1024), precision)


logger = logging.getLogger("schedule_explorer.gtfs_loader")


@dataclass
class Translation:
    """
    Represents a translation from translations.txt (STIB specific)
    trans_id/record_id, translation, lang
    """

    record_id: str
    translation: str
    language: str


@dataclass
class Stop:
    """
    Represents a stop from stops.txt
    STIB: stop_id, stop_name, stop_lat, stop_lon, location_type, parent_station
    Flixbus: stop_id, stop_name, stop_lat, stop_lon, stop_timezone, platform_code
    """

    id: str
    name: str
    lat: float
    lon: float
    translations: Dict[str, str] = field(
        default_factory=dict
    )  # language -> translated name
    location_type: Optional[int] = None
    parent_station: Optional[str] = None
    platform_code: Optional[str] = None
    timezone: Optional[str] = None


@dataclass
class RouteStop:
    stop: Stop
    arrival_time: str
    departure_time: str
    stop_sequence: int


@dataclass
class Shape:
    shape_id: str
    points: List[List[float]]


@dataclass
class StopTime:
    """
    Represents a stop time from stop_times.txt
    STIB: trip_id, arrival_time, departure_time, stop_id, stop_sequence
    Flixbus: trip_id, stop_id, arrival_time, departure_time, stop_sequence
    """

    trip_id: str
    stop_id: str
    arrival_time: str
    departure_time: str
    stop_sequence: int


@dataclass
class Trip:
    """
    Represents a trip from trips.txt
    STIB: route_id, service_id, trip_id, trip_headsign, direction_id, block_id, shape_id
    Flixbus: route_id, trip_id, service_id, trip_headsign, block_id, shape_id
    """

    id: str
    route_id: str
    service_id: str
    headsign: Optional[str] = None
    direction_id: Optional[str] = None
    block_id: Optional[str] = None
    shape_id: Optional[str] = None
    stop_times: List[StopTime] = field(default_factory=list)


@dataclass
class Calendar:
    """
    Represents a service calendar from calendar.txt
    Both: service_id, monday-sunday (0/1), start_date, end_date
    """

    service_id: str
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    start_date: datetime
    end_date: datetime


@dataclass
class CalendarDate:
    """
    Represents a calendar exception from calendar_dates.txt
    Both: service_id, date, exception_type (1=added, 2=removed)
    """

    service_id: str
    date: datetime
    exception_type: int  # 1 = service added, 2 = service removed


@dataclass
class Agency:
    """
    Represents an agency from agency.txt
    Required fields: agency_id, agency_name, agency_url, agency_timezone
    Optional fields: agency_lang, agency_phone, agency_fare_url, agency_email
    """

    agency_id: str
    agency_name: str
    agency_url: str
    agency_timezone: str
    agency_lang: Optional[str] = None
    agency_phone: Optional[str] = None
    agency_fare_url: Optional[str] = None
    agency_email: Optional[str] = None


@dataclass
class Route:
    route_id: str
    route_name: str
    trip_id: str
    stops: List[RouteStop]
    service_days: List[str]
    shape: Optional[Shape] = None
    short_name: Optional[str] = None
    long_name: Optional[str] = None
    route_type: Optional[int] = None
    color: Optional[str] = None
    text_color: Optional[str] = None
    agency_id: Optional[str] = None
    headsigns: Dict[str, str] = field(default_factory=dict)  # direction_id -> headsign
    service_ids: List[str] = field(
        default_factory=list
    )  # List of all service IDs for this route
    direction_id: Optional[str] = None  # Direction of this route variant
    route_desc: Optional[str] = None  # Description of the route
    route_url: Optional[str] = None  # URL of a web page about the route
    route_sort_order: Optional[int] = None  # Order in which routes should be displayed
    continuous_pickup: Optional[int] = None  # Flag stop behavior for pickup (0-3)
    continuous_drop_off: Optional[int] = None  # Flag stop behavior for drop-off (0-3)
    trips: List[Trip] = field(default_factory=list)  # List of trips for this route
    _feed: Optional["FlixbusFeed"] = field(
        default=None, repr=False, compare=False, hash=False
    )
    # New debug and service calendar fields
    service_days_explicit: List[str] = field(
        default_factory=list
    )  # Days from calendar.txt
    calendar_dates_additions: List[datetime] = field(
        default_factory=list
    )  # Days added via exceptions
    calendar_dates_removals: List[datetime] = field(
        default_factory=list
    )  # Days removed via exceptions
    valid_calendar_days: List[datetime] = field(
        default_factory=list
    )  # All valid service days
    service_calendar: Optional[str] = None  # Human readable service calendar

    def __post_init__(self):
        """Calculate service days after initialization"""
        if not self.service_days and self.trips and self._feed:
            self.calculate_service_info()

    @property
    def computed_service_days(self) -> List[str]:
        """DEPRECATED: Use calculate_service_info() instead"""
        logger.warning(
            f"Route {self.route_id}: Using deprecated computed_service_days property, should use calculate_service_info() instead"
        )
        if not self.trips or not self._feed:
            return []

        # Get unique service IDs from all trips
        service_ids = {trip.service_id for trip in self.trips}

        # Get days from both regular calendars and calendar dates
        days = set()

        # First check calendar_dates for type 1 exceptions (added service)
        # Create a map of service_id -> set of weekdays it operates on
        service_days = {}
        for cal_date in self._feed.calendar_dates:
            if cal_date.service_id in service_ids:
                weekday = cal_date.date.strftime("%A").lower()
                if cal_date.service_id not in service_days:
                    service_days[cal_date.service_id] = set()
                if cal_date.exception_type == 1:  # Service added
                    service_days[cal_date.service_id].add(weekday)

        # Add all days from calendar exceptions
        for weekdays in service_days.values():
            days.update(weekdays)

        # Then check regular calendars if they exist
        has_regular_calendar = False
        for service_id in service_ids:
            if service_id in self._feed.calendars:
                calendar = self._feed.calendars[service_id]
                # Only consider this calendar if it has at least one day set to 1
                if any(
                    getattr(calendar, day)
                    for day in [
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    ]
                ):
                    has_regular_calendar = True
                    for day in [
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    ]:
                        if getattr(calendar, day):
                            days.add(day)

        if has_regular_calendar:
            # If we have regular calendars, check for type 2 exceptions (removals)
            # Group exceptions by weekday to see if any day is completely removed
            removals_by_day = {}
            for cal_date in self._feed.calendar_dates:
                if cal_date.service_id in service_ids and cal_date.exception_type == 2:
                    weekday = cal_date.date.strftime("%A").lower()
                    if weekday not in removals_by_day:
                        removals_by_day[weekday] = set()
                    removals_by_day[weekday].add(cal_date.service_id)

            # Remove days that are completely excluded by type 2 exceptions
            for day, removed_services in removals_by_day.items():
                if (
                    removed_services == service_ids
                ):  # All services have this day removed
                    days.discard(day)

        return sorted(list(days))

    def calculate_service_info(self) -> None:
        """Calculate service calendar information"""
        # logger.info(
        #     f"=== Starting service calendar calculation for route {self.route_id} ==="
        # )

        if not self.trips or not self._feed:
            logger.error(f"Route {self.route_id}: No trips or feed available")
            return

        # Get unique service IDs from all trips
        service_ids = {trip.service_id for trip in self.trips}
        # logger.info(f"Route {self.route_id}: Found service IDs: {service_ids}")

        # Log the actual service IDs we found in calendar.txt and calendar_dates.txt
        calendar_service_ids = set(self._feed.calendars.keys())
        calendar_dates_service_ids = {cd.service_id for cd in self._feed.calendar_dates}
        # logger.info(
        #     f"Route {self.route_id}: Service IDs in calendar.txt: {calendar_service_ids}"
        # )
        # logger.info(
        #     f"Route {self.route_id}: Service IDs in calendar_dates.txt: {calendar_dates_service_ids}"
        # )

        # Calculate how many of our service IDs are in each file
        calendar_matches = service_ids & calendar_service_ids
        calendar_dates_matches = service_ids & calendar_dates_service_ids
        # logger.info(
        #     f"Route {self.route_id}: Found {len(calendar_matches)}/{len(service_ids)} service IDs in calendar.txt"
        # )
        # logger.info(
        #     f"Route {self.route_id}: Found {len(calendar_dates_matches)}/{len(service_ids)} service IDs in calendar_dates.txt"
        # )

        # Calculate service_days_explicit from calendar.txt
        self.service_days_explicit = []
        has_regular_calendar = False
        has_calendar_entries = False
        for service_id in service_ids:
            if service_id in self._feed.calendars:
                has_calendar_entries = True
                calendar = self._feed.calendars[service_id]
                # logger.info(
                #     f"Route {self.route_id}: Service {service_id} found in calendar.txt"
                # )
                # # Only consider this calendar if it has at least one day set to 1
                active_days = []
                for day in [
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                ]:
                    if getattr(calendar, day):
                        active_days.append(day)
                if active_days:
                    has_regular_calendar = True
                    for day in active_days:
                        self.service_days_explicit.append(day.capitalize())
            #         logger.info(
            #             f"Route {self.route_id}: Service {service_id} active on: {', '.join(active_days)}"
            #         )
            #     else:
            #         logger.info(
            #             f"Route {self.route_id}: Service {service_id} has no active days in calendar.txt"
            #         )
            # else:
            #     logger.info(
            #         f"Route {self.route_id}: Service {service_id} not found in calendar.txt"
            #     )
        self.service_days_explicit = sorted(list(set(self.service_days_explicit)))
        # logger.info(
        #     f"Route {self.route_id}: Final service_days_explicit: {self.service_days_explicit}"
        # )

        # Calculate calendar_dates_additions and calendar_dates_removals
        self.calendar_dates_additions = []
        self.calendar_dates_removals = []
        additions_by_service = {}  # service_id -> list of dates
        removals_by_service = {}  # service_id -> list of dates
        for cal_date in self._feed.calendar_dates:
            if cal_date.service_id in service_ids:
                if cal_date.exception_type == 1:  # Service added
                    self.calendar_dates_additions.append(cal_date.date)
                    if cal_date.service_id not in additions_by_service:
                        additions_by_service[cal_date.service_id] = []
                    additions_by_service[cal_date.service_id].append(cal_date.date)
                elif cal_date.exception_type == 2:  # Service removed
                    self.calendar_dates_removals.append(cal_date.date)
                    if cal_date.service_id not in removals_by_service:
                        removals_by_service[cal_date.service_id] = []
                    removals_by_service[cal_date.service_id].append(cal_date.date)

        # Log additions and removals by service ID
        for service_id in service_ids:
            additions = additions_by_service.get(service_id, [])
            removals = removals_by_service.get(service_id, [])
            # logger.info(
            #     f"Route {self.route_id}: Service {service_id} has {len(additions)} additions and {len(removals)} removals"
            # )
            # if additions:
            #     logger.info(
            #         f"Route {self.route_id}: Service {service_id} additions: {[d.strftime('%Y-%m-%d') for d in additions]}"
            #     )
            # if removals:
            #     logger.info(
            #         f"Route {self.route_id}: Service {service_id} removals: {[d.strftime('%Y-%m-%d') for d in removals]}"
            #     )

        # Calculate valid_calendar_days
        self.valid_calendar_days = []
        if has_regular_calendar:
            # logger.info(
            #     f"Route {self.route_id}: Using regular calendar (has_regular_calendar=True)"
            # )
            # Get the feed's validity window from calendar.txt
            start_dates = []
            end_dates = []
            for service_id in service_ids:
                if service_id in self._feed.calendars:
                    calendar = self._feed.calendars[service_id]
                    start_dates.append(calendar.start_date)
                    end_dates.append(calendar.end_date)
                    # logger.info(
                    #     f"Route {self.route_id}: Service {service_id} validity: {calendar.start_date.strftime('%Y-%m-%d')} to {calendar.end_date.strftime('%Y-%m-%d')}"
                    # )

            if start_dates and end_dates:
                start_date = min(start_dates)
                end_date = max(end_dates)
                # logger.info(
                #     f"Route {self.route_id}: Calendar window: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
                # )

                # For each day in the window, check if the route operates
                current_date = start_date
                while current_date <= end_date:
                    if self.operates_on(current_date):
                        self.valid_calendar_days.append(current_date)
                        # logger.info(
                        #     f"Route {self.route_id}: Service operates on {current_date.strftime('%Y-%m-%d')}"
                        # )
                    current_date += timedelta(days=1)
            # else:
            #     logger.error(
            #         f"Route {self.route_id}: No valid dates found in calendar.txt despite has_regular_calendar=True"
            #     )
        else:
            # logger.info(
            #     f"Route {self.route_id}: Using calendar_dates.txt (has_regular_calendar=False)"
            # )
            if self.calendar_dates_additions:
                self.valid_calendar_days = sorted(self.calendar_dates_additions)
            #     logger.info(
            #         f"Route {self.route_id}: Valid calendar days from additions: {[d.strftime('%Y-%m-%d') for d in self.valid_calendar_days]}"
            #     )
            # else:
            #     logger.error(
            #         f"Route {self.route_id}: No calendar_dates_additions found despite using calendar_dates.txt"
            # )

        # Create human-readable service calendar
        if self.valid_calendar_days:
            # Group consecutive dates
            date_ranges = []
            current_range = [self.valid_calendar_days[0]]

            # Remove duplicates and sort
            unique_dates = sorted(list(set(self.valid_calendar_days)))

            # Group into continuous ranges
            for date in unique_dates[1:]:
                if date - current_range[-1] <= timedelta(
                    days=1
                ):  # Allow 1 day gap to merge duplicates
                    current_range.append(date)
                else:
                    # Only add the first and last date of the range
                    date_ranges.append([current_range[0], current_range[-1]])
                    current_range = [date]
            # Add the last range
            date_ranges.append([current_range[0], current_range[-1]])

            # Format date ranges
            formatted_ranges = []
            for start_date, end_date in date_ranges:
                if start_date == end_date:
                    formatted_ranges.append(start_date.strftime("%Y-%m-%d"))
                else:
                    formatted_ranges.append(
                        f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
                    )

            self.service_calendar = "; ".join(formatted_ranges)
            # logger.info(
            #     f"Route {self.route_id}: Service calendar: {self.service_calendar}"
            # )
        else:
            self.service_calendar = None
            # logger.error(
            #     f"Route {self.route_id}: No service calendar (no valid calendar days)"
            # )

        # Update service_days based on valid_calendar_days
        if self.valid_calendar_days:
            weekdays = {d.strftime("%A").lower() for d in self.valid_calendar_days}
            self.service_days = sorted(list(weekdays))
            # logger.info(
            #     f"Route {self.route_id}: Final service_days: {self.service_days}"
            # )
        else:
            logger.error(
                f"Route {self.route_id}: No service_days (no valid calendar days)"
            )

        # If we have calendar_dates_additions but no service_days yet, calculate them from the additions
        if not self.service_days and self.calendar_dates_additions:
            weekdays = {d.strftime("%A").lower() for d in self.calendar_dates_additions}
            self.service_days = sorted(list(weekdays))
            # logger.info(
            #     f"Route {self.route_id}: Service days calculated from calendar_dates_additions: {self.service_days}"
            # )

        # logger.info(
        #     f"=== Completed service calendar calculation for route {self.route_id} ==="
        # )
        # logger.info(
        #     f"Final state: service_days={self.service_days}, service_calendar={self.service_calendar}, valid_calendar_days={len(self.valid_calendar_days)} days"
        # )

    def operates_on(self, date: datetime) -> bool:
        """Check if this route operates on a specific date"""
        if not self._feed:
            logger.info(
                f"Route {self.route_id}: No feed available for operates_on check"
            )
            return False

        # Check each service ID for this route
        for service_id in self.service_ids:
            operates = False
            has_exception = False

            # First check calendar_dates exceptions
            for cal_date in self._feed.calendar_dates:
                if (
                    cal_date.service_id == service_id
                    and cal_date.date.date() == date.date()
                ):
                    has_exception = True
                    if cal_date.exception_type == 1:  # Service added
                        operates = True
                        # logger.info(
                        #     f"Route {self.route_id}: Service {service_id} added on {date.strftime('%Y-%m-%d')} via exception"
                        # )
                        break
                    elif cal_date.exception_type == 2:  # Service removed
                        operates = False
                        # logger.info(
                        #     f"Route {self.route_id}: Service {service_id} removed on {date.strftime('%Y-%m-%d')} via exception"
                        # )
                        break

            # If no exception found and we have a regular calendar, check it
            if not has_exception and service_id in self._feed.calendars:
                calendar = self._feed.calendars[service_id]
                if (
                    calendar.start_date.date()
                    <= date.date()
                    <= calendar.end_date.date()
                ):
                    weekday = date.strftime("%A").lower()
                    operates = getattr(calendar, weekday)
                    # if operates:
                    #     logger.info(
                    #         f"Route {self.route_id}: Service {service_id} operates on {date.strftime('%Y-%m-%d')} ({weekday}) via regular calendar"
                    #     )
                    # else:
                    #     logger.info(
                    #         f"Route {self.route_id}: Service {service_id} does not operate on {date.strftime('%Y-%m-%d')} ({weekday}) via regular calendar"
                    #     )
            elif not has_exception and not self._feed.calendars:
                # If we only have calendar_dates.txt, treat no exception as not operating
                operates = False
                # logger.info(
                #     f"Route {self.route_id}: Service {service_id} does not operate on {date.strftime('%Y-%m-%d')} (no calendar.txt and no exception)"
                # )

            # If any service ID operates on this date, the route operates
            if operates:
                return True

        # logger.info(
        #     f"Route {self.route_id}: No service operates on {date.strftime('%Y-%m-%d')}"
        # )
        return False

    def get_stop_by_id(self, stop_id: str) -> Optional[RouteStop]:
        """Get a stop in this route by its ID"""
        return next((stop for stop in self.stops if stop.stop.id == stop_id), None)

    def get_stops_between(
        self, start_id: Optional[str], end_id: Optional[str]
    ) -> List[RouteStop]:
        """Get all stops between (and including) the start and end stops"""
        if start_id is None and end_id is None:
            return []

        if start_id is None:
            # Find the end stop and return all stops up to it
            end_seq = next(
                (s.stop_sequence for s in self.stops if s.stop.id == end_id), None
            )
            if end_seq is None:
                return []
            return [s for s in self.stops if s.stop_sequence <= end_seq]

        if end_id is None:
            # Find the start stop and return all stops after it
            start_seq = next(
                (s.stop_sequence for s in self.stops if s.stop.id == start_id), None
            )
            if start_seq is None:
                return []
            return [s for s in self.stops if s.stop_sequence >= start_seq]

        # Both stops are specified
        start_seq = next(
            (s.stop_sequence for s in self.stops if s.stop.id == start_id), None
        )
        end_seq = next(
            (s.stop_sequence for s in self.stops if s.stop.id == end_id), None
        )

        if start_seq is None or end_seq is None:
            return []

        # Handle both directions
        if start_seq <= end_seq:
            return [s for s in self.stops if start_seq <= s.stop_sequence <= end_seq]
        else:
            # For reverse direction, return stops in the original order
            return [s for s in self.stops if end_seq <= s.stop_sequence <= start_seq]

    def calculate_duration(self, start_id: str, end_id: str) -> Optional[timedelta]:
        """Calculate duration between any two stops in the route"""
        start_stop = self.get_stop_by_id(start_id)
        end_stop = self.get_stop_by_id(end_id)

        if not (start_stop and end_stop):
            return None

        def parse_time(time_str: str) -> datetime:
            hours, minutes, seconds = map(int, time_str.split(":"))
            base_date = datetime.today().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            return base_date + timedelta(hours=hours, minutes=minutes, seconds=seconds)

        departure = parse_time(start_stop.departure_time)
        arrival = parse_time(end_stop.arrival_time)

        if arrival < departure:  # Handle overnight routes
            arrival += timedelta(days=1)

        return arrival - departure


@dataclass
class FlixbusFeed:
    stops: Dict[str, Stop]
    routes: List[Route]
    calendars: Dict[str, Calendar] = field(default_factory=dict)
    calendar_dates: List[CalendarDate] = field(default_factory=list)
    trips: Dict[str, Trip] = field(default_factory=dict)
    stop_times_dict: Dict[str, List[Dict]] = field(
        default_factory=dict
    )  # trip_id -> list of stop times
    agencies: Dict[str, Agency] = field(default_factory=dict)  # agency_id -> Agency
    _feed: Optional["FlixbusFeed"] = field(default=None, repr=False)

    def __post_init__(self):
        """Set feed reference on all routes"""
        for route in self.routes:
            route._feed = self

    def get_stops_in_bbox(self, bbox) -> List[Stop]:
        """Get all stops within a bounding box."""
        result = []
        for stop in self.stops.values():
            if (bbox.min_lat <= stop.lat <= bbox.max_lat and 
                bbox.min_lon <= stop.lon <= bbox.max_lon):
                result.append(stop)
        return result

    def find_routes_between_stations(self, start_id: str, end_id: str) -> List[Route]:
        """Find all routes between two stations in any direction (start_id → end_id or end_id → start_id)"""
        routes = []

        # Group routes by route_id to check all variants
        routes_by_id = {}
        for route in self.routes:
            if route.route_id not in routes_by_id:
                routes_by_id[route.route_id] = []
            routes_by_id[route.route_id].append(route)

        # Check each route group
        for route_variants in routes_by_id.values():
            for route in route_variants:
                # Get all stops in sequence
                stop_sequences = [
                    (stop.stop.id, idx) for idx, stop in enumerate(route.stops)
                ]

                # Find positions of our target stops
                start_positions = [
                    idx for sid, idx in stop_sequences if sid == start_id
                ]
                end_positions = [idx for sid, idx in stop_sequences if sid == end_id]

                # Skip if either stop is not in this route
                if not start_positions or not end_positions:
                    continue

                # Check if we have a valid sequence
                for start_idx in start_positions:
                    for end_idx in end_positions:
                        # Check if the stops appear in sequence (either direction)
                        if start_idx < end_idx:  # Forward direction
                            # Verify no other occurrence of start_id or end_id between these positions
                            intermediate_stops = stop_sequences[start_idx + 1 : end_idx]
                            if not any(
                                sid in (start_id, end_id)
                                for sid, _ in intermediate_stops
                            ):
                                routes.append(route)
                                break
                        elif start_idx > end_idx:  # Reverse direction
                            # Verify no other occurrence of start_id or end_id between these positions
                            intermediate_stops = stop_sequences[end_idx + 1 : start_idx]
                            if not any(
                                sid in (start_id, end_id)
                                for sid, _ in intermediate_stops
                            ):
                                # Create a new route object with reversed direction_id
                                reversed_route = Route(
                                    route_id=route.route_id,
                                    route_name=route.route_name,
                                    trip_id=route.trip_id,
                                    service_days=route.service_days,
                                    stops=route.stops,
                                    shape=route.shape,
                                    short_name=route.short_name,
                                    long_name=route.long_name,
                                    route_type=route.route_type,
                                    color=route.color,
                                    text_color=route.text_color,
                                    agency_id=route.agency_id,
                                    headsigns=route.headsigns,
                                    service_ids=route.service_ids,
                                    direction_id=(
                                        "1" if route.direction_id == "0" else "0"
                                    ),
                                    trips=route.trips,  # Copy trips list
                                    _feed=route._feed,  # Copy feed reference
                                )
                                routes.append(reversed_route)
                                break
                    if (
                        route in routes
                    ):  # Skip checking more positions if we already added this route
                        break

        return routes

    def get_stop_name(
        self, stop_id: str, language: Optional[str] = None
    ) -> Optional[str]:
        """Get the stop name in the specified language if available, otherwise return the default name."""
        stop = self.stops.get(stop_id)
        if not stop:
            return None
        if language and stop.translations and language in stop.translations:
            return stop.translations[language]
        return stop.name

    def find_trips_between_stations(self, start_id: str, end_id: str) -> List[Route]:
        """Find all trips/services between two stations, including duplicates for different times."""
        routes = []

        # Group trips by route_id to check all variants
        trips_by_route = {}
        for trip_id, trip in self.trips.items():
            if trip.route_id not in trips_by_route:
                trips_by_route[trip.route_id] = []
            trips_by_route[trip.route_id].append(trip)

        # Check each route's trips
        for route_id, trips in trips_by_route.items():
            # Find the base route for this trip
            base_route = next((r for r in self.routes if r.route_id == route_id), None)
            if not base_route:
                continue

            for trip in trips:
                # Get stop times for this trip
                stop_times = sorted(trip.stop_times, key=lambda x: x.stop_sequence)
                if (
                    not stop_times
                ):  # If no stop times in trip object, get from dictionary
                    stop_times = [
                        StopTime(
                            trip_id=trip.id,
                            stop_id=st["stop_id"],
                            arrival_time=st["arrival_time"],
                            departure_time=st["departure_time"],
                            stop_sequence=st["stop_sequence"],
                        )
                        for st in sorted(
                            self.stop_times_dict.get(trip.id, []),
                            key=lambda x: x["stop_sequence"],
                        )
                    ]

                # Find positions of our target stops
                start_pos = next(
                    (i for i, st in enumerate(stop_times) if st.stop_id == start_id),
                    None,
                )
                end_pos = next(
                    (i for i, st in enumerate(stop_times) if st.stop_id == end_id), None
                )

                # Skip if either stop is not in this trip
                if start_pos is None or end_pos is None:
                    continue

                # Check if stops appear in sequence (either direction)
                if start_pos < end_pos:  # Forward direction
                    relevant_stops = stop_times[start_pos : end_pos + 1]
                elif start_pos > end_pos:  # Reverse direction
                    relevant_stops = stop_times[end_pos : start_pos + 1]
                    relevant_stops.reverse()  # Reverse to maintain from -> to order
                else:
                    continue  # Same stop

                # Create RouteStop objects
                route_stops = [
                    RouteStop(
                        stop=self.stops[st.stop_id],
                        arrival_time=st.arrival_time,
                        departure_time=st.departure_time,
                        stop_sequence=st.stop_sequence,
                    )
                    for st in relevant_stops
                ]

                # Get service days for this trip
                service_days = set()
                service_id = trip.service_id
                if service_id in self.calendars:
                    calendar = self.calendars[service_id]
                    if calendar.monday:
                        service_days.add("monday")
                    if calendar.tuesday:
                        service_days.add("tuesday")
                    if calendar.wednesday:
                        service_days.add("wednesday")
                    if calendar.thursday:
                        service_days.add("thursday")
                    if calendar.friday:
                        service_days.add("friday")
                    if calendar.saturday:
                        service_days.add("saturday")
                    if calendar.sunday:
                        service_days.add("sunday")
                else:
                    # If no regular calendar, get service days from calendar_dates
                    for cal_date in self.calendar_dates:
                        if (
                            cal_date.service_id == service_id
                            and cal_date.exception_type == 1
                        ):
                            service_days.add(cal_date.date.strftime("%A").lower())

                # Create a new route object with this trip's specific times
                route = Route(
                    route_id=base_route.route_id,
                    route_name=base_route.route_name,
                    trip_id=trip.id,
                    service_days=sorted(list(service_days)),
                    stops=route_stops,
                    shape=base_route.shape,
                    short_name=base_route.short_name,
                    long_name=base_route.long_name,
                    route_type=base_route.route_type,
                    color=base_route.color,
                    text_color=base_route.text_color,
                    agency_id=base_route.agency_id,
                    headsigns=base_route.headsigns,
                    service_ids=[
                        trip.service_id
                    ],  # Set service_ids to this trip's service_id
                    direction_id=trip.direction_id,
                    trips=[trip],  # Add the trip to the trips list
                    _feed=self,  # Set feed reference to self
                )
                # Calculate service days after initialization
                route.calculate_service_info()
                routes.append(route)

        return routes


def calculate_gtfs_hash(data_path: Path) -> str:
    """Calculate a hash of the GTFS files to determine if cache is valid."""
    hasher = hashlib.sha256()

    # List of files to include in the hash
    files_to_hash = ["stops.txt", "routes.txt", "trips.txt", "stop_times.txt"]
    calendar_files = ["calendar.txt", "calendar_dates.txt"]

    # Add whichever calendar file exists
    for cal_file in calendar_files:
        if (data_path / cal_file).exists():
            files_to_hash.append(cal_file)
            break

    # Optional files
    if (data_path / "shapes.txt").exists():
        files_to_hash.append("shapes.txt")

    # Calculate hash
    for filename in sorted(files_to_hash):
        file_path = data_path / filename
        if file_path.exists():
            hasher.update(file_path.read_bytes())

    return hasher.hexdigest()


def process_trip_batch(args):
    """Process a batch of trips in parallel."""
    (
        trips_batch,
        stops,
        shapes,
        routes_dict,
        calendar_dict,
        stop_times_dict,
        use_calendar_dates,
    ) = args

    routes = []
    for trip in trips_batch:
        route_id = trip["route_id"]
        trip_id = trip["trip_id"]

        # Get route name from the routes dictionary, handle NaN values
        route_info = routes_dict.get(route_id, {})
        route_name = route_info.get("route_long_name", "")
        if pd.isna(route_name):
            route_name = route_info.get("route_short_name", "") or f"Route {route_id}"

        # Get service days based on calendar type
        if use_calendar_dates:
            # For calendar_dates.txt, group by service_id and get unique dates
            service_dates = calendar_dict.get(trip["service_id"], [])
            # Convert dates to days of the week
            service_days = list(
                set(
                    datetime.strptime(date, "%Y%m%d").strftime("%A").lower()
                    for date in service_dates
                )
            )
        else:
            # For calendar.txt, use the existing logic
            service = calendar_dict.get(trip["service_id"], {})
            service_days = [
                day
                for day in [
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                ]
                if service.get(day, 0) == 1
            ]

        # Get stops for this trip from the dictionary
        trip_stops = stop_times_dict.get(trip_id, [])
        route_stops = []

        for stop_time in sorted(trip_stops, key=lambda x: x["stop_sequence"]):
            stop_id = str(stop_time["stop_id"])
            if stop_id in stops:
                route_stops.append(
                    RouteStop(
                        stop=stops[stop_id],
                        arrival_time=stop_time["arrival_time"],
                        departure_time=stop_time["departure_time"],
                        stop_sequence=stop_time["stop_sequence"],
                    )
                )

        # Get shape for this trip if available
        shape = None
        if "shape_id" in trip and trip["shape_id"] in shapes:
            shape = shapes[trip["shape_id"]]

        routes.append(
            Route(
                route_id=route_id,
                route_name=route_name,
                trip_id=trip_id,
                service_days=service_days,
                stops=route_stops,
                shape=shape,
                short_name=route_info.get("route_short_name"),
                color=route_info.get("route_color"),
                text_color=route_info.get("route_text_color"),
            )
        )

    return routes


def load_translations(gtfs_dir: str) -> dict[str, dict[str, str]]:
    """Load translations from translations.txt file.

    Handles both translation formats:
    1. Simple format: trans_id,translation,lang
    2. Table-based format: table_name,field_name,language,translation,record_id[,record_sub_id,field_value]

    Returns a dictionary mapping stop_id to a dictionary of language codes to translations.
    """
    translations_file = os.path.join(gtfs_dir, "translations.txt")
    if not os.path.exists(translations_file):
        logger.warning(f"No translations file found at {translations_file}")
        return {}

    # First, determine which format we're dealing with by reading the header
    with open(translations_file, "r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")

    # Create a mapping of stop IDs to translations
    translations = {}

    if "table_name" in header:  # Table-based format
        logger.info("Using table-based format for translations")

        # Read translations file
        df = pd.read_csv(translations_file)

        # Filter for stop name translations only
        stop_translations = df[
            (df["table_name"] == "stops") & (df["field_name"] == "stop_name")
        ]

        # Load stops.txt to get the mapping between stop_id and stop_name
        stops_df = pd.read_csv(os.path.join(gtfs_dir, "stops.txt"))

        # Create a mapping of stop_name to stop_id
        # Some stops might share the same name, so we need to handle that
        name_to_ids = {}
        for _, stop in stops_df.iterrows():
            stop_name = stop["stop_name"]
            stop_id = str(stop["stop_id"])
            if stop_name not in name_to_ids:
                name_to_ids[stop_name] = []
            name_to_ids[stop_name].append(stop_id)

        # Process each translation
        for _, row in stop_translations.iterrows():
            # Get the original stop name either from record_id or field_value
            original_name = row.get("field_value", row.get("record_id"))
            if pd.isna(original_name):
                continue

            # Find all stop IDs that match this name
            stop_ids = name_to_ids.get(original_name, [])
            if not stop_ids:
                continue

            # Add translation for each matching stop ID
            for stop_id in stop_ids:
                if stop_id not in translations:
                    translations[stop_id] = {}
                translations[stop_id][row["language"]] = row["translation"]

    else:  # Simple format (trans_id,translation,lang)
        logger.info("Using simple format for translations")

        # Read translations file
        df = pd.read_csv(translations_file)

        # Load stops.txt to get the mapping between stop_id and stop_name
        stops_df = pd.read_csv(os.path.join(gtfs_dir, "stops.txt"))

        # Create a mapping of stop names to translations
        name_translations = {}
        for _, row in df.iterrows():
            trans_id = row["trans_id"]
            if trans_id not in name_translations:
                name_translations[trans_id] = {}
            name_translations[trans_id][row["lang"]] = row["translation"]

        # Map translations to stop IDs
        for _, stop in stops_df.iterrows():
            stop_id = str(stop["stop_id"])
            stop_name = stop["stop_name"]
            if stop_name in name_translations:
                translations[stop_id] = name_translations[stop_name]

    logger.info(f"Created translations map with {len(translations)} entries")
    return translations


CACHE_VERSION = "3.0.0.0"


def serialize_gtfs_data(feed: "FlixbusFeed") -> bytes:
    """Serialize GTFS feed data using msgpack and lzma compression."""
    try:
        logger.info("Starting GTFS feed serialization")
        t00 = time.time()
        # Create a custom dictionary without _feed references
        data = {
            "stops": {stop_id: asdict(stop) for stop_id, stop in feed.stops.items()},
            "routes": [],
            "calendars": {
                cal_id: asdict(cal) for cal_id, cal in feed.calendars.items()
            },
            "calendar_dates": [asdict(cal_date) for cal_date in feed.calendar_dates],
            "trips": {trip_id: asdict(trip) for trip_id, trip in feed.trips.items()},
            "stop_times_dict": feed.stop_times_dict,
            "agencies": {
                agency_id: asdict(agency) for agency_id, agency in feed.agencies.items()
            },
        }

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
                "trip_ids": [trip.id for trip in route.trips],  # Store only trip IDs
                # Add service calendar fields
                "service_days_explicit": route.service_days_explicit,
                "calendar_dates_additions": [
                    d.isoformat() for d in route.calendar_dates_additions
                ],
                "calendar_dates_removals": [
                    d.isoformat() for d in route.calendar_dates_removals
                ],
                "valid_calendar_days": [
                    d.isoformat() for d in route.valid_calendar_days
                ],
                "service_calendar": route.service_calendar,
            }
            data["routes"].append(route_dict)

        # Convert datetime objects to ISO format strings
        if "calendars" in data:
            for calendar in data["calendars"].values():
                calendar["start_date"] = calendar["start_date"].isoformat()
                calendar["end_date"] = calendar["end_date"].isoformat()

        if "calendar_dates" in data:
            for cal_date in data["calendar_dates"]:
                cal_date["date"] = cal_date["date"].isoformat()

        # Pack with msgpack
        logger.info("Packing data with msgpack")
        t0 = time.time()
        packed_data = msgpack.packb(data, use_bin_type=True)
        logger.info(
            f"Packed data size: {bytes_to_mb(len(packed_data))} MB in {time.time() - t0:.2f}s"
        )

        # Compress with lzma
        logger.info("Compressing data with lzma")
        t0 = time.time()
        compressed_data = lzma.compress(
            packed_data,
            format=lzma.FORMAT_XZ,
            filters=[{"id": lzma.FILTER_LZMA2, "preset": 6}],
        )
        logger.info(
            f"Compressed data size:{bytes_to_mb(len(packed_data))} MB --> {bytes_to_mb(len(compressed_data))} MB in {time.time() - t0:.2f}s"
        )
        logger.info(
            f"GTFS feed serialization completed successfully in {time.time() - t00:.2f}s"
        )

        return compressed_data
    except Exception as e:
        logger.error(f"Error serializing GTFS data: {e}", exc_info=True)
        raise


def deserialize_gtfs_data(data: bytes) -> "FlixbusFeed":
    """Deserialize GTFS feed data from msgpack and lzma compression."""
    try:
        start_time = time.time()
        logger.info("Starting GTFS feed deserialization")

        # Decompress with lzma
        t0 = time.time()
        decompressed_data = lzma.decompress(data)
        logger.info(
            f"LZMA decompression: {bytes_to_mb(len(data))} MB -> {bytes_to_mb(len(decompressed_data))} MB in {time.time() - t0:.2f}s"
        )

        # Unpack with msgpack
        logger.info("Unpacking data with msgpack")
        t0 = time.time()
        raw_data = msgpack.unpackb(decompressed_data, raw=False)
        logger.info(f"Msgpack unpacking took {time.time() - t0:.2f} seconds")

        # Convert back to objects
        logger.info("Converting back to objects")
        t0 = time.time()

        # Convert stops
        stops = {}
        for stop_id, stop_data in raw_data["stops"].items():
            stops[stop_id] = Stop(**stop_data)

        # Convert calendars
        calendars = {}
        if "calendars" in raw_data:
            for cal_id, cal_data in raw_data["calendars"].items():
                cal_data["start_date"] = datetime.fromisoformat(cal_data["start_date"])
                cal_data["end_date"] = datetime.fromisoformat(cal_data["end_date"])
                calendars[cal_id] = Calendar(**cal_data)

        # Convert calendar dates
        calendar_dates = []
        if "calendar_dates" in raw_data:
            for cal_date in raw_data["calendar_dates"]:
                cal_date["date"] = datetime.fromisoformat(cal_date["date"])
                calendar_dates.append(CalendarDate(**cal_date))

        # Convert trips
        trips = {}
        if "trips" in raw_data:
            for trip_id, trip_data in raw_data["trips"].items():
                # Convert stop times
                stop_times = []
                for stop_time_data in trip_data.get("stop_times", []):
                    stop_time_data["trip_id"] = trip_id  # Add trip_id to the data
                    stop_times.append(StopTime(**stop_time_data))
                trip_data["stop_times"] = stop_times
                trips[trip_id] = Trip(**trip_data)

        # Convert agencies
        agencies = {}
        if "agencies" in raw_data:
            for agency_id, agency_data in raw_data["agencies"].items():
                agencies[agency_id] = Agency(**agency_data)

        # Convert routes
        routes = []
        for route_data in raw_data["routes"]:
            # Convert route stops
            route_stops = [
                RouteStop(
                    stop=stops[stop_data["stop"]["id"]],
                    arrival_time=stop_data["arrival_time"],
                    departure_time=stop_data["departure_time"],
                    stop_sequence=stop_data["stop_sequence"],
                )
                for stop_data in route_data["stops"]
            ]
            route_data["stops"] = route_stops

            # Convert shape if present
            if route_data.get("shape"):
                route_data["shape"] = Shape(**route_data["shape"])

            # Add trips to route
            route_trips = []
            for trip_id in route_data.get("trip_ids", []):
                if trip_id in trips:
                    route_trips.append(trips[trip_id])
            route_data["trips"] = route_trips

            # Remove trip_ids as it's not a field in the Route class
            route_data.pop("trip_ids", None)

            # Convert datetime fields back from ISO format
            if "calendar_dates_additions" in route_data:
                route_data["calendar_dates_additions"] = [
                    datetime.fromisoformat(d)
                    for d in route_data["calendar_dates_additions"]
                ]
            if "calendar_dates_removals" in route_data:
                route_data["calendar_dates_removals"] = [
                    datetime.fromisoformat(d)
                    for d in route_data["calendar_dates_removals"]
                ]
            if "valid_calendar_days" in route_data:
                route_data["valid_calendar_days"] = [
                    datetime.fromisoformat(d) for d in route_data["valid_calendar_days"]
                ]

            routes.append(Route(**route_data))

        # Create feed instance
        feed = FlixbusFeed(
            stops=stops,
            routes=routes,
            calendars=calendars,
            calendar_dates=calendar_dates,
            trips=trips,
            stop_times_dict=raw_data["stop_times_dict"],
            agencies=agencies,
        )

        logger.info(
            f"Deserialization completed in {time.time() - start_time:.2f} seconds"
        )
        return feed
    except Exception as e:
        logger.error(f"Error deserializing GTFS data: {e}", exc_info=True)
        raise


def load_feed(
    data_dir: str | Path = None, target_stops: Set[str] = None
) -> FlixbusFeed:
    """
    Load GTFS feed from the specified directory.
    If target_stops is provided, only loads routes that contain those stops.

    Args:
        data_dir: Path to the GTFS data directory. Can be either a string or Path object.
        target_stops: Optional set of stop IDs to filter routes by.

    Returns:
        FlixbusFeed object containing the loaded GTFS data.

    Raises:
        ValueError: If data_dir is None or does not exist.
    """
    start_time = time.time()
    if not data_dir:
        raise ValueError("No data directory provided to load_feed()")
    
    # Convert data_dir to Path if it's a string
    data_path = Path(data_dir)

    if not data_path.exists():
        raise ValueError(f"Data directory does not exist: {data_path}")

    logger.info(f"Loading GTFS feed from: {data_path}")

    # Check if we have a valid cache
    cache_file = data_path / ".gtfs_cache"
    hash_file = data_path / ".gtfs_cache_hash"
    current_hash = f"{CACHE_VERSION}_{calculate_gtfs_hash(data_path)}"

    if cache_file.exists() and hash_file.exists():
        stored_hash = hash_file.read_text().strip()
        if stored_hash == current_hash:
            logger.info(f"Loading from cache... {current_hash}")
            try:
                with open(cache_file, "rb") as f:
                    return deserialize_gtfs_data(f.read())
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
                # Delete corrupted cache files
                try:
                    cache_file.unlink()
                    hash_file.unlink()
                except:
                    pass

    # Load agencies first
    t0 = time.time()
    logger.info("Loading agencies...")
    agencies = {}
    try:
        agencies_df = pd.read_csv(
            data_path / "agency.txt",
            dtype={
                "agency_id": str,
                "agency_name": str,
                "agency_url": str,
                "agency_timezone": str,
                # Optional fields
                "agency_lang": str,
                "agency_phone": str,
                "agency_fare_url": str,
                "agency_email": str,
            },
        )
        for _, row in agencies_df.iterrows():
            agency = Agency(
                agency_id=str(row["agency_id"]),
                agency_name=row["agency_name"],
                agency_url=row["agency_url"],
                agency_timezone=row["agency_timezone"],
                agency_lang=(
                    row["agency_lang"]
                    if "agency_lang" in row and pd.notna(row["agency_lang"])
                    else None
                ),
                agency_phone=(
                    row["agency_phone"]
                    if "agency_phone" in row and pd.notna(row["agency_phone"])
                    else None
                ),
                agency_fare_url=(
                    row["agency_fare_url"]
                    if "agency_fare_url" in row and pd.notna(row["agency_fare_url"])
                    else None
                ),
                agency_email=(
                    row["agency_email"]
                    if "agency_email" in row and pd.notna(row["agency_email"])
                    else None
                ),
            )
            agencies[agency.agency_id] = agency
        logger.info(
            f"Loaded {len(agencies)} agencies in {time.time() - t0:.2f} seconds"
        )
    except FileNotFoundError:
        logger.warning("No agency.txt found")

    # Calculate optimal chunk size based on available memory
    available_memory = psutil.virtual_memory().available
    estimated_row_size = 200  # bytes per row
    optimal_chunk_size = min(
        100000,  # max chunk size
        max(1000, available_memory // (estimated_row_size * 2)),  # ensure buffer
    )
    logger.info(f"Using chunk size of {optimal_chunk_size} based on available memory")

    # Load translations first
    t0 = time.time()
    translations = load_translations(data_path)
    logger.info(f"Loaded translations in {time.time() - t0:.2f} seconds")

    # Load stops
    t0 = time.time()
    logger.info("Loading stops...")
    stops = {}
    for chunk in pd.read_csv(
        data_path / "stops.txt",
        chunksize=optimal_chunk_size,
        dtype={"stop_id": str, "stop_name": str, "stop_lat": float, "stop_lon": float},
    ):
        for _, row in chunk.iterrows():
            stop = Stop(
                id=str(row["stop_id"]),
                name=row["stop_name"],
                lat=row["stop_lat"],
                lon=row["stop_lon"],
                translations=translations.get(str(row["stop_id"]), {}),
                location_type=int(row["location_type"]) if "location_type" in row and pd.notna(row["location_type"]) else None,
                parent_station=str(row["parent_station"]) if "parent_station" in row and pd.notna(row["parent_station"]) else None,
                platform_code=str(row["platform_code"]) if "platform_code" in row and pd.notna(row["platform_code"]) else None,
            )
            stops[stop.id] = stop
            # if stop.translations:
            #     logger.info(
            #         f"Stop {stop.id} ({stop.name}) has translations: {stop.translations}"
            #     )
    logger.info(f"Loaded {len(stops)} stops in {time.time() - t0:.2f} seconds")

    # Load shapes if available
    t0 = time.time()
    shapes = {}
    try:
        logger.info("Loading shapes...")
        shapes_df = pd.read_csv(
            data_path / "shapes.txt",
            dtype={
                "shape_id": str,
                "shape_pt_lat": float,
                "shape_pt_lon": float,
                "shape_pt_sequence": int,
                # Optional fields
                "shape_dist_traveled": float,
            },
        )
        # Group by shape_id and sort by sequence
        for shape_id, group in shapes_df.groupby("shape_id"):
            sorted_points = group.sort_values("shape_pt_sequence")[
                ["shape_pt_lat", "shape_pt_lon"]
            ].values.tolist()
            shapes[shape_id] = Shape(shape_id=str(shape_id), points=sorted_points)
        logger.info(f"Loaded {len(shapes)} shapes in {time.time() - t0:.2f} seconds")
    except FileNotFoundError:
        logger.warning("No shapes.txt found, routes will use stop coordinates")

    # Load routes and other data
    t0 = time.time()
    logger.info("Loading routes, trips, stop times, and calendar...")
    routes_df = pd.read_csv(
        data_path / "routes.txt",
        dtype={
            "route_id": str,
            "route_long_name": str,
            "route_short_name": str,
            "route_color": str,
            "route_text_color": str,
            "route_type": int,
            # Optional fields
            "agency_id": str,
            "route_desc": str,
            "route_url": str,
            "route_sort_order": "Int64",  # Nullable integer for route ordering
            "continuous_pickup": "Int64",  # Nullable integer enum (0-3)
            "continuous_drop_off": "Int64",  # Nullable integer enum (0-3)
        },
    )

    # Convert routes to dictionary early to free memory
    routes_dict = {
        row.route_id: {
            "route_long_name": row.route_long_name,
            "route_short_name": row.route_short_name,
            "color": getattr(row, "route_color", None),
            "text_color": getattr(row, "route_text_color", None),
            "route_type": int(row.route_type),
            "agency_id": (
                str(row.agency_id)
                if hasattr(row, "agency_id") and pd.notna(row.agency_id)
                else None
            ),
            "route_desc": (
                str(row.route_desc)
                if hasattr(row, "route_desc") and pd.notna(row.route_desc)
                else None
            ),
            "route_url": (
                str(row.route_url)
                if hasattr(row, "route_url") and pd.notna(row.route_url)
                else None
            ),
            "route_sort_order": (
                int(row.route_sort_order)
                if hasattr(row, "route_sort_order") and pd.notna(row.route_sort_order)
                else None
            ),
            "continuous_pickup": (
                int(row.continuous_pickup)
                if hasattr(row, "continuous_pickup") and pd.notna(row.continuous_pickup)
                else None
            ),
            "continuous_drop_off": (
                int(row.continuous_drop_off)
                if hasattr(row, "continuous_drop_off")
                and pd.notna(row.continuous_drop_off)
                else None
            ),
        }
        for row in routes_df.itertuples()
    }
    del routes_df
    logger.info(
        f"Loaded routes, trips, stop times, and calendar in {time.time() - t0:.2f} seconds"
    )
    use_low_memory = check_memory_for_file(data_path / "trips.txt")
    # Load trips with correct dtypes
    trips_df = pd.read_csv(
        data_path / "trips.txt",
        dtype={
            "route_id": str,
            "service_id": str,
            "trip_id": str,
            # Optional fields
            "trip_headsign": str,
            "trip_short_name": str,
            "direction_id": "Int64",  # Nullable integer (0 or 1)
            "block_id": str,
            "shape_id": str,
            "wheelchair_accessible": "Int64",  # Nullable integer enum (0-2)
            "bikes_allowed": "Int64",  # Nullable integer enum (0-2)
        },
        low_memory=use_low_memory,
    )

    # Load stop times in chunks to handle large files
    t0 = time.time()
    logger.info("Loading stop times...")
    chunk_size = 100000
    stop_times_dict = {}

    use_low_memory = check_memory_for_file(data_path / "stop_times.txt")

    for chunk in pd.read_csv(
        data_path / "stop_times.txt",
        chunksize=chunk_size,
        dtype={
            "trip_id": str,
            "stop_id": str,
            "arrival_time": str,
            "departure_time": str,
            "stop_sequence": int,
            # Optional fields
            "stop_headsign": str,
            "pickup_type": "Int64",  # Nullable integer enum (0-3)
            "drop_off_type": "Int64",  # Nullable integer enum (0-3)
            "continuous_pickup": "Int64",  # Nullable integer enum (0-3)
            "continuous_drop_off": "Int64",  # Nullable integer enum (0-3)
            "shape_dist_traveled": float,  # Non-negative float
            "timepoint": "Int64",  # Nullable integer enum (0-1)
            "stop_time_desc": str,
        },
        low_memory=use_low_memory,
    ):
        for _, row in chunk.iterrows():
            if row.trip_id not in stop_times_dict:
                stop_times_dict[row.trip_id] = []
            stop_times_dict[row.trip_id].append(
                {
                    "stop_id": str(row.stop_id),
                    "arrival_time": row.arrival_time,
                    "departure_time": row.departure_time,
                    "stop_sequence": row.stop_sequence,
                }
            )
    logger.info(f"Loaded stop times in {time.time() - t0:.2f} seconds")

    # Try to load calendar.txt first, fall back to calendar_dates.txt
    t0 = time.time()
    try:
        logger.info("Loading calendar.txt...")
        calendar_df = pd.read_csv(
            data_path / "calendar.txt",
            dtype={
                "service_id": str,
                "monday": int,
                "tuesday": int,
                "wednesday": int,
                "thursday": int,
                "friday": int,
                "saturday": int,
                "sunday": int,
                "start_date": str,
                "end_date": str,
            },
        )
        use_calendar_dates = False
        calendars = {}
        logger.info(f"Found {len(calendar_df)} entries in calendar.txt")
        for _, row in calendar_df.iterrows():
            service_id = str(row["service_id"])
            calendars[service_id] = Calendar(
                service_id=service_id,
                monday=bool(row["monday"]),
                tuesday=bool(row["tuesday"]),
                wednesday=bool(row["wednesday"]),
                thursday=bool(row["thursday"]),
                friday=bool(row["friday"]),
                saturday=bool(row["saturday"]),
                sunday=bool(row["sunday"]),
                start_date=datetime.strptime(str(row["start_date"]), "%Y%m%d"),
                end_date=datetime.strptime(str(row["end_date"]), "%Y%m%d"),
            )
            # logger.info(
            #     f"Service {service_id}: M={row['monday']} T={row['tuesday']} W={row['wednesday']} T={row['thursday']} F={row['friday']} S={row['saturday']} S={row['sunday']}"
            # )
        del calendar_df
        logger.info(
            f"Loaded calendar.txt with {len(calendars)} services in {time.time() - t0:.2f} seconds"
        )
    except FileNotFoundError:
        logger.info("calendar.txt not found, trying calendar_dates.txt...")
        calendar_df = pd.read_csv(
            data_path / "calendar_dates.txt",
            dtype={"service_id": str, "date": str, "exception_type": int},
        )
        use_calendar_dates = True
        calendars = {}
        calendar_dates = []
        logger.info(f"Found {len(calendar_df)} entries in calendar_dates.txt")
        for _, row in calendar_df.iterrows():
            service_id = str(row["service_id"])
            date = datetime.strptime(str(row["date"]), "%Y%m%d")
            exception_type = int(row["exception_type"])
            calendar_dates.append(
                CalendarDate(
                    service_id=service_id,
                    date=date,
                    exception_type=exception_type,
                )
            )
            # logger.info(
            #     f"Service {service_id}: Date={date.strftime('%Y-%m-%d')} Type={exception_type}"
            # )
        del calendar_df
        logger.info(
            f"Loaded calendar_dates.txt with {len(calendar_dates)} exceptions in {time.time() - t0:.2f} seconds"
        )

    # Load calendar_dates.txt for exceptions if we have regular calendars
    if not use_calendar_dates:
        t0 = time.time()
        try:
            logger.info("Loading calendar_dates.txt for exceptions...")
            calendar_dates_df = pd.read_csv(
                data_path / "calendar_dates.txt",
                dtype={"service_id": str, "date": str, "exception_type": int},
            )
            calendar_dates = []
            logger.info(f"Found {len(calendar_dates_df)} exception entries")
            for _, row in calendar_dates_df.iterrows():
                service_id = str(row["service_id"])
                date = datetime.strptime(str(row["date"]), "%Y%m%d")
                exception_type = int(row["exception_type"])
                calendar_dates.append(
                    CalendarDate(
                        service_id=service_id,
                        date=date,
                        exception_type=exception_type,
                    )
                )
                # logger.info(
                #     f"Exception for service {service_id}: Date={date.strftime('%Y-%m-%d')} Type={exception_type}"
                # )
            del calendar_dates_df
            logger.info(
                f"Loaded calendar_dates.txt for exceptions with {len(calendar_dates)} entries in {time.time() - t0:.2f} seconds"
            )
        except FileNotFoundError:
            logger.info("No calendar_dates.txt found")
            calendar_dates = []

    # If we have target stops, pre-filter the trips that contain them
    if target_stops:
        t0 = time.time()
        logger.info(f"Pre-filtering trips containing stops: {target_stops}")
        # Get trips that contain any of our target stops
        relevant_trips = set()
        for trip_id, stops_list in stop_times_dict.items():
            if any(str(stop["stop_id"]) in target_stops for stop in stops_list):
                relevant_trips.add(trip_id)
        trips_df = trips_df[trips_df["trip_id"].isin(relevant_trips)]
        logger.info(f"Found {len(trips_df)} relevant trips")
        logger.info(f"Pre-filtered trips in {time.time() - t0:.2f} seconds")

    # Convert trips DataFrame to dictionary
    t0 = time.time()
    trips = {}
    # First, group trips by route_id to collect all service_ids and headsigns
    route_service_ids = {}  # route_id -> set of service_ids
    route_headsigns = {}  # route_id -> dict of direction_id -> headsign
    for _, row in trips_df.iterrows():
        trip_id = str(row["trip_id"])
        route_id = str(row["route_id"])
        service_id = str(row["service_id"])
        direction_id = str(getattr(row, "direction_id", "0"))
        headsign = getattr(row, "trip_headsign", None)

        # Collect service IDs for each route
        if route_id not in route_service_ids:
            route_service_ids[route_id] = set()
        route_service_ids[route_id].add(service_id)

        # Collect headsigns for each route direction
        if headsign:
            if route_id not in route_headsigns:
                route_headsigns[route_id] = {}
            route_headsigns[route_id][direction_id] = headsign

        # Store trip information
        trips[trip_id] = Trip(
            id=trip_id,
            route_id=route_id,
            service_id=service_id,
            headsign=headsign,
            direction_id=direction_id,
            shape_id=(
                str(row["shape_id"])
                if "shape_id" in row and pd.notna(row["shape_id"])
                else None
            ),
        )
    del trips_df
    logger.info(f"Processed {len(trips)} trips in {time.time() - t0:.2f} seconds")

    # Process routes
    t0 = time.time()
    routes = []
    for route_id, route_info in routes_dict.items():
        # Get all trips for this route
        route_trips = [trip for trip in trips.values() if trip.route_id == route_id]
        if not route_trips:
            continue

        # Group trips by direction
        trips_by_direction = {}
        for trip in route_trips:
            direction = str(trip.direction_id) if trip.direction_id is not None else "0"
            if direction not in trips_by_direction:
                trips_by_direction[direction] = []
            trips_by_direction[direction].append(trip)

        # Create a route object for each direction
        for direction, direction_trips in trips_by_direction.items():
            # Use the first trip of this direction as a reference
            reference_trip = direction_trips[0]

            # Get stop times for this trip
            stop_times = stop_times_dict.get(reference_trip.id, [])
            if not stop_times:
                continue

            # Sort stop times by sequence
            stop_times.sort(key=lambda x: x["stop_sequence"])

            # Create RouteStop objects
            route_stops = []
            for stop_time in stop_times:
                stop_id = stop_time["stop_id"]
                if stop_id not in stops:
                    continue
                route_stops.append(
                    RouteStop(
                        stop=stops[stop_id],
                        arrival_time=stop_time["arrival_time"],
                        departure_time=stop_time["departure_time"],
                        stop_sequence=stop_time["stop_sequence"],
                    )
                )

            # Calculate service days based on all service IDs for this route
            service_days = set()
            for service_id in route_service_ids[route_id]:
                if service_id in calendars:
                    calendar = calendars[service_id]
                    if calendar.monday:
                        service_days.add("monday")
                    if calendar.tuesday:
                        service_days.add("tuesday")
                    if calendar.wednesday:
                        service_days.add("wednesday")
                    if calendar.thursday:
                        service_days.add("thursday")
                    if calendar.friday:
                        service_days.add("friday")
                    if calendar.saturday:
                        service_days.add("saturday")
                    if calendar.sunday:
                        service_days.add("sunday")

            # Create the route object
            route = Route(
                route_id=route_id,
                route_name=route_info["route_long_name"] or f"Route {route_id}",
                trip_id=reference_trip.id,
                service_days=sorted(list(service_days)),
                stops=route_stops,
                shape=(
                    shapes.get(reference_trip.shape_id)
                    if reference_trip.shape_id
                    else None
                ),
                short_name=route_info["route_short_name"],
                long_name=route_info["route_long_name"],
                color=route_info["color"],
                text_color=route_info["text_color"],
                headsigns=route_headsigns.get(route_id, {}),
                service_ids=list(route_service_ids[route_id]),
                direction_id=direction,
                route_type=route_info["route_type"],
                agency_id=route_info["agency_id"],
                route_desc=route_info["route_desc"],
                route_url=route_info["route_url"],
                route_sort_order=route_info["route_sort_order"],
                continuous_pickup=route_info["continuous_pickup"],
                continuous_drop_off=route_info["continuous_drop_off"],
                trips=direction_trips,  # Add all trips for this direction
            )
            routes.append(route)

    logger.info(f"Created {len(routes)} routes in {time.time() - t0:.2f} seconds")

    # Create feed object
    t0 = time.time()
    feed = FlixbusFeed(
        stops=stops,
        routes=routes,
        calendars=calendars,
        calendar_dates=calendar_dates,
        trips=trips,
        stop_times_dict=stop_times_dict,
        agencies=agencies,
    )
    logger.info(f"Created feed object in {time.time() - t0:.2f} seconds")

    # Calculate service info for all routes
    t0 = time.time()
    logger.info("Calculating service info for all routes...")
    for route in feed.routes:
        route.calculate_service_info()
    logger.info(
        f"Calculated service info for {len(feed.routes)} routes in {time.time() - t0:.2f} seconds"
    )

    # Save to cache
    t0 = time.time()
    logger.info(f"Saving to cache... with hash {current_hash}")
    try:
        serialized_data = serialize_gtfs_data(feed)
        with open(cache_file, "wb") as f:
            f.write(serialized_data)
        hash_file.write_text(current_hash)
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")
        # Clean up failed cache files
        try:
            cache_file.unlink()
            hash_file.unlink()
        except:
            pass
    logger.info(f"Saved to cache in {time.time() - t0:.2f} seconds")

    logger.info(f"Total time taken: {time.time() - start_time:.2f} seconds")
    return feed
