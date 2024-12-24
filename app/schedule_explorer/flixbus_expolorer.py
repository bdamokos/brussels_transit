from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set
import pandas as pd
from pathlib import Path

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
class Route:
    route_id: str
    route_name: str
    trip_id: str
    service_days: List[str]
    stops: List[RouteStop]
    
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
            return [s for s in self.stops if end_seq <= s.stop_sequence <= start_seq][::-1]
    
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
        
        # Determine which stop comes first in the sequence
        if start_stop.stop_sequence <= end_stop.stop_sequence:
            departure = parse_time(start_stop.departure_time)
            arrival = parse_time(end_stop.arrival_time)
        else:
            departure = parse_time(end_stop.departure_time)
            arrival = parse_time(start_stop.arrival_time)
        
        if arrival < departure:  # Handle overnight routes
            arrival += timedelta(days=1)
            
        return arrival - departure

@dataclass
class FlixbusFeed:
    stops: Dict[str, Stop]
    routes: List[Route]

def format_time(time_str: str) -> str:
    """Format time string with +1 for times past midnight"""
    hours, minutes = map(int, time_str.split(':')[:2])
    day = "+1" if hours >= 24 else ""
    if hours >= 24:
        hours -= 24
    return f"{hours:02d}:{minutes:02d}{day}"

def find_routes_between_stations(feed: FlixbusFeed, start_id: str, end_id: str) -> List[Route]:
    """Find all routes between two stations in the specified direction"""
    routes = []
    
    for route in feed.routes:
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
    data_path = Path(data_dir)
    
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
        if idx % 10 == 0:  # Progress indicator every 10 trips (since we have fewer now)
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
        
        routes.append(
            Route(
                route_id=route_id,
                route_name=route_name,
                trip_id=trip_id,
                service_days=service_days,
                stops=route_stops
            )
        )
    
    print(f"Loaded {len(routes)} routes")
    return FlixbusFeed(stops=stops, routes=routes)

def print_route_details(route: Route, start_id: str, end_id: str):
    """Print details of a route between specified stations"""
    print(f"\nRoute: {route.route_name}")
    print(f"Trip ID: {route.trip_id}")
    print(f"Operates on: {', '.join(route.service_days)}")
    
    # Get all stops between start and end
    relevant_stops = route.get_stops_between(start_id, end_id)
    duration = route.calculate_duration(start_id, end_id)
    
    if duration:
        print(f"Duration: {duration}")
    
    print("\nStops:")
    for stop in relevant_stops:
        print(f"- {stop.stop.name}")
        print(f"  Arrival: {format_time(stop.arrival_time)} | Departure: {format_time(stop.departure_time)}")
        print(f"  Location: {stop.stop.lat}, {stop.stop.lon}")

def main():
    print("Starting Flixbus route explorer...")
    
    # Define station IDs
    BRUSSELS_NORTH_ID = "dcbf8bd9-9603-11e6-9066-549f350fcb0c"  # Brussels-North train station
    ROTTERDAM_CENTRAL_ID = "dcbfe5ff-9603-11e6-9066-549f350fcb0c"  # Rotterdam Central Station
    
    # Load only routes containing our stations of interest
    feed = load_feed(target_stops={BRUSSELS_NORTH_ID, ROTTERDAM_CENTRAL_ID})
    
    print("\nSearching for routes from Brussels North to Rotterdam Central...")
    routes_to_rotterdam = find_routes_between_stations(feed, BRUSSELS_NORTH_ID, ROTTERDAM_CENTRAL_ID)
    print(f"Found {len(routes_to_rotterdam)} routes to Rotterdam")
    for route in routes_to_rotterdam:
        print_route_details(route, BRUSSELS_NORTH_ID, ROTTERDAM_CENTRAL_ID)
    
    print("\nSearching for routes from Rotterdam Central to Brussels North...")
    routes_to_brussels = find_routes_between_stations(feed, ROTTERDAM_CENTRAL_ID, BRUSSELS_NORTH_ID)
    print(f"Found {len(routes_to_brussels)} routes to Brussels")
    for route in routes_to_brussels:
        print_route_details(route, ROTTERDAM_CENTRAL_ID, BRUSSELS_NORTH_ID)

if __name__ == "__main__":
    main()
