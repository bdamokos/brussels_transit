from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from datetime import datetime, timedelta

from .models import RouteResponse, StationResponse, Route, Stop, Location, Shape
from .gtfs_loader import FlixbusFeed, load_feed

app = FastAPI(title="Flixbus Explorer API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global GTFS feed instance
feed: Optional[FlixbusFeed] = None

@app.on_event("startup")
async def startup_event():
    """Load GTFS data on startup"""
    global feed
    feed = load_feed()

@app.get("/stations/search", response_model=List[StationResponse])
async def search_stations(query: str = Query(default="", min_length=0)):
    """Search for stations by name"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    # If query is empty, return all stations (limited to 100 for performance)
    if not query:
        stations = [
            StationResponse(
                id=stop_id,
                name=stop.name,
                location=Location(lat=stop.lat, lon=stop.lon)
            )
            for stop_id, stop in feed.stops.items()
        ]
        # Sort alphabetically and limit to 100
        return sorted(stations, key=lambda x: x.name.lower())[:100]
    
    # Case-insensitive search
    matches = []
    for stop_id, stop in feed.stops.items():
        if query.lower() in stop.name.lower():
            matches.append(StationResponse(
                id=stop_id,
                name=stop.name,
                location=Location(lat=stop.lat, lon=stop.lon)
            ))
    
    # Sort matches alphabetically
    return sorted(matches, key=lambda x: x.name.lower())

@app.get("/routes", response_model=RouteResponse)
async def get_routes(
    from_station: str = Query(..., description="Departure station ID or comma-separated list of IDs"),
    to_station: str = Query(..., description="Destination station ID or comma-separated list of IDs"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format")
):
    """Get all routes between multiple possible stations for a specific date"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    # Parse station IDs
    from_stations = from_station.split(',')
    to_stations = to_station.split(',')
    
    # Validate all stations exist
    for station_id in from_stations:
        if station_id not in feed.stops:
            raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    for station_id in to_stations:
        if station_id not in feed.stops:
            raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find routes between all combinations of stations
    all_routes = []
    for from_id in from_stations:
        for to_id in to_stations:
            routes = feed.find_routes_between_stations(from_id, to_id)
            all_routes.extend(routes)
    
    # Remove duplicates based on route_id and trip_id combination
    unique_routes = {}
    for route in all_routes:
        route_key = f"{route.route_id}_{route.trips[0].id if route.trips else ''}"
        if route_key not in unique_routes:
            unique_routes[route_key] = route
    
    routes = list(unique_routes.values())
    
    # Filter by date if provided
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
            prev_date = target_date - timedelta(days=1)
            
            filtered_routes = []
            for route in routes:
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
            routes = [r[0] for r in routes_with_stations]
            
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    else:
        # If no date filter, still need to track which stations to use for each route
        routes_with_stations = []
        for route in routes:
            for from_id in from_stations:
                for to_id in to_stations:
                    if route.get_stops_between(from_id, to_id):
                        routes_with_stations.append((route, from_id, to_id))
                        break  # Found a valid combination, no need to check others
    
    # Convert to response format
    route_responses = []
    for route, from_id, to_id in routes_with_stations:
        # Check each trip in the route
        for trip in route.trips:
            # Get relevant stops for this trip
            stops = route.get_trip_stops_between(trip, from_id, to_id)
            if not stops:
                continue
                
            # Calculate duration for this trip
            departure = stops[0].departure_time
            arrival = stops[-1].arrival_time
            
            # Parse times
            def parse_time(time_str: str) -> datetime:
                hours, minutes, seconds = map(int, time_str.split(':'))
                base_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
                return base_date + timedelta(hours=hours, minutes=minutes, seconds=seconds)
            
            departure_time = parse_time(departure)
            arrival_time = parse_time(arrival)
            
            # Handle overnight routes
            if arrival_time < departure_time:
                arrival_time += timedelta(days=1)
            
            duration = arrival_time - departure_time
            
            route_responses.append(Route(
                route_id=route.route_id,
                route_name=route.route_name,
                line_number=route.short_name or "",
                trip_id=trip.id,
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
                ) if route.shape else None,
                color=route.color or "",
                text_color=route.text_color or "FFFFFF"
            ))
    
    # Sort routes by actual departure time
    route_responses.sort(key=lambda r: _normalize_time(r.stops[0].departure_time))
    
    return RouteResponse(
        routes=route_responses,
        total_routes=len(route_responses)
    )

@app.get("/stations/destinations/{station_id}", response_model=List[StationResponse])
async def get_possible_destinations(station_id: str):
    """Get all possible destination stations from a given station"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    if station_id not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find all routes that start from this station
    destinations = set()
    for route in feed.all_routes:
        stops = route.stops
        try:
            # Find the position of our station in the route
            station_idx = next(i for i, stop in enumerate(stops) if stop.stop.id == station_id)
            # Add all subsequent stops as possible destinations
            for stop in stops[station_idx + 1:]:
                destinations.add(stop.stop.id)
        except StopIteration:
            continue
    
    # Convert to response format and sort alphabetically
    return sorted([
        StationResponse(
            id=stop_id,
            name=feed.stops[stop_id].name,
            location=Location(lat=feed.stops[stop_id].lat, lon=feed.stops[stop_id].lon)
        )
        for stop_id in destinations
        if stop_id in feed.stops
    ], key=lambda x: x.name.lower())

@app.get("/stations/origins/{station_id}", response_model=List[StationResponse])
async def get_possible_origins(station_id: str):
    """Get all possible origin stations for a given destination station"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    if station_id not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find all routes that end at this station
    origins = set()
    for route in feed.all_routes:
        stops = route.stops
        try:
            # Find the position of our station in the route
            station_idx = next(i for i, stop in enumerate(stops) if stop.stop.id == station_id)
            # Add all previous stops as possible origins
            for stop in stops[:station_idx]:
                origins.add(stop.stop.id)
        except StopIteration:
            continue
    
    # Convert to response format and sort alphabetically
    return sorted([
        StationResponse(
            id=stop_id,
            name=feed.stops[stop_id].name,
            location=Location(lat=feed.stops[stop_id].lat, lon=feed.stops[stop_id].lon)
        )
        for stop_id in origins
        if stop_id in feed.stops
    ], key=lambda x: x.name.lower())

def _normalize_time(time_str: str) -> float:
    """Convert a time string to a comparable number, handling +1 day notation"""
    hours, minutes = map(int, time_str.split(":")[0:2])
    if hours >= 24:
        hours -= 24
    return hours + minutes/60 