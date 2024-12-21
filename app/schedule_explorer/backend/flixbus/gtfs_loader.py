from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set, Tuple
import pandas as pd
from pathlib import Path
import pickle
import os
import hashlib
import lzma
from multiprocessing import Pool, cpu_count
import msgpack
import logging

logger = logging.getLogger(__name__)

@dataclass
class Stop:
    """
    Represents a stop from stops.txt
    STIB: stop_id, stop_name, stop_lat, stop_lon, location_type, parent_station
    Flixbus: stop_id, stop_name, stop_lat, stop_lon, stop_timezone, platform_code
    """
    id: str
    name: str
    lat: float
    lon: float
    location_type: Optional[int] = None
    parent_station: Optional[str] = None
    platform_code: Optional[str] = None
    timezone: Optional[str] = None
    translations: Dict[str, str] = field(default_factory=dict)  # language -> translated name

@dataclass
class RouteStop:
    """Represents a stop in a route with arrival/departure times"""
    stop: Stop
    arrival_time: str
    departure_time: str
    stop_sequence: int

@dataclass
class Shape:
    """Represents a shape from shapes.txt"""
    shape_id: str
    points: List[Tuple[float, float]]  # List of (lat, lon) points
    
@dataclass
class Route:
    """
    Represents a route from routes.txt
    STIB: route_id, route_short_name (number), route_long_name, route_type, route_color, route_text_color
    Flixbus: agency_id, route_id, route_short_name, route_long_name (city pairs), route_type, route_color
    """
    id: str
    short_name: str
    long_name: str
    route_type: int
    color: Optional[str] = None
    text_color: Optional[str] = None
    agency_id: Optional[str] = None
    trips: List['Trip'] = field(default_factory=list)
    _feed: Optional['FlixbusFeed'] = field(default=None, repr=False)

    @property
    def route_id(self) -> str:
        """Backward compatibility with old code"""
        return self.id

    @property
    def route_name(self) -> str:
        """Backward compatibility with old code"""
        return self.long_name or self.short_name

    @property
    def trip_id(self) -> Optional[str]:
        """Backward compatibility with old code"""
        return self.trips[0].id if self.trips else None

    @property
    def service_days(self) -> List[str]:
        """Get the days of the week this route operates on"""
        if not self.trips or not self._feed:
            return []
        
        # Get unique service IDs from all trips
        service_ids = {trip.service_id for trip in self.trips}
        
        # Get days from both regular calendars and calendar dates
        days = set()
        
        # First check regular calendars
        has_regular_calendar = False
        for service_id in service_ids:
            if service_id in self._feed.calendars:
                has_regular_calendar = True
                calendar = self._feed.calendars[service_id]
                for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                    if getattr(calendar, day):
                        days.add(day.capitalize())
        
        if has_regular_calendar:
            # If we have regular calendars, check for type 2 exceptions (removals)
            # Group exceptions by weekday to see if any day is completely removed
            removals_by_day = {}
            for cal_date in self._feed.calendar_dates:
                if cal_date.service_id in service_ids and cal_date.exception_type == 2:
                    weekday = cal_date.date.strftime("%A")
                    if weekday not in removals_by_day:
                        removals_by_day[weekday] = set()
                    removals_by_day[weekday].add(cal_date.service_id)
            
            # Remove days that are completely excluded by type 2 exceptions
            for day, removed_services in removals_by_day.items():
                if removed_services == service_ids:  # All services have this day removed
                    days.discard(day)
        else:
            # If no regular calendar entries exist, check calendar_dates
            # Create a map of service_id -> set of weekdays it operates on
            service_days = {}
            for cal_date in self._feed.calendar_dates:
                if cal_date.service_id in service_ids:
                    weekday = cal_date.date.strftime("%A")
                    if cal_date.service_id not in service_days:
                        service_days[cal_date.service_id] = set()
                    if cal_date.exception_type == 1:  # Service added
                        service_days[cal_date.service_id].add(weekday)
            
            # Add all days from calendar exceptions
            for weekdays in service_days.values():
                days.update(weekdays)
        
        return sorted(list(days))

    @property
    def shape(self) -> Optional[Shape]:
        """Get the shape from the first trip"""
        if not self.trips or not self._feed:
            return None
        first_trip = self.trips[0]
        if not first_trip.shape_id or first_trip.shape_id not in self._feed.shapes:
            return None
        return self._feed.shapes[first_trip.shape_id]

    @property
    def stops(self) -> List[RouteStop]:
        """Backward compatibility with old code - get stops from first trip"""
        if not self.trips or not self._feed:
            return []
        first_trip = self.trips[0]
        return [
            RouteStop(
                stop=self._feed.stops[st.stop_id],
                arrival_time=st.arrival_time,
                departure_time=st.departure_time,
                stop_sequence=st.stop_sequence
            )
            for st in sorted(first_trip.stop_times, key=lambda x: x.stop_sequence)
        ]

    def get_stops_between(self, start_id: str, end_id: str) -> List[RouteStop]:
        """Get all stops between (and including) the start and end stops"""
        all_stops = self.stops
        try:
            start_idx = next(i for i, s in enumerate(all_stops) if s.stop.id == start_id)
            end_idx = next(i for i, s in enumerate(all_stops) if s.stop.id == end_id)
            if start_idx <= end_idx:
                return all_stops[start_idx:end_idx + 1]
        except StopIteration:
            pass
        return []

    def calculate_duration(self, start_id: str, end_id: str) -> Optional[timedelta]:
        """Calculate duration between any two stops in the route"""
        stops = self.get_stops_between(start_id, end_id)
        if len(stops) < 2:
            return None

        def parse_time(time_str: str) -> datetime:
            hours, minutes, seconds = map(int, time_str.split(':'))
            base_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
            return base_date + timedelta(hours=hours, minutes=minutes, seconds=seconds)

        departure = parse_time(stops[0].departure_time)
        arrival = parse_time(stops[-1].arrival_time)

        if arrival < departure:  # Handle overnight routes
            arrival += timedelta(days=1)

        return arrival - departure

    def operates_on(self, date: datetime) -> bool:
        """Check if this route operates on a specific date"""
        if not self.trips or not self._feed:
            return False
        
        # Check each trip - if any trip operates on this date, the route operates
        for trip in self.trips:
            service_id = trip.service_id
            operates = False
            has_exception = False
            
            # First check calendar_dates exceptions
            for cal_date in self._feed.calendar_dates:
                if cal_date.service_id == service_id and cal_date.date.date() == date.date():
                    has_exception = True
                    if cal_date.exception_type == 1:  # Service added
                        operates = True
                        break
                    elif cal_date.exception_type == 2:  # Service removed
                        operates = False
                        break
            
            # If no exception found, check regular calendar
            if not has_exception and service_id in self._feed.calendars:
                calendar = self._feed.calendars[service_id]
                if calendar.start_date.date() <= date.date() <= calendar.end_date.date():
                    weekday = date.strftime("%A").lower()
                    operates = getattr(calendar, weekday)
            
            # If this trip operates, the route operates
            if operates:
                return True
        
        # No trips operate on this date
        return False

    def get_trip_stops_between(self, trip: 'Trip', start_id: str, end_id: str) -> List[RouteStop]:
        """Get all stops between (and including) the start and end stops for a specific trip"""
        if not self._feed:
            return []
            
        # Get all stop times for this trip
        stop_times = sorted(trip.stop_times, key=lambda x: x.stop_sequence)
        stops = [
            RouteStop(
                stop=self._feed.stops[st.stop_id],
                arrival_time=st.arrival_time,
                departure_time=st.departure_time,
                stop_sequence=st.stop_sequence
            )
            for st in stop_times
        ]
        
        try:
            start_idx = next(i for i, s in enumerate(stops) if s.stop.id == start_id)
            end_idx = next(i for i, s in enumerate(stops) if s.stop.id == end_id)
            if start_idx <= end_idx:
                return stops[start_idx:end_idx + 1]
        except StopIteration:
            pass
        return []

@dataclass
class Trip:
    """
    Represents a trip from trips.txt
    STIB: route_id, service_id, trip_id, trip_headsign, direction_id, block_id, shape_id
    Flixbus: route_id, trip_id, service_id, trip_headsign, block_id, shape_id
    """
    id: str
    route_id: str
    service_id: str
    headsign: Optional[str] = None
    direction_id: Optional[str] = None
    block_id: Optional[str] = None
    shape_id: Optional[str] = None
    stop_times: List['StopTime'] = field(default_factory=list)

@dataclass
class StopTime:
    """
    Represents a stop time from stop_times.txt
    STIB: trip_id, arrival_time, departure_time, stop_id, stop_sequence
    Flixbus: trip_id, stop_id, arrival_time, departure_time, stop_sequence
    """
    trip_id: str
    stop_id: str
    arrival_time: str
    departure_time: str
    stop_sequence: int

@dataclass
class Calendar:
    """
    Represents a service calendar from calendar.txt
    Both: service_id, monday-sunday (0/1), start_date, end_date
    """
    service_id: str
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    start_date: datetime
    end_date: datetime

@dataclass
class CalendarDate:
    """
    Represents a calendar exception from calendar_dates.txt
    Both: service_id, date, exception_type (1=added, 2=removed)
    """
    service_id: str
    date: datetime
    exception_type: int  # 1 = service added, 2 = service removed

@dataclass
class Translation:
    """
    Represents a translation from translations.txt (STIB specific)
    trans_id/record_id, translation, lang
    """
    record_id: str
    translation: str
    language: str



@dataclass
class FlixbusFeed:
    """Main container for GTFS data"""
    stops: Dict[str, Stop]
    routes: Dict[str, Route]
    trips: Dict[str, Trip]
    calendars: Dict[str, Calendar]
    calendar_dates: List[CalendarDate]
    shapes: Dict[str, Shape] = field(default_factory=dict)  # shape_id -> Shape
    translations: Dict[str, Dict[str, str]] = field(default_factory=dict)  # record_id -> (lang -> translation)

    def __iter__(self):
        """Make routes iterable for backward compatibility"""
        return iter(self.routes.values())

    @property
    def all_routes(self) -> List[Route]:
        """Get all routes as a list of Route objects"""
        return list(self.routes.values())

    def get_route_by_id(self, route_id: str) -> Optional[Route]:
        return self.routes.get(route_id)

    def get_stop_by_id(self, stop_id: str) -> Optional[Stop]:
        return self.stops.get(stop_id)

    def get_trip_by_id(self, trip_id: str) -> Optional[Trip]:
        return self.trips.get(trip_id)

    def get_stop_name(self, stop_id: str, language: Optional[str] = None) -> Optional[str]:
        stop = self.get_stop_by_id(stop_id)
        if not stop:
            return None
        if language and stop_id in self.translations:
            return self.translations[stop_id].get(language, stop.name)
        return stop.name

    def find_routes_between_stations(self, start_id: str, end_id: str) -> List[Route]:
        """Find all routes between two stations in the specified direction"""
        matching_routes = []
        
        for route in self.routes.values():
            for trip in route.trips:
                # Get stop sequences
                stop_ids = [st.stop_id for st in sorted(trip.stop_times, key=lambda x: x.stop_sequence)]
                
                # Check if both stations are in this trip and in the correct order
                try:
                    start_idx = stop_ids.index(start_id)
                    end_idx = stop_ids.index(end_id)
                    if start_idx < end_idx:  # Correct direction
                        matching_routes.append(route)
                        break  # Found a matching trip for this route, no need to check others
                except ValueError:
                    continue  # One or both stops not in this trip
                    
        return matching_routes

def load_translations(data_dir: Path) -> Dict[str, Dict[str, str]]:
    """Load translations if available (STIB specific)"""
    translations = {}
    translations_file = data_dir / 'translations.txt'
    
    if translations_file.exists():
        df = pd.read_csv(translations_file)
        for _, row in df.iterrows():
            record_id = str(row.get('record_id', row.get('trans_id')))
            lang = str(row['lang'])
            translation = str(row['translation'])
            
            if record_id not in translations:
                translations[record_id] = {}
            translations[record_id][lang] = translation
    
    return translations

def load_stops(data_dir: Path, translations: Dict[str, Dict[str, str]]) -> Dict[str, Stop]:
    """Load stops with translations if available"""
    stops = {}
    stops_df = pd.read_csv(data_dir / 'stops.txt')
    
    for _, row in stops_df.iterrows():
        stop_id = str(row['stop_id'])
        stop = Stop(
            id=stop_id,
            name=row['stop_name'],
            lat=float(row['stop_lat']),
            lon=float(row['stop_lon']),
            location_type=int(row['location_type']) if 'location_type' in row and pd.notna(row['location_type']) else None,
            parent_station=str(row['parent_station']) if 'parent_station' in row and pd.notna(row['parent_station']) else None,
            platform_code=str(row['platform_code']) if 'platform_code' in row and pd.notna(row['platform_code']) else None,
            timezone=str(row['stop_timezone']) if 'stop_timezone' in row and pd.notna(row['stop_timezone']) else None,
            translations=translations.get(stop_id, {})
        )
        stops[stop_id] = stop
    
    return stops

def load_routes(data_dir: Path) -> Dict[str, Route]:
    """Load routes with provider-specific handling"""
    routes = {}
    routes_df = pd.read_csv(data_dir / 'routes.txt')
    
    print("\nLoading routes:")
    print(f"Columns in routes.txt: {routes_df.columns.tolist()}")
    
    for _, row in routes_df.iterrows():
        route_id = str(row['route_id'])
        short_name = str(row['route_short_name']) if pd.notna(row['route_short_name']) else ''
        color = str(row['route_color']) if 'route_color' in row and pd.notna(row['route_color']) else None
        text_color = str(row['route_text_color']) if 'route_text_color' in row and pd.notna(row['route_text_color']) else None
        
        # print(f"\nRoute {route_id}:")
        # print(f"- Short name: {short_name}")
        # print(f"- Color: {color}")
        # print(f"- Text color: {text_color}")
        
        route = Route(
            id=route_id,
            short_name=short_name,
            long_name=str(row['route_long_name']) if pd.notna(row['route_long_name']) else '',
            route_type=int(row['route_type']),
            color=color,
            text_color=text_color,
            agency_id=str(row['agency_id']) if 'agency_id' in row and pd.notna(row['agency_id']) else None
        )
        routes[route_id] = route
    
    return routes

def load_trips(data_dir: Path) -> Dict[str, Trip]:
    """Load trips"""
    trips = {}
    trips_df = pd.read_csv(data_dir / 'trips.txt')
    
    for _, row in trips_df.iterrows():
        trip_id = str(row['trip_id'])
        trip = Trip(
            id=trip_id,
            route_id=str(row['route_id']),
            service_id=str(row['service_id']),
            headsign=str(row['trip_headsign']) if 'trip_headsign' in row and pd.notna(row['trip_headsign']) else None,
            direction_id=str(row['direction_id']) if 'direction_id' in row and pd.notna(row['direction_id']) else None,
            block_id=str(row['block_id']) if 'block_id' in row and pd.notna(row['block_id']) else None,
            shape_id=str(row['shape_id']) if 'shape_id' in row and pd.notna(row['shape_id']) else None
        )
        trips[trip_id] = trip
    
    return trips

def load_stop_times(data_dir: Path, trips: Dict[str, Trip]) -> None:
    """Load and associate stop times with trips"""
    stop_times_df = pd.read_csv(data_dir / 'stop_times.txt')
    
    for _, row in stop_times_df.iterrows():
        trip_id = str(row['trip_id'])
        if trip_id not in trips:
            continue
            
        stop_time = StopTime(
            trip_id=trip_id,
            stop_id=str(row['stop_id']),
            arrival_time=str(row['arrival_time']),
            departure_time=str(row['departure_time']),
            stop_sequence=int(row['stop_sequence'])
        )
        trips[trip_id].stop_times.append(stop_time)

def load_calendars(data_dir: Path) -> Dict[str, Calendar]:
    """Load service calendars"""
    calendars = {}
    calendar_file = data_dir / 'calendar.txt'
    
    if calendar_file.exists():
        df = pd.read_csv(calendar_file)
        for _, row in df.iterrows():
            service_id = str(row['service_id'])
            calendars[service_id] = Calendar(
                service_id=service_id,
                monday=bool(row['monday']),
                tuesday=bool(row['tuesday']),
                wednesday=bool(row['wednesday']),
                thursday=bool(row['thursday']),
                friday=bool(row['friday']),
                saturday=bool(row['saturday']),
                sunday=bool(row['sunday']),
                start_date=datetime.strptime(str(row['start_date']), '%Y%m%d'),
                end_date=datetime.strptime(str(row['end_date']), '%Y%m%d')
            )
    
    return calendars

def load_calendar_dates(data_dir: Path) -> List[CalendarDate]:
    """Load calendar exceptions"""
    exceptions = []
    calendar_dates_file = data_dir / 'calendar_dates.txt'
    
    if calendar_dates_file.exists():
        df = pd.read_csv(calendar_dates_file)
        for _, row in df.iterrows():
            exceptions.append(CalendarDate(
                service_id=str(row['service_id']),
                date=datetime.strptime(str(row['date']), '%Y%m%d'),
                exception_type=int(row['exception_type'])
            ))
    
    return exceptions

def load_shapes(data_dir: Path) -> Dict[str, Shape]:
    """Load shapes from shapes.txt if available"""
    shapes: Dict[str, Dict[int, Tuple[float, float]]] = {}  # shape_id -> (sequence -> point)
    shapes_file = data_dir / 'shapes.txt'
    
    if shapes_file.exists():
        df = pd.read_csv(shapes_file)
        for _, row in df.iterrows():
            shape_id = str(row['shape_id'])
            sequence = int(row['shape_pt_sequence'])
            lat = float(row['shape_pt_lat'])
            lon = float(row['shape_pt_lon'])
            
            if shape_id not in shapes:
                shapes[shape_id] = {}
            shapes[shape_id][sequence] = (lat, lon)
    
    # Convert to Shape objects with ordered points
    return {
        shape_id: Shape(
            shape_id=shape_id,
            points=[point for _, point in sorted(points.items())]
        )
        for shape_id, points in shapes.items()
    }

def calculate_gtfs_hash(data_dir: Path) -> str:
    """Calculate a hash of all GTFS files to detect changes"""
    hasher = hashlib.sha256()
    
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

def serialize_gtfs_data(feed: FlixbusFeed) -> bytes:
    """Serialize GTFS data to MessagePack format"""
    data = {
        'stops': {
            stop_id: {
                'id': stop.id,
                'name': stop.name,
                'lat': stop.lat,
                'lon': stop.lon,
                'location_type': stop.location_type,
                'parent_station': stop.parent_station,
                'platform_code': stop.platform_code,
                'timezone': stop.timezone,
                'translations': stop.translations
            }
            for stop_id, stop in feed.stops.items()
        },
        'routes': {
            route_id: {
                'id': route.id,
                'short_name': route.short_name,
                'long_name': route.long_name,
                'route_type': route.route_type,
                'color': route.color,
                'text_color': route.text_color,
                'agency_id': route.agency_id
            }
            for route_id, route in feed.routes.items()
        },
        'trips': {
            trip_id: {
                'id': trip.id,
                'route_id': trip.route_id,
                'service_id': trip.service_id,
                'headsign': trip.headsign,
                'direction_id': trip.direction_id,
                'block_id': trip.block_id,
                'shape_id': trip.shape_id,
                'stop_times': [
                    {
                        'trip_id': st.trip_id,
                        'stop_id': st.stop_id,
                        'arrival_time': st.arrival_time,
                        'departure_time': st.departure_time,
                        'stop_sequence': st.stop_sequence
                    }
                    for st in trip.stop_times
                ]
            }
            for trip_id, trip in feed.trips.items()
        },
        'shapes': {
            shape_id: {
                'shape_id': shape.shape_id,
                'points': shape.points
            }
            for shape_id, shape in feed.shapes.items()
        },
        'calendars': {
            cal_id: {
                'service_id': cal.service_id,
                'monday': cal.monday,
                'tuesday': cal.tuesday,
                'wednesday': cal.wednesday,
                'thursday': cal.thursday,
                'friday': cal.friday,
                'saturday': cal.saturday,
                'sunday': cal.sunday,
                'start_date': cal.start_date.isoformat(),
                'end_date': cal.end_date.isoformat()
            }
            for cal_id, cal in feed.calendars.items()
        },
        'calendar_dates': [
            {
                'service_id': cal.service_id,
                'date': cal.date.isoformat(),
                'exception_type': cal.exception_type
            }
            for cal in feed.calendar_dates
        ]
    }
        # First pack with MessagePack
    packed_data = msgpack.packb(data, use_bin_type=True)
    
    # Then compress with LZMA using optimized settings
    # preset=6 offers good compression while being faster than max compression
    # format=lzma.FORMAT_XZ for better compatibility
    # filters=[{"id": lzma.FILTER_LZMA2, "preset": 6}] for optimized compression
    return lzma.compress(
        packed_data,
        format=lzma.FORMAT_XZ,
        filters=[{"id": lzma.FILTER_LZMA2, "preset": 6}]
    )

def deserialize_gtfs_data(data: bytes) -> FlixbusFeed:
    """Deserialize GTFS data from compressed MessagePack format"""
    # First decompress LZMA
    decompressed_data = lzma.decompress(data)
    
    # Then unpack MessagePack
    raw_data = msgpack.unpackb(decompressed_data, raw=False)
    
    # Reconstruct objects
    stops = {
        stop_id: Stop(**stop_data)
        for stop_id, stop_data in raw_data['stops'].items()
    }
    
    routes = {
        route_id: Route(**route_data)
        for route_id, route_data in raw_data['routes'].items()
    }
    
    trips = {
        trip_id: Trip(**{k: v for k, v in trip_data.items() if k != 'stop_times'})
        for trip_id, trip_data in raw_data['trips'].items()
    }
    
    # Add stop times to trips
    for trip_id, trip_data in raw_data['trips'].items():
        trips[trip_id].stop_times = [
            StopTime(**st_data)
            for st_data in trip_data['stop_times']
        ]
    
    shapes = {
        shape_id: Shape(**shape_data)
        for shape_id, shape_data in raw_data['shapes'].items()
    }
    
    calendars = {
        cal_id: Calendar(
            **{k: v if k not in ['start_date', 'end_date'] else datetime.fromisoformat(v)
               for k, v in cal_data.items()}
        )
        for cal_id, cal_data in raw_data['calendars'].items()
    }
    
    calendar_dates = [
        CalendarDate(
            service_id=cal['service_id'],
            date=datetime.fromisoformat(cal['date']),
            exception_type=cal['exception_type']
        )
        for cal in raw_data['calendar_dates']
    ]
    
    # Create feed instance
    feed = FlixbusFeed(
        stops=stops,
        routes=routes,
        trips=trips,
        calendars=calendars,
        calendar_dates=calendar_dates,
        shapes=shapes
    )
    
    # Associate trips with routes and set feed reference
    for trip in trips.values():
        if trip.route_id in routes:
            route = routes[trip.route_id]
            route.trips.append(trip)
            route._feed = feed
    
    return feed





def load_feed(data_dir: str = None) -> FlixbusFeed:
    """Load GTFS data with caching"""
    if not data_dir:
        data_dir = os.getenv('GTFS_DATA_DIR', 'gtfs_generic_eu')
    data_dir = Path(data_dir)
    
    # Calculate hash of GTFS files
    gtfs_hash = calculate_gtfs_hash(data_dir)
    cache_file = data_dir / '.gtfs_cache'
    cache_hash_file = data_dir / '.gtfs_cache_hash'
    
    # Check if cache exists and is valid
    if cache_file.exists() and cache_hash_file.exists():
        stored_hash = cache_hash_file.read_text().strip()
        if stored_hash == gtfs_hash:
            try:
                # Load from cache
                with cache_file.open('rb') as f:
                    return deserialize_gtfs_data(f.read())
            except Exception as e:
                print(f"Error loading cache: {e}")
                # Continue to load from GTFS files
    
    # Load from GTFS files
    translations = load_translations(data_dir)
    stops = load_stops(data_dir, translations)
    routes = load_routes(data_dir)
    trips = load_trips(data_dir)
    shapes = load_shapes(data_dir)
    load_stop_times(data_dir, trips)
    calendars = load_calendars(data_dir)
    calendar_dates = load_calendar_dates(data_dir)
    
    # Create feed instance
    feed = FlixbusFeed(
        stops=stops,
        routes=routes,
        trips=trips,
        calendars=calendars,
        calendar_dates=calendar_dates,
        shapes=shapes,
        translations=translations
    )
    
    # Associate trips with routes and set feed reference
    for trip in trips.values():
        if trip.route_id in routes:
            route = routes[trip.route_id]
            route.trips.append(trip)
            route._feed = feed
    
    # Save to cache
    try:
        with cache_file.open('wb') as f:
            f.write(serialize_gtfs_data(feed))
        cache_hash_file.write_text(gtfs_hash)
    except Exception as e:
        print(f"Error saving cache: {e}")
    
    return feed 