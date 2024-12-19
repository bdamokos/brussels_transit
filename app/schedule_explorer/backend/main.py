from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import os
from pathlib import Path

from .models import RouteResponse, StationResponse, Route, Stop, Location, Shape
from .gtfs_loader import FlixbusFeed, load_feed

app = FastAPI(title="Schedule Explorer API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
feed: Optional[FlixbusFeed] = None
current_provider: Optional[str] = None
available_providers: List[str] = []

def find_gtfs_directories() -> List[str]:
    """Find all GTFS data directories in the project's cache directory."""
    # Start from the current file's location
    current_path = Path(os.path.dirname(os.path.abspath(__file__)))
    
    # Navigate up to the project root (where cache directory is)
    project_root = current_path
    while project_root.name != 'STIB':
        project_root = project_root.parent
    
    # Look in the cache directory
    cache_path = project_root / 'cache'
    gtfs_dirs = []
    
    # Look for directories that contain GTFS files
    if cache_path.exists():
        for item in cache_path.iterdir():
            if item.is_dir():
                # Check if directory contains required GTFS files
                required_files = ['stops.txt', 'routes.txt', 'trips.txt', 'stop_times.txt']
                # Either calendar.txt or calendar_dates.txt is required
                calendar_files = ['calendar.txt', 'calendar_dates.txt']
                
                if (all((item / file).exists() for file in required_files) and 
                    any((item / file).exists() for file in calendar_files)):
                    gtfs_dirs.append(item.name)
    
    return sorted(gtfs_dirs)

@app.on_event("startup")
async def startup_event():
    """Load available GTFS providers on startup"""
    global available_providers
    available_providers = find_gtfs_directories()

@app.get("/providers", response_model=List[str])
async def get_providers():
    """Get list of available GTFS providers"""
    return available_providers

@app.post("/provider/{provider_name}")
async def set_provider(provider_name: str):
    """Set the current GTFS provider and load its data"""
    global feed, current_provider
    
    if provider_name not in available_providers:
        raise HTTPException(status_code=404, detail=f"Provider {provider_name} not found")
    
    try:
        feed = load_feed(provider_name)
        current_provider = provider_name
        return {"status": "success", "message": f"Loaded GTFS data for {provider_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stations/search", response_model=List[StationResponse])
async def search_stations(query: str = Query(..., min_length=2)):
    """Search for stations by name"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    # Case-insensitive search
    matches = []
    for stop_id, stop in feed.stops.items():
        if query.lower() in stop.name.lower():
            matches.append(StationResponse(
                id=stop_id,
                name=stop.name,
                location=Location(lat=stop.lat, lon=stop.lon)
            ))
    return matches

@app.get("/routes", response_model=RouteResponse)
async def get_routes(
    from_station: str = Query(..., description="Departure station ID"),
    to_station: str = Query(..., description="Destination station ID"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format")
):
    """Get all routes between two stations for a specific date"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    # Validate stations exist
    if from_station not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {from_station} not found")
    if to_station not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {to_station} not found")
    
    # Find routes
    routes = feed.find_routes_between_stations(from_station, to_station)
    
    # Filter by date if provided
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
            day_name = target_date.strftime("%A").lower()
            routes = [r for r in routes if day_name in r.service_days]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    
    # Convert to response format
    route_responses = []
    for route in routes:
        # Get relevant stops
        stops = route.get_stops_between(from_station, to_station)
        duration = route.calculate_duration(from_station, to_station)
        
        if not duration:
            continue
            
        route_responses.append(Route(
            route_id=route.route_id,
            route_name=route.route_name,
            trip_id=route.trip_id,
            service_days=route.service_days,
            duration_minutes=int(duration.total_seconds() / 60),
            stops=[
                Stop(
                    id=stop.stop.id,
                    name=stop.stop.name,
                    location=Location(lat=stop.stop.lat, lon=stop.stop.lon),
                    arrival_time=stop.arrival_time,
                    departure_time=stop.departure_time
                )
                for stop in stops
            ],
            shape=Shape(
                shape_id=route.shape.shape_id,
                points=route.shape.points
            ) if route.shape else None
        ))
    
    return RouteResponse(
        routes=route_responses,
        total_routes=len(route_responses)
    ) 