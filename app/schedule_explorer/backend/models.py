from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import time


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
