from pydantic import BaseModel, Field
from typing import List, Optional, Tuple

class Location(BaseModel):
    lat: float
    lon: float

class Shape(BaseModel):
    shape_id: str
    points: List[List[float]] = Field(description="List of [lat, lon] coordinates")

    def __init__(self, **data):
        # Convert tuples to lists if needed
        if 'points' in data and data['points'] and isinstance(data['points'][0], tuple):
            data['points'] = [list(point) for point in data['points']]
        super().__init__(**data)

class Stop(BaseModel):
    id: str
    name: str
    location: Location
    arrival_time: str
    departure_time: str

class Route(BaseModel):
    route_id: str
    route_name: str
    line_number: str
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