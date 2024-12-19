from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set
import pandas as pd
from pathlib import Path
import os

@dataclass
class Stop:
    id: str
    name: str
    lat: float
    lon: float

@dataclass
class RouteStop:
    stop: Stop
    arrival_time: str
    departure_time: str
    stop_sequence: int

@dataclass
class Shape:
    shape_id: str
    points: List[List[float]]

@dataclass
class Route:
    route_id: str
    route_name: str
    trip_id: str
    service_days: List[str]
    stops: List[RouteStop]
    shape: Optional[Shape] = None
    
    def get_stop_by_id(self, stop_id: str) -> Optional[RouteStop]:
        """Get a stop in this route by its ID"""
        return next((stop for stop in self.stops if stop.stop.id == stop_id), None)
    
    def get_stops_between(self, start_id: str, end_id: str) -> List[RouteStop]:
        """Get all stops between (and including) the start and end stops"""
        start_seq = next((s.stop_sequence for s in self.stops if s.stop.id == start_id), None)
        end_seq = next((s.stop_sequence for s in self.stops if s.stop.id == end_id), None)
        
        if start_seq is None or end_seq is None:
            return []
            
        # Keep original order based on stop_sequence
        if start_seq <= end_seq:
            return [s for s in self.stops if start_seq <= s.stop_sequence <= end_seq]
        else:
            return []  # Don't return stops in reverse order
    
    def calculate_duration(self, start_id: str, end_id: str) -> Optional[timedelta]:
        """Calculate duration between any two stops in the route"""
        start_stop = self.get_stop_by_id(start_id)
        end_stop = self.get_stop_by_id(end_id)
        
        if not (start_stop and end_stop):
            return None
        
        def parse_time(time_str: str) -> datetime:
            hours, minutes, seconds = map(int, time_str.split(':'))
            base_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
            return base_date + timedelta(hours=hours, minutes=minutes, seconds=seconds)
        
        departure = parse_time(start_stop.departure_time)
        arrival = parse_time(end_stop.arrival_time)
        
        if arrival < departure:  # Handle overnight routes
            arrival += timedelta(days=1)
            
        return arrival - departure

@dataclass
class FlixbusFeed:
    stops: Dict[str, Stop]
    routes: List[Route]
    
    def find_routes_between_stations(self, start_id: str, end_id: str) -> List[Route]:
        """Find all routes between two stations in the specified direction"""
        routes = []
        
        for route in self.routes:
            # Get all stops in this route
            stops = route.get_stops_between(start_id, end_id)
            
            # Check if both stations are in this route and in the correct order
            if len(stops) >= 2 and stops[0].stop.id == start_id and stops[-1].stop.id == end_id:
                routes.append(route)
        
        return routes

def load_feed(data_dir: str = "Flixbus/gtfs_generic_eu", target_stops: Set[str] = None) -> FlixbusFeed:
    """
    Load GTFS feed from the specified directory.
    If target_stops is provided, only loads routes that contain those stops.
    """
    print("Loading GTFS feed from:", data_dir)
    
    # Start from the current file's location
    current_path = Path(os.path.dirname(os.path.abspath(__file__)))
    
    # Navigate up to the project root (where cache directory is)
    project_root = current_path
    while project_root.name != 'STIB':
        project_root = project_root.parent
    
    # Look in the cache directory
    data_path = project_root / 'cache' / data_dir
    
    # Load stops
    print("Loading stops...")
    stops_df = pd.read_csv(data_path / "stops.txt")
    stops = {
        str(row.stop_id): Stop(
            id=str(row.stop_id),
            name=row.stop_name,
            lat=row.stop_lat,
            lon=row.stop_lon
        )
        for row in stops_df.itertuples()
    }
    print(f"Loaded {len(stops)} stops")
    
    # Load shapes if available
    shapes = {}
    try:
        print("Loading shapes...")
        shapes_df = pd.read_csv(data_path / "shapes.txt")
        # Group by shape_id and sort by sequence
        for shape_id, group in shapes_df.groupby('shape_id'):
            sorted_points = group.sort_values('shape_pt_sequence')[['shape_pt_lat', 'shape_pt_lon']].values.tolist()
            shapes[shape_id] = Shape(shape_id=str(shape_id), points=sorted_points)
        print(f"Loaded {len(shapes)} shapes")
    except FileNotFoundError:
        print("No shapes.txt found, routes will use stop coordinates")
    
    # Load routes and other data
    print("Loading routes, trips, stop times, and calendar...")
    routes_df = pd.read_csv(data_path / "routes.txt")
    trips_df = pd.read_csv(data_path / "trips.txt")
    stop_times_df = pd.read_csv(data_path / "stop_times.txt")
    calendar_df = pd.read_csv(data_path / "calendar.txt")
    
    # If we have target stops, pre-filter the trips that contain them
    if target_stops:
        print(f"Pre-filtering trips containing stops: {target_stops}")
        # Convert stop_id to string for consistent comparison
        stop_times_df['stop_id'] = stop_times_df['stop_id'].astype(str)
        # Get trips that contain any of our target stops
        relevant_trips = stop_times_df[stop_times_df['stop_id'].isin(target_stops)]['trip_id'].unique()
        trips_df = trips_df[trips_df['trip_id'].isin(relevant_trips)]
        print(f"Found {len(trips_df)} relevant trips")
    
    print("Processing routes...")
    routes = []
    for idx, trip in enumerate(trips_df.iterrows()):
        if idx % 10 == 0:  # Progress indicator every 10 trips
            print(f"Processing trip {idx}/{len(trips_df)}")
            
        trip = trip[1]  # Get the actual row data
        route_id = trip.route_id
        trip_id = trip.trip_id
        
        # Get route name
        route_name = routes_df[routes_df.route_id == route_id].route_long_name.iloc[0]
        
        # Get service days
        service = calendar_df[calendar_df.service_id == trip.service_id].iloc[0]
        service_days = [
            day for day, operates in service[['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']].items()
            if operates == 1
        ]
        
        # Get stops for this trip
        trip_stops_df = stop_times_df[stop_times_df.trip_id == trip_id].sort_values('stop_sequence')
        route_stops = []
        
        for _, stop_time in trip_stops_df.iterrows():
            stop_id = str(stop_time.stop_id)
            if stop_id in stops:
                route_stops.append(
                    RouteStop(
                        stop=stops[stop_id],
                        arrival_time=stop_time.arrival_time,
                        departure_time=stop_time.departure_time,
                        stop_sequence=stop_time.stop_sequence
                    )
                )
        
        # Get shape for this trip if available
        shape = None
        if hasattr(trip, 'shape_id') and trip.shape_id in shapes:
            shape = shapes[trip.shape_id]
        
        routes.append(
            Route(
                route_id=route_id,
                route_name=route_name,
                trip_id=trip_id,
                service_days=service_days,
                stops=route_stops,
                shape=shape
            )
        )
    
    print(f"Loaded {len(routes)} routes")
    return FlixbusFeed(stops=stops, routes=routes) 