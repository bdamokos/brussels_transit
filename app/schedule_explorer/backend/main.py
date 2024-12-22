from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import os
from pathlib import Path
import pandas as pd
import logging
from .logging_config import setup_logging

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
logger = setup_logging()

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
    
    # If the requested provider is already loaded, return early
    if feed is not None and current_provider == provider_name:
        logger.info(f"Provider {provider_name} already loaded, skipping reload")
        return {"status": "success", "message": f"Provider {provider_name} already loaded"}
    
    try:
        logger.info(f"Loading GTFS data for provider {provider_name}")
        feed = load_feed(provider_name)
        current_provider = provider_name
        return {"status": "success", "message": f"Loaded GTFS data for {provider_name}"}
    except Exception as e:
        logger.error(f"Error loading provider {provider_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stations/search", response_model=List[StationResponse])
async def search_stations(
    query: str = Query(..., min_length=2),
    language: Optional[str] = Query('default', description="Language code (e.g., 'fr', 'nl') or 'default'")
):
    """Search for stations by name"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    logger.info(f"Searching for stations with query: {query}, language: {language}")
    
    # Case-insensitive search in both default names and translations
    matches = []
    for stop_id, stop in feed.stops.items():
        # Search in default name and translations
        searchable_names = [stop.name.lower()]
        if stop.translations:
            searchable_names.extend(trans.lower() for trans in stop.translations.values())
        
        if any(query.lower() in name for name in searchable_names):
            # Get the appropriate name based on language
            display_name = stop.name  # Default name
            if language != 'default' and stop.translations and language in stop.translations:
                display_name = stop.translations[language]
            
            matches.append(StationResponse(
                id=stop_id,
                name=display_name,
                location=Location(lat=stop.lat, lon=stop.lon),
                translations=stop.translations
            ))
    
    logger.info(f"Found {len(matches)} matches")
    return matches

@app.get("/routes", response_model=RouteResponse)
async def get_routes(
    from_station: str = Query(..., description="Departure station ID"),
    to_station: str = Query(..., description="Destination station ID"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    language: Optional[str] = Query('default', description="Language code (e.g., 'fr', 'nl') or 'default'")
):
    """Get all routes between two stations for a specific date"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    # Handle multiple station IDs
    from_stations = from_station.split(',')
    to_stations = to_station.split(',')
    
    # Validate all stations exist
    for station_id in from_stations:
        if station_id not in feed.stops:
            raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    for station_id in to_stations:
        if station_id not in feed.stops:
            raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find routes for all combinations
    all_routes = []
    for from_id in from_stations:
        for to_id in to_stations:
            routes = feed.find_routes_between_stations(from_id, to_id)
            all_routes.extend(routes)
    
    # Filter by date if provided
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
            prev_date = target_date - timedelta(days=1)
            
            filtered_routes = []
            for route in all_routes:
                # Check all possible station combinations for this route
                for from_id in from_stations:
                    for to_id in to_stations:
                        stops = route.get_stops_between(from_id, to_id)
                        if not stops:
                            continue
                            
                        # Parse departure time to check if it's a next-day arrival
                        departure_time = stops[0].departure_time
                        hours = int(departure_time.split(":")[0])
                        
                        # If departure is before midnight, check current day
                        # If departure is after midnight, check previous day
                        if hours < 24:
                            if route.operates_on(target_date):
                                filtered_routes.append((route, from_id, to_id))
                                break  # Found a valid combination, no need to check others
                        else:
                            if route.operates_on(prev_date):
                                filtered_routes.append((route, from_id, to_id))
                                break  # Found a valid combination, no need to check others
            
            # Convert filtered routes back to the format we need
            routes_with_stations = filtered_routes
            all_routes = [r[0] for r in routes_with_stations]
            
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    
    # Convert to response format
    route_responses = []
    for route in all_routes:
        # Get relevant stops
        # Find first matching from and to stations in this route
        route_stop_ids = [stop.stop.id for stop in route.stops]
        matching_from = next((s for s in from_stations if s in route_stop_ids), None)
        matching_to = next((s for s in to_stations if s in route_stop_ids), None)
        
        if not matching_from or not matching_to:
            continue
        
        stops = route.get_stops_between(matching_from, matching_to)
        duration = route.calculate_duration(matching_from, matching_to)
        
        if not duration:
            continue
        
        # Handle NaN values in route name
        route_name = route.route_name
        if pd.isna(route_name) or not isinstance(route_name, str):
            route_name = f"Route {route.route_id}"
            
        route_responses.append(Route(
            route_id=route.route_id,
            route_name=route_name,
            trip_id=route.trip_id,
            service_days=route.service_days,
            duration_minutes=int(duration.total_seconds() / 60),
            stops=[
                Stop(
                    id=stop.stop.id,
                    name=feed.get_stop_name(stop.stop.id, language) if language != 'default' else stop.stop.name,
                    location=Location(lat=stop.stop.lat, lon=stop.stop.lon),
                    arrival_time=stop.arrival_time,
                    departure_time=stop.departure_time,
                    translations=stop.stop.translations
                )
                for stop in stops
            ],
            shape=Shape(
                shape_id=route.shape.shape_id,
                points=route.shape.points
            ) if route.shape else None,
            line_number=route.short_name if hasattr(route, 'short_name') else "",
            color=route.color if hasattr(route, 'color') else None,
            text_color=route.text_color if hasattr(route, 'text_color') else None
        ))
    
    return RouteResponse(
        routes=route_responses,
        total_routes=len(route_responses)
    )

@app.get("/stations/destinations/{station_id}", response_model=List[StationResponse])
async def get_destinations(
    station_id: str,
    language: Optional[str] = Query(None, description="Language code (e.g., 'fr', 'nl')")
):
    """Get all possible destination stations from a given station"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    if station_id not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find all routes that start from this station
    destinations = set()
    for route in feed.routes:
        # Get all stops in this route
        stops = route.get_stops_between(station_id, None)
        
        # If this station is in the route
        if stops and stops[0].stop.id == station_id:
            # Add all subsequent stops as potential destinations
            for stop in stops[1:]:
                destinations.add(stop.stop.id)
    
    # Convert to response format
    return [
        StationResponse(
            id=stop_id,
            name=feed.get_stop_name(stop_id, language) if language else feed.stops[stop_id].name,
            location=Location(
                lat=feed.stops[stop_id].lat,
                lon=feed.stops[stop_id].lon
            ),
            translations=feed.stops[stop_id].translations
        )
        for stop_id in destinations
        if stop_id in feed.stops
    ]

@app.get("/stations/origins/{station_id}", response_model=List[StationResponse])
async def get_origins(
    station_id: str,
    language: Optional[str] = Query(None, description="Language code (e.g., 'fr', 'nl')")
):
    """Get all possible origin stations that can reach a given station"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    if station_id not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find all routes that end at this station
    origins = set()
    for route in feed.routes:
        # Get all stops in this route
        stops = route.get_stops_between(None, station_id)
        
        # If this station is in the route
        if stops and stops[-1].stop.id == station_id:
            # Add all previous stops as potential origins
            for stop in stops[:-1]:
                origins.add(stop.stop.id)
    
    # Convert to response format
    return [
        StationResponse(
            id=stop_id,
            name=feed.get_stop_name(stop_id, language) if language else feed.stops[stop_id].name,
            location=Location(
                lat=feed.stops[stop_id].lat,
                lon=feed.stops[stop_id].lon
            ),
            translations=feed.stops[stop_id].translations
        )
        for stop_id in origins
        if stop_id in feed.stops
    ] 