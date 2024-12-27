from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import time


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


class Provider(BaseModel):
    id: str  # The long ID generated from the provider's name and the dataset_id (raw_id) (e.g. "Budapest_Transport_mdb-990")
    raw_id: str  # The short ID (e.g. "mdb-990") - the raw ID is the dataset_id in the Mobility Database
    provider: str  # The provider's name
    name: str  # The provider's name (same as provider)
    latest_dataset: DatasetInfo


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


class RouteResponse(BaseModel):
    routes: List[Route]
    total_routes: int


class StationResponse(BaseModel):
    id: str
    name: str
    location: Location
    translations: Optional[dict[str, str]] = None


class RouteInfo(BaseModel):
    route_id: str
    route_name: str
    short_name: Optional[str]
    color: Optional[str]
    text_color: Optional[str]
    first_stop: str  # Name of first stop
    last_stop: str  # Name of last stop
    stops: List[str]  # List of stop names in order
    headsign: Optional[str]
    service_days: List[str]
    parent_station_id: Optional[str] = (None,)
    terminus_stop_id: Optional[str] = None


class ArrivalInfo(BaseModel):
    is_realtime: bool
    provider: str
    scheduled_time: str
    scheduled_minutes: str


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
