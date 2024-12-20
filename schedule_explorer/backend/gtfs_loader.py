from dataclasses import dataclass
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
    short_name: str
    long_name: str
    route_type: Optional[int]
    color: Optional[str]
    text_color: Optional[str]
    agency_id: Optional[str]
    trips: List[dict]
    _feed: Optional['FlixbusFeed'] = None
    
    @property
    def route_name(self) -> str:
        """Get a display name for this route"""
        if self.short_name:
            if self.long_name:
                return f"{self.short_name} - {self.long_name}"
            return self.short_name
        if self.long_name:
            return self.long_name
        return f"Route {self.route_id}"
    
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

# Cache version - bump this when changing the data format
CACHE_VERSION = 1

def deserialize_gtfs_data(data: bytes) -> FlixbusFeed:
    """Deserialize GTFS data from bytes"""
    try:
        return pickle.loads(data)
    except Exception as e:
        raise ValueError(f"Failed to deserialize GTFS data: {e}")

def calculate_gtfs_hash(data_dir: Path) -> str:
    """Calculate a hash of all GTFS files to detect changes"""
    hasher = hashlib.sha256()
    
    # Add cache version to the hash
    hasher.update(str(CACHE_VERSION).encode())
    
    # Sort files to ensure consistent order
    gtfs_files = sorted([
        f for f in data_dir.glob('*.txt')
        if f.name in ['stops.txt', 'routes.txt', 'trips.txt', 'stop_times.txt', 
                     'calendar.txt', 'calendar_dates.txt', 'shapes.txt']
    ])
    
    for file_path in gtfs_files:
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
        
        # Get route info from the routes dictionary
        route_info = routes_dict.get(route_id, {})
        
        # Handle route names
        short_name = route_info.get('route_short_name', '')
        long_name = route_info.get('route_long_name', '')
        if pd.isna(short_name): short_name = ''
        if pd.isna(long_name): long_name = ''
        
        # Handle route type
        route_type = route_info.get('route_type')
        if pd.isna(route_type): route_type = None
        else: route_type = int(route_type)
        
        # Handle colors
        color = route_info.get('route_color')
        if pd.notna(color):
            color = str(color).strip().lstrip('#')
            if len(color) < 6:
                color = color.zfill(6)
            elif len(color) > 6:
                color = color[:6]
        else:
            color = None
            
        text_color = route_info.get('route_text_color')
        if pd.notna(text_color):
            text_color = str(text_color).strip().lstrip('#')
            if len(text_color) < 6:
                text_color = text_color.zfill(6)
            elif len(text_color) > 6:
                text_color = text_color[:6]
        else:
            text_color = None
        
        routes.append(
            Route(
                route_id=route_id,
                short_name=short_name,
                long_name=long_name,
                route_type=route_type,
                color=color,
                text_color=text_color,
                agency_id=route_info.get('agency_id'),
                trips=[trip],
                _feed=None  # Will be set later
            )
        )
    
    return routes

def load_feed(data_dir: str = None, target_stops: Set[str] = None) -> FlixbusFeed:
    """Load GTFS data with caching"""
    if not data_dir:
        data_dir = os.getenv('GTFS_DATA_DIR', 'gtfs_generic_eu')
    
    # Convert relative path to absolute path
    if not os.path.isabs(data_dir):
        # Start from the current file's location
        current_path = Path(os.path.dirname(os.path.abspath(__file__)))
        # Navigate up to the project root
        project_root = current_path.parent.parent
        # Look in the cache directory
        data_dir = project_root / 'cache' / data_dir
    else:
        data_dir = Path(data_dir)
    
    print(f"Loading GTFS feed from {data_dir} (cache version {CACHE_VERSION})")
    
    # Calculate hash of GTFS files
    gtfs_hash = calculate_gtfs_hash(data_dir)
    cache_file = data_dir / '.gtfs_cache'
    cache_hash_file = data_dir / '.gtfs_cache_hash'
    
    # Check if cache exists and is valid
    if cache_file.exists() and cache_hash_file.exists():
        stored_hash = cache_hash_file.read_text().strip()
        if stored_hash == gtfs_hash:
            try:
                print("Found valid cache, loading...")
                with cache_file.open('rb') as f:
                    return deserialize_gtfs_data(f.read())
            except Exception as e:
                print(f"Error loading cache: {e}")
                # Delete corrupted cache files
                try:
                    print("Deleting corrupted cache files...")
                    cache_file.unlink()
                    cache_hash_file.unlink()
                except Exception as e:
                    print(f"Error deleting cache files: {e}")
    else:
        print("No cache found or cache is invalid")
    
    print("Loading from GTFS files...")
    
    # Load stops
    print("Loading stops...")
    stops_df = pd.read_csv(data_dir / "stops.txt", dtype={
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
        shapes_df = pd.read_csv(data_dir / "shapes.txt", dtype={
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
    routes_df = pd.read_csv(data_dir / "routes.txt", dtype={
        'route_id': str,
        'route_short_name': str,
        'route_long_name': str,
        'route_type': int,
        'route_color': str,
        'route_text_color': str,
        'agency_id': str
    })
    
    # Convert routes to dictionary early to free memory
    routes_dict = {
        row.route_id: {
            'route_short_name': row.route_short_name,
            'route_long_name': row.route_long_name,
            'route_type': row.route_type,
            'route_color': row.route_color if hasattr(row, 'route_color') else None,
            'route_text_color': row.route_text_color if hasattr(row, 'route_text_color') else None,
            'agency_id': row.agency_id if hasattr(row, 'agency_id') else None
        }
        for row in routes_df.itertuples()
    }
    del routes_df
    
    # Load trips with correct dtypes
    trips_df = pd.read_csv(data_dir / "trips.txt", dtype={
        'route_id': str,
        'service_id': str,
        'trip_id': str,
        'shape_id': str
    }, low_memory=False)
    
    # Load stop times in chunks to handle large files
    print("Loading stop times...")
    chunk_size = 100000
    stop_times_dict = {}
    
    for chunk in pd.read_csv(data_dir / "stop_times.txt", 
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
        calendar_df = pd.read_csv(data_dir / "calendar.txt", dtype={
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
        calendar_df = pd.read_csv(data_dir / "calendar_dates.txt", dtype={
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
    print("Saving to cache...")
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(feed, f)
        cache_hash_file.write_text(gtfs_hash)
    except Exception as e:
        print(f"Failed to save cache: {e}")
        # Clean up failed cache files
        try:
            cache_file.unlink()
            cache_hash_file.unlink()
        except:
            pass
    
    return feed 

def load_routes(data_dir: Path) -> Dict[str, Route]:
    """Load routes with provider-specific handling"""
    routes = {}
    routes_df = pd.read_csv(data_dir / 'routes.txt')
    
    print("\nLoading routes:")
    print(f"Columns in routes.txt: {routes_df.columns.tolist()}")
    
    for _, row in routes_df.iterrows():
        route_id = str(row['route_id'])
        
        # Handle route names
        short_name = str(row['route_short_name']) if pd.notna(row.get('route_short_name')) else ''
        long_name = str(row['route_long_name']) if pd.notna(row.get('route_long_name')) else ''
        
        # Handle route type
        route_type = int(row['route_type']) if pd.notna(row.get('route_type')) else None
        
        # Handle colors - ensure they are 6-digit hex without #
        color = None
        if 'route_color' in row and pd.notna(row['route_color']):
            color = str(row['route_color']).strip().lstrip('#')
            if len(color) < 6:
                color = color.zfill(6)
            elif len(color) > 6:
                color = color[:6]
                
        text_color = None
        if 'route_text_color' in row and pd.notna(row['route_text_color']):
            text_color = str(row['route_text_color']).strip().lstrip('#')
            if len(text_color) < 6:
                text_color = text_color.zfill(6)
            elif len(text_color) > 6:
                text_color = text_color[:6]
        
        route = Route(
            route_id=route_id,
            short_name=short_name,
            long_name=long_name,
            route_type=route_type,
            color=color,
            text_color=text_color,
            agency_id=str(row['agency_id']) if 'agency_id' in row and pd.notna(row['agency_id']) else None,
            trips=[],
            _feed=None
        )
        routes[route_id] = route
    
    return routes 