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
    route_short_name: Optional[str] = None
    route_long_name: Optional[str] = None
    route_type: Optional[int] = None
    route_name: str  # For backward compatibility
    trip_id: str
    service_days: List[str]
    duration_minutes: int
    stops: List[Stop]
    shape: Optional[Shape] = None
    color: Optional[str] = None
    text_color: Optional[str] = None

class RouteResponse(BaseModel):
    routes: List[Route]
    total_routes: int

class StationResponse(BaseModel):
    id: str
    name: str
    location: Location 