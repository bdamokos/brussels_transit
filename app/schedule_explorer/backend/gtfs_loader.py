from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set
import pandas as pd
from pathlib import Path
import os
import pickle
import hashlib
from multiprocessing import Pool, cpu_count

@dataclass
class Stop:
    id: str
    name: str
    lat: float
    lon: float
    translations: Dict[str, str] = field(default_factory=dict)
    location_type: Optional[int] = None
    parent_station: Optional[str] = None
    platform_code: Optional[str] = None
    timezone: Optional[str] = None

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
    short_name: Optional[str] = None
    long_name: Optional[str] = None
    route_type: Optional[int] = None
    color: Optional[str] = None
    text_color: Optional[str] = None
    agency_id: Optional[str] = None
    
    def get_stop_by_id(self, stop_id: str) -> Optional[RouteStop]:
        """Get a stop in this route by its ID"""
        return next((stop for stop in self.stops if stop.stop.id == stop_id), None)
    
    def get_stops_between(self, start_id: Optional[str], end_id: Optional[str]) -> List[RouteStop]:
        """Get all stops between (and including) the start and end stops"""
        if start_id is None and end_id is None:
            return []
            
        if start_id is None:
            # Find the end stop and return all stops up to it
            end_seq = next((s.stop_sequence for s in self.stops if s.stop.id == end_id), None)
            if end_seq is None:
                return []
            return [s for s in self.stops if s.stop_sequence <= end_seq]
            
        if end_id is None:
            # Find the start stop and return all stops after it
            start_seq = next((s.stop_sequence for s in self.stops if s.stop.id == start_id), None)
            if start_seq is None:
                return []
            return [s for s in self.stops if s.stop_sequence >= start_seq]
        
        # Both stops are specified
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

def calculate_gtfs_hash(data_path: Path) -> str:
    """Calculate a hash of the GTFS files to determine if cache is valid."""
    hasher = hashlib.sha256()
    
    # List of files to include in the hash
    files_to_hash = ['stops.txt', 'routes.txt', 'trips.txt', 'stop_times.txt']
    calendar_files = ['calendar.txt', 'calendar_dates.txt']
    
    # Add whichever calendar file exists
    for cal_file in calendar_files:
        if (data_path / cal_file).exists():
            files_to_hash.append(cal_file)
            break
    
    # Optional files
    if (data_path / 'shapes.txt').exists():
        files_to_hash.append('shapes.txt')
    
    # Calculate hash
    for filename in sorted(files_to_hash):
        file_path = data_path / filename
        if file_path.exists():
            hasher.update(file_path.read_bytes())
    
    return hasher.hexdigest()

def process_trip_batch(args):
    """Process a batch of trips in parallel."""
    trips_batch, stops, shapes, routes_dict, calendar_dict, stop_times_dict, use_calendar_dates = args
    
    routes = []
    for trip in trips_batch:
        route_id = trip['route_id']
        trip_id = trip['trip_id']
        
        # Get route name from the routes dictionary, handle NaN values
        route_info = routes_dict.get(route_id, {})
        route_name = route_info.get('route_long_name', '')
        if pd.isna(route_name):
            route_name = route_info.get('route_short_name', '') or f"Route {route_id}"
        
        # Get service days based on calendar type
        if use_calendar_dates:
            # For calendar_dates.txt, group by service_id and get unique dates
            service_dates = calendar_dict.get(trip['service_id'], [])
            # Convert dates to days of the week
            service_days = list(set(
                datetime.strptime(date, '%Y%m%d').strftime('%A').lower()
                for date in service_dates
            ))
        else:
            # For calendar.txt, use the existing logic
            service = calendar_dict.get(trip['service_id'], {})
            service_days = [
                day for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                if service.get(day, 0) == 1
            ]
        
        # Get stops for this trip from the dictionary
        trip_stops = stop_times_dict.get(trip_id, [])
        route_stops = []
        
        for stop_time in sorted(trip_stops, key=lambda x: x['stop_sequence']):
            stop_id = str(stop_time['stop_id'])
            if stop_id in stops:
                route_stops.append(
                    RouteStop(
                        stop=stops[stop_id],
                        arrival_time=stop_time['arrival_time'],
                        departure_time=stop_time['departure_time'],
                        stop_sequence=stop_time['stop_sequence']
                    )
                )
        
        # Get shape for this trip if available
        shape = None
        if 'shape_id' in trip and trip['shape_id'] in shapes:
            shape = shapes[trip['shape_id']]
        
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
    
    return routes

CACHE_VERSION = "1.0"

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
    
    # Check if we have a valid cache
    cache_file = data_path / '.gtfs_cache'
    hash_file = data_path / '.gtfs_cache_hash'
    current_hash = f"{CACHE_VERSION}_{calculate_gtfs_hash(data_path)}"
    
    if cache_file.exists() and hash_file.exists():
        stored_hash = hash_file.read_text().strip()
        if stored_hash == current_hash:
            print(f"Loading from cache... {current_hash}")
            try:
                with open(cache_file, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"Failed to load cache: {e}")
                # Delete corrupted cache files
                try:
                    cache_file.unlink()
                    hash_file.unlink()
                except:
                    pass
    
    # Load stops
    print("Loading stops...")
    stops_df = pd.read_csv(data_path / "stops.txt", dtype={
        'stop_id': str,
        'stop_name': str,
        'stop_lat': float,
        'stop_lon': float
    })
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
        shapes_df = pd.read_csv(data_path / "shapes.txt", dtype={
            'shape_id': str,
            'shape_pt_lat': float,
            'shape_pt_lon': float,
            'shape_pt_sequence': int
        })
        # Group by shape_id and sort by sequence
        for shape_id, group in shapes_df.groupby('shape_id'):
            sorted_points = group.sort_values('shape_pt_sequence')[['shape_pt_lat', 'shape_pt_lon']].values.tolist()
            shapes[shape_id] = Shape(shape_id=str(shape_id), points=sorted_points)
        print(f"Loaded {len(shapes)} shapes")
    except FileNotFoundError:
        print("No shapes.txt found, routes will use stop coordinates")
    
    # Load routes and other data
    print("Loading routes, trips, stop times, and calendar...")
    routes_df = pd.read_csv(data_path / "routes.txt", dtype={
        'route_id': str,
        'route_long_name': str,
        'route_short_name': str
    })
    
    # Convert routes to dictionary early to free memory
    routes_dict = {
        row.route_id: {
            'route_long_name': row.route_long_name,
            'route_short_name': row.route_short_name
        }
        for row in routes_df.itertuples()
    }
    del routes_df
    
    # Load trips with correct dtypes
    trips_df = pd.read_csv(data_path / "trips.txt", dtype={
        'route_id': str,
        'service_id': str,
        'trip_id': str,
        'shape_id': str
    }, low_memory=False)
    
    # Load stop times in chunks to handle large files
    print("Loading stop times...")
    chunk_size = 100000
    stop_times_dict = {}
    
    for chunk in pd.read_csv(data_path / "stop_times.txt", 
                           chunksize=chunk_size,
                           dtype={
                               'trip_id': str,
                               'stop_id': str,
                               'arrival_time': str,
                               'departure_time': str,
                               'stop_sequence': int
                           }):
        for _, row in chunk.iterrows():
            if row.trip_id not in stop_times_dict:
                stop_times_dict[row.trip_id] = []
            stop_times_dict[row.trip_id].append({
                'stop_id': str(row.stop_id),
                'arrival_time': row.arrival_time,
                'departure_time': row.departure_time,
                'stop_sequence': row.stop_sequence
            })
    
    # Try to load calendar.txt first, fall back to calendar_dates.txt
    try:
        calendar_df = pd.read_csv(data_path / "calendar.txt", dtype={
            'service_id': str,
            'monday': int,
            'tuesday': int,
            'wednesday': int,
            'thursday': int,
            'friday': int,
            'saturday': int,
            'sunday': int
        })
        use_calendar_dates = False
        calendar_dict = {
            row.service_id: {
                'monday': row.monday,
                'tuesday': row.tuesday,
                'wednesday': row.wednesday,
                'thursday': row.thursday,
                'friday': row.friday,
                'saturday': row.saturday,
                'sunday': row.sunday
            }
            for row in calendar_df.itertuples()
        }
        del calendar_df
    except FileNotFoundError:
        calendar_df = pd.read_csv(data_path / "calendar_dates.txt", dtype={
            'service_id': str,
            'date': str
        })
        use_calendar_dates = True
        # Group dates by service_id
        calendar_dict = {}
        for _, row in calendar_df.iterrows():
            if row.service_id not in calendar_dict:
                calendar_dict[row.service_id] = []
            calendar_dict[row.service_id].append(str(row.date))
        del calendar_df
    
    # If we have target stops, pre-filter the trips that contain them
    if target_stops:
        print(f"Pre-filtering trips containing stops: {target_stops}")
        # Get trips that contain any of our target stops
        relevant_trips = set()
        for trip_id, stops_list in stop_times_dict.items():
            if any(str(stop['stop_id']) in target_stops for stop in stops_list):
                relevant_trips.add(trip_id)
        trips_df = trips_df[trips_df['trip_id'].isin(relevant_trips)]
        print(f"Found {len(trips_df)} relevant trips")
    
    print("Processing routes...")
    # Convert trips DataFrame to list of dictionaries and free memory
    trips_list = trips_df.to_dict('records')
    del trips_df
    
    # Process in smaller batches to reduce memory usage
    batch_size = min(1000, max(100, len(trips_list) // (cpu_count() * 4)))
    trip_batches = [trips_list[i:i + batch_size] for i in range(0, len(trips_list), batch_size)]
    del trips_list
    
    # Process routes in parallel with progress indicator
    routes = []
    total_batches = len(trip_batches)
    print(f"Processing {total_batches} batches...")
    
    with Pool() as pool:
        for i, batch_routes in enumerate(pool.imap_unordered(process_trip_batch, [
            (batch, stops, shapes, routes_dict, calendar_dict, stop_times_dict, use_calendar_dates)
            for batch in trip_batches
        ])):
            routes.extend(batch_routes)
            if (i + 1) % 10 == 0 or (i + 1) == total_batches:
                print(f"Processed {i + 1}/{total_batches} batches")
    
    print(f"Loaded {len(routes)} routes")
    
    # Create feed object
    feed = FlixbusFeed(stops=stops, routes=routes)
    
    # Save to cache
    print(f"Saving to cache... with hash {current_hash}")
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(feed, f)
        hash_file.write_text(current_hash)
    except Exception as e:
        print(f"Failed to save cache: {e}")
        # Clean up failed cache files
        try:
            cache_file.unlink()
            hash_file.unlink()
        except:
            pass
    
    return feed 