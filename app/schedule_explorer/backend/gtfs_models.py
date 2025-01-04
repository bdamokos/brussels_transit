"""
Data models for GTFS static data.
These dataclasses represent the core GTFS entities used in both the original and Parquet implementations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

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