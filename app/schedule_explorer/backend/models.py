from pydantic import BaseModel, validator, field_validator
from typing import List, Optional, Dict
from datetime import time, datetime


class DatasetValidation(BaseModel):
    total_error: int
    total_warning: int
    total_info: int


class DatasetInfo(BaseModel):
    id: str
    downloaded_at: str
    hash: str
    hosted_url: str
    validation_report: DatasetValidation


class BoundingBox(BaseModel):
    """A geographical bounding box defined by its corners."""

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @field_validator("min_lat", "max_lat")
    def validate_latitude(cls, v):
        if not -90 <= v <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("min_lon", "max_lon")
    def validate_longitude(cls, v):
        if not -180 <= v <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v

    @field_validator("max_lat")
    def validate_lat_bounds(cls, v, values):
        if "min_lat" in values.data and v < values.data["min_lat"]:
            raise ValueError("max_lat must be greater than or equal to min_lat")
        return v

    @field_validator("max_lon")
    def validate_lon_bounds(cls, v, values):
        if "min_lon" in values.data and v < values.data["min_lon"]:
            raise ValueError("max_lon must be greater than or equal to min_lon")
        return v


class Provider(BaseModel):
    id: str  # The long ID generated from the provider's name and the dataset_id (raw_id) (e.g. "Budapest_Transport_mdb-990")
    raw_id: str  # The short ID (e.g. "mdb-990") - the raw ID is the dataset_id in the Mobility Database
    provider: str  # The provider's name
    name: str  # The provider's name (same as provider)
    latest_dataset: DatasetInfo
    bounding_box: Optional[BoundingBox] = (
        None  # The geographical bounding box of the dataset, if available
    )


class Location(BaseModel):
    lat: float
    lon: float


class Shape(BaseModel):
    shape_id: str
    points: List[List[float]]


class Stop(BaseModel):
    id: str
    name: str
    location: Location
    arrival_time: str
    departure_time: str


class RouteInfo(BaseModel):
    route_id: str
    route_name: str
    short_name: Optional[str]
    color: Optional[str]
    text_color: Optional[str]
    first_stop: str  # Name of first stop
    last_stop: str  # Name of last stop
    stops: Optional[List[str]] = None  # List of stop names in order
    headsign: Optional[str]
    service_days: List[str]
    parent_station_id: Optional[str] = (None,)
    terminus_stop_id: Optional[str] = None
    service_days_explicit: Optional[List[str]] = None  # Days from calendar.txt
    calendar_dates_additions: Optional[List[datetime]] = (
        None  # Days added via exceptions
    )
    calendar_dates_removals: Optional[List[datetime]] = (
        None  # Days removed via exceptions
    )
    valid_calendar_days: Optional[List[datetime]] = None  # All valid service days
    service_calendar: Optional[str] = None  # Human readable service calendar

    @field_validator("service_days")
    @classmethod
    def sort_service_days(cls, v):
        day_order = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        # Convert input to title case before sorting
        v = [day.title() for day in v]
        return sorted(v, key=lambda x: day_order.index(x))


class StationResponse(BaseModel):
    id: str
    name: str
    location: Location
    translations: Optional[dict[str, str]] = None
    routes: Optional[List[RouteInfo]] = None  # List of routes serving this stop


class Route(BaseModel):
    route_id: str
    route_name: str
    trip_id: str
    service_days: List[str]
    duration_minutes: int
    stops: List[Stop]
    shape: Optional[Shape] = None
    line_number: Optional[str] = None
    color: Optional[str] = None
    text_color: Optional[str] = None
    headsigns: Optional[Dict[str, str]] = None  # direction_id -> headsign
    service_ids: Optional[List[str]] = None  # List of service IDs for debugging

    @field_validator("service_days")
    @classmethod
    def sort_service_days(cls, v):
        day_order = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        # Convert input to title case before sorting
        v = [day.title() for day in v]
        return sorted(v, key=lambda x: day_order.index(x))


class RouteResponse(BaseModel):
    routes: List[Route]
    total_routes: int


class ArrivalInfo(BaseModel):
    route: RouteInfo
    waiting_time: int
    is_realtime: bool
    provider: str
    scheduled_time: Optional[str] = None
    departure_time: Optional[str] = None


class RouteMetadata(BaseModel):
    route_desc: str
    route_short_name: str


class RouteArrivals(BaseModel):
    _metadata: RouteMetadata
    destinations: Dict[str, List[ArrivalInfo]]  # headsign -> arrivals


class StopData(BaseModel):
    coordinates: Location
    lines: Dict[
        str, Dict[str, List[ArrivalInfo] | List[RouteMetadata]]
    ]  # route_id -> {terminus_name: List[ArrivalInfo], "_metadata": List[RouteMetadata]}
    name: str


class WaitingTimeInfo(BaseModel):
    _metadata: Dict[str, Dict[str, float]]  # performance metadata
    stops_data: Dict[str, StopData]  # stop_id -> StopData


class RouteColors(BaseModel):
    background: str  # HEX color code
    background_border: str  # HEX color code
    text: str  # HEX color code
    text_border: str  # HEX color code


class LineInfo(BaseModel):
    color: Optional[str]  # HEX color code
    display_name: str  # Short name or route_id if not available
    long_name: str  # Long name or empty string if not available
    provider: str  # Provider ID
    route_id: str  # Route ID
    route_type: Optional[int] = None  # GTFS route type
    text_color: Optional[str]  # HEX color code
    agency_id: Optional[str] = None  # Agency operating this route
    route_desc: Optional[str] = None  # Description of the route
    route_url: Optional[str] = None  # URL of a web page about the route
    route_sort_order: Optional[int] = None  # Order in which routes should be displayed
    continuous_pickup: Optional[int] = None  # Flag stop behavior for pickup (0-3)
    continuous_drop_off: Optional[int] = None  # Flag stop behavior for drop-off (0-3)
