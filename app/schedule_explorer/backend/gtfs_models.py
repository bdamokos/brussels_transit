"""
Data models for GTFS static data.
These dataclasses represent the core GTFS entities used in both the original and Parquet implementations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import logging
from .models import BoundingBox, StationResponse, Location

logger = logging.getLogger("schedule_explorer.gtfs_models")

def calculate_minutes_until(target_time: str, current_time: str) -> int:
    """Calculate minutes between two times in HH:MM:SS format.
    
    Args:
        target_time: Target time in HH:MM:SS format
        current_time: Current time in HH:MM:SS format
        
    Returns:
        Number of minutes between the times
    """
    def parse_time(time_str: str) -> datetime:
        hours, minutes, seconds = map(int, time_str.split(":"))
        base_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
        return base_date + timedelta(hours=hours, minutes=minutes, seconds=seconds)

    target = parse_time(target_time)
    current = parse_time(current_time)

    # Handle overnight routes
    if target < current:
        target += timedelta(days=1)

    minutes = int((target - current).total_seconds() / 60)
    return max(0, minutes)  # Don't return negative minutes

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
    translations: Dict[str, str] = field(default_factory=dict)  # language -> translated name
    location_type: Optional[int] = None
    parent_station: Optional[str] = None
    platform_code: Optional[str] = None
    timezone: Optional[str] = None

@dataclass
class RouteStop:
    """
    Represents a stop within a route, including arrival and departure times.
    """
    stop: Stop
    arrival_time: str
    departure_time: str
    stop_sequence: int

@dataclass
class Shape:
    """
    Represents a shape from shapes.txt
    """
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
    Represents a calendar date exception from calendar_dates.txt
    Both: service_id, date, exception_type
    """
    service_id: str
    date: datetime
    exception_type: int  # 1 = service added, 2 = service removed

@dataclass
class Route:
    """
    Represents a route from routes.txt with its stops and service information.
    """
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
    service_ids: List[str] = field(default_factory=list)  # List of all service IDs for this route
    direction_id: Optional[str] = None  # Direction of this route variant
    route_desc: Optional[str] = None  # Description of the route
    route_url: Optional[str] = None  # URL of a web page about the route
    route_sort_order: Optional[int] = None  # Order in which routes should be displayed
    continuous_pickup: Optional[int] = None  # Flag stop behavior for pickup (0-3)
    continuous_drop_off: Optional[int] = None  # Flag stop behavior for drop-off (0-3)
    trips: List[Trip] = field(default_factory=list)  # List of trips for this route
    _feed: Optional["FlixbusFeed"] = field(default=None, repr=False, compare=False, hash=False)
    # New debug and service calendar fields
    service_days_explicit: List[str] = field(default_factory=list)  # Days from calendar.txt
    calendar_dates_additions: List[datetime] = field(default_factory=list)  # Days added via exceptions
    calendar_dates_removals: List[datetime] = field(default_factory=list)  # Days removed via exceptions
    valid_calendar_days: List[datetime] = field(default_factory=list)  # All valid service days
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
        if not self.trips or not self._feed:
            logger.error(f"Route {self.route_id}: No trips or feed available")
            return

        # Get unique service IDs from all trips
        service_ids = {trip.service_id for trip in self.trips}

        # Calculate service_days_explicit from calendar.txt
        self.service_days_explicit = []
        has_regular_calendar = False
        has_calendar_entries = False
        for service_id in service_ids:
            if service_id in self._feed.calendars:
                has_calendar_entries = True
                calendar = self._feed.calendars[service_id]
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

        self.service_days_explicit = sorted(list(set(self.service_days_explicit)))

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

        # Calculate valid_calendar_days
        self.valid_calendar_days = []
        if has_regular_calendar:
            # Get the feed's validity window from calendar.txt
            start_dates = []
            end_dates = []
            for service_id in service_ids:
                if service_id in self._feed.calendars:
                    calendar = self._feed.calendars[service_id]
                    start_dates.append(calendar.start_date)
                    end_dates.append(calendar.end_date)

            if start_dates and end_dates:
                start_date = min(start_dates)
                end_date = max(end_dates)

                # For each day in the window, check if the route operates
                current_date = start_date
                while current_date <= end_date:
                    if self.operates_on(current_date):
                        self.valid_calendar_days.append(current_date)
                    current_date += timedelta(days=1)
        else:
            if self.calendar_dates_additions:
                self.valid_calendar_days = sorted(self.calendar_dates_additions)

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
        else:
            self.service_calendar = None

        # Update service_days based on valid_calendar_days
        if self.valid_calendar_days:
            weekdays = {d.strftime("%A").lower() for d in self.valid_calendar_days}
            self.service_days = sorted(list(weekdays))
        else:
            logger.error(
                f"Route {self.route_id}: No service_days (no valid calendar days)"
            )

        # If we have calendar_dates_additions but no service_days yet, calculate them from the additions
        if not self.service_days and self.calendar_dates_additions:
            weekdays = {d.strftime("%A").lower() for d in self.calendar_dates_additions}
            self.service_days = sorted(list(weekdays))

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
                        break
                    elif cal_date.exception_type == 2:  # Service removed
                        operates = False
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
            elif not has_exception and not self._feed.calendars:
                # If we only have calendar_dates.txt, treat no exception as not operating
                operates = False

            # If any service ID operates on this date, the route operates
            if operates:
                return True

        return False

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

@dataclass
class FlixbusFeed:
    """
    Represents a GTFS feed with all its components.
    """
    stops: Dict[str, Stop]
    routes: List[Route]
    translations: Dict[str, Dict[str, str]]
    trips: Dict[str, Trip] = field(default_factory=dict)
    stop_times_dict: Dict[str, List[Dict]] = field(default_factory=dict)
    calendars: Dict[str, Calendar] = field(default_factory=dict)
    calendar_dates: List[CalendarDate] = field(default_factory=list)
    agencies: Dict[str, Agency] = field(default_factory=dict)  # agency_id -> Agency
    _feed: Optional["FlixbusFeed"] = field(default=None, repr=False)

    def __post_init__(self):
        """Set feed reference on all routes"""
        for route in self.routes:
            route._feed = self

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

        return routes

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

    def get_waiting_times(self, stop_id: str, route_id: Optional[str] = None, limit: int = 2) -> Dict:
        """Get waiting times for a stop, optionally filtered by route.
        
        Args:
            stop_id: The ID of the stop to get waiting times for
            route_id: Optional route ID to filter by
            limit: Maximum number of waiting times to return per route/destination
            
        Returns:
            Dictionary with waiting times information
        """
        if stop_id not in self.stops:
            logger.warning(f"Stop {stop_id} not found")
            return {"stops_data": {}}

        stop = self.stops[stop_id]
        formatted_data = {
            "stops_data": {
                stop_id: {
                    "name": stop.name,
                    "coordinates": {"lat": stop.lat, "lon": stop.lon},
                    "translations": stop.translations,
                    "lines": {}
                }
            }
        }

        # Get current time in local timezone
        agency_timezone = None
        if self.agencies:
            # Get the first agency's timezone (all agencies inside a GTFS dataset must have the same timezone)
            agency_timezone = next(iter(self.agencies.values())).agency_timezone

        # If no agency timezone found, use UTC
        if not agency_timezone:
            agency_timezone = "UTC"

        now = datetime.now(timezone.utc)
        now_local = now.astimezone(ZoneInfo(agency_timezone))
        current_time = now_local.strftime("%H:%M:%S")

        # Find all routes that serve this stop
        for route in self.routes:
            # Skip if route_id is specified and doesn't match
            if route_id and route_id != route.route_id:
                continue

            # Check if this route serves our stop
            route_stop = route.get_stop_by_id(stop_id)
            if not route_stop:
                continue

            # Get the route's terminus (last stop)
            terminus = route.stops[-1].stop if route.stops else None
            if not terminus:
                continue

            # Initialize route in formatted_data if needed
            if route.route_id not in formatted_data["stops_data"][stop_id]["lines"]:
                formatted_data["stops_data"][stop_id]["lines"][route.route_id] = {
                    "_metadata": [
                        {
                            "route_desc": route.route_name,
                            "route_short_name": route.short_name or route.route_id
                        }
                    ]
                }

            # Get the headsign (destination)
            headsign = terminus.name

            # Initialize headsign in formatted_data if needed
            if headsign not in formatted_data["stops_data"][stop_id]["lines"][route.route_id]:
                formatted_data["stops_data"][stop_id]["lines"][route.route_id][headsign] = []

            # Calculate waiting time
            arrival_time = route_stop.arrival_time
            minutes = calculate_minutes_until(arrival_time, current_time)

            # Add waiting time info
            formatted_data["stops_data"][stop_id]["lines"][route.route_id][headsign].append({
                "is_realtime": False,
                "provider": "gtfs",
                "scheduled_time": arrival_time,
                "scheduled_minutes": f"{minutes}'"
            })

            # Sort waiting times and limit to requested number
            formatted_data["stops_data"][stop_id]["lines"][route.route_id][headsign].sort(
                key=lambda x: int(x["scheduled_minutes"].rstrip("'"))
            )
            formatted_data["stops_data"][stop_id]["lines"][route.route_id][headsign] = \
                formatted_data["stops_data"][stop_id]["lines"][route.route_id][headsign][:limit]

        return formatted_data

    def get_stops_in_bbox(self, bbox: BoundingBox, count_only: bool = False) -> Union[List[StationResponse], Dict[str, int]]:
        """Get all stops within a bounding box.
        
        Args:
            bbox: BoundingBox object with min/max lat/lon
            count_only: If True, only return the count of stops
            
        Returns:
            If count_only is True, returns Dict with count
            Otherwise returns List of StationResponse objects
        """
        # Filter stops within the bounding box
        stops_in_bbox = []
        for stop_id, stop in self.stops.items():
            if (bbox.min_lat <= stop.lat <= bbox.max_lat) and (
                bbox.min_lon <= stop.lon <= bbox.max_lon
            ):
                # If we only need the count, just add the ID
                if count_only:
                    stops_in_bbox.append(stop_id)
                    continue

                # Create StationResponse object
                stops_in_bbox.append(
                    StationResponse(
                        id=stop_id,
                        name=stop.name,
                        location=Location(lat=stop.lat, lon=stop.lon),
                        translations=stop.translations,
                        routes=[]  # Routes will be added by the API endpoint
                    )
                )

        if count_only:
            return {"count": len(stops_in_bbox)}

        return stops_in_bbox 