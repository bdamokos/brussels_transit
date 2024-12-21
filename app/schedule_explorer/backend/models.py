from pydantic import BaseModel
from typing import List, Optional
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

class RouteResponse(BaseModel):
    routes: List[Route]
    total_routes: int

class StationResponse(BaseModel):
    id: str
    name: str
    location: Location
    translations: Optional[dict[str, str]] = None 