"""
GTFS loader using DuckDB and Parquet for efficient storage and querying.
This implementation focuses on memory efficiency and fast loading times,
particularly for resource-constrained environments like Raspberry Pi.
"""

import logging
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
import pandas as pd
import os

from .gtfs_models import (
    Translation,
    Stop,
    RouteStop,
    Shape,
    StopTime,
    Trip,
    Calendar,
    CalendarDate,
    Route,
    FlixbusFeed,
)

logger = logging.getLogger("schedule_explorer.gtfs_parquet")



def load_translations(gtfs_dir: Path) -> Dict[str, Dict[str, str]]:
    """
    Load translations from translations.txt if it exists.
    Handles both translation formats:
    1. Simple format: trans_id,translation,lang
    2. Table-based format: table_name,field_name,language,translation,record_id[,record_sub_id,field_value]

    Returns a dictionary mapping stop_id to a dictionary of language codes to translations.
    """
    translations_file = gtfs_dir / "translations.txt"
    if not translations_file.exists():
        logger.warning(f"No translations file found at {translations_file}")
        return {}

    translations: Dict[str, Dict[str, str]] = {}
    
    try:
        # First, determine which format we're dealing with by reading the header
        with open(translations_file, "r", encoding="utf-8") as f:
            header = f.readline().strip().split(",")

        db = duckdb.connect(":memory:")

        if "table_name" in header:  # Table-based format
            logger.info("Using table-based format for translations")

            # Load translations and stops
            db.execute(f"""
                CREATE VIEW translations AS 
                SELECT * FROM read_csv_auto('{translations_file}', header=true);
                
                CREATE VIEW stops AS 
                SELECT * FROM read_csv_auto('{gtfs_dir}/stops.txt', header=true);
            """)

            # Filter for stop name translations and join with stops
            db.execute("""
                WITH stop_translations AS (
                    SELECT 
                        COALESCE(field_value, record_id) as original_name,
                        language,
                        translation
                    FROM translations
                    WHERE table_name = 'stops' 
                    AND field_name = 'stop_name'
                    AND translation IS NOT NULL
                    AND language IS NOT NULL
                ),
                name_to_ids AS (
                    SELECT 
                        stop_name,
                        stop_id::VARCHAR as stop_id
                    FROM stops
                )
                SELECT 
                    n.stop_id,
                    t.language,
                    t.translation
                FROM stop_translations t
                JOIN name_to_ids n ON t.original_name = n.stop_name;
            """)
            result = db.fetchdf()

        else:  # Simple format
            logger.info("Using simple format for translations")

            # Load translations and stops
            db.execute(f"""
                CREATE VIEW translations AS 
                SELECT * FROM read_csv_auto('{translations_file}', header=true);
                
                CREATE VIEW stops AS 
                SELECT * FROM read_csv_auto('{gtfs_dir}/stops.txt', header=true);
            """)

            # Join translations with stops based on stop_name matching trans_id
            db.execute("""
                SELECT 
                    s.stop_id::VARCHAR as stop_id,
                    t.lang as language,
                    t.translation
                FROM stops s
                JOIN translations t ON s.stop_name = t.trans_id
                WHERE t.translation IS NOT NULL 
                AND t.lang IS NOT NULL;
            """)
            result = db.fetchdf()

        # Process results into the required format
        for _, row in result.iterrows():
            stop_id = str(row['stop_id'])
            if stop_id not in translations:
                translations[stop_id] = {}
            translations[stop_id][row['language']] = row['translation']

        logger.info(f"Created translations map with {len(translations)} entries")
        return translations

    except Exception as e:
        logger.warning(f"Error loading translations: {e}")
        return {}

class ParquetGTFSLoader:
    """
    Loads and manages GTFS data using Parquet files and DuckDB for efficient querying.
    """
    
    def __init__(self, data_dir: str | Path = None):
        """Initialize the loader with the GTFS data directory."""
        self.data_dir = Path(data_dir) if data_dir else Path.cwd()
        self.db = duckdb.connect(":memory:")
        self.stops = {}
        self.routes = {}
        self.translations = {}
        
    def _setup_db(self):
        """Set up DuckDB configuration for optimal performance."""
        # Configure memory limits based on available system memory
        total_memory = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
        memory_limit = max(128 * 1024 * 1024, total_memory // 8)  # Use 12.5% of system memory or at least 128MB
        
        self.db.execute(f"SET memory_limit='{memory_limit}B'")
        self.db.execute("SET enable_progress_bar=false")
        self.db.execute("PRAGMA threads=4")  # Limit thread usage
        self.db.execute("PRAGMA memory_limit='1GB'")  # Hard limit
        self.db.execute("PRAGMA temp_directory='.tmp'")  # Use temp directory for spilling
    
    def _csv_to_parquet(self, filename: str) -> Optional[Path]:
        """Convert a CSV file to Parquet format using DuckDB."""
        csv_path = self.data_dir / filename
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return None
        
        try:
            # Create a temporary table from the CSV
            table_name = f"temp_{filename.replace('.', '_')}"
            self.db.execute(f"""
                CREATE TABLE {table_name} AS 
                SELECT * FROM read_csv_auto('{csv_path}', header=true, sample_size=1000)
            """)
            
            # Write to Parquet using DuckDB's COPY command
            parquet_path = self.data_dir / f"{filename}.parquet"
            self.db.execute(f"""
                COPY {table_name} TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY')
            """)
            
            # Drop temporary table
            self.db.execute(f"DROP TABLE {table_name}")
            
            return parquet_path
        except Exception as e:
            logger.error(f"Error converting {filename} to Parquet: {e}")
            return None
    
    def _load_stops(self) -> None:
        """Load stops from stops.txt into memory."""
        parquet_path = self._csv_to_parquet("stops.txt")
        if not parquet_path:
            return

        # Read stops from Parquet file
        query = """
            SELECT 
                stop_id,
                stop_name,
                stop_lat,
                stop_lon,
                COALESCE(location_type, NULL) as location_type,
                COALESCE(parent_station, NULL) as parent_station,
                COALESCE(platform_code, NULL) as platform_code,
                COALESCE(stop_timezone, NULL) as timezone
            FROM read_parquet(?)
        """
        result = self.db.execute(query, [str(parquet_path)]).fetchdf()
        
        # Create Stop objects
        for _, row in result.iterrows():
            stop = Stop(
                id=row["stop_id"],
                name=row["stop_name"],
                lat=row["stop_lat"],
                lon=row["stop_lon"],
                translations=self.translations.get(row["stop_id"], {}),
                location_type=None if pd.isna(row["location_type"]) else row["location_type"],
                parent_station=None if pd.isna(row["parent_station"]) else row["parent_station"],
                platform_code=None if pd.isna(row["platform_code"]) else row["platform_code"],
                timezone=None if pd.isna(row["timezone"]) else row["timezone"]
            )
            self.stops[stop.id] = stop
    
    def _load_stop_times(self) -> None:
        """Load stop times data into DuckDB using parallel processing."""
        parquet_path = self._csv_to_parquet('stop_times.txt')
        if not parquet_path:
            return
            
        # Use multiple threads but limit based on available memory
        num_threads = min(2, os.cpu_count() or 1)  # Conservative for RPi
            
        self.db.execute(f"""
            CREATE TABLE stop_times AS 
            SELECT 
                trip_id,
                arrival_time,
                departure_time,
                stop_id,
                CAST(stop_sequence AS INTEGER) as stop_sequence
            FROM parquet_scan('{parquet_path}')
            /*+ PARALLEL({num_threads}) */
        """)
        
        # Create optimized indices for route search
        self.db.execute(f"""
            CREATE INDEX idx_stop_times_trip_stop ON stop_times(trip_id, stop_id)
            /*+ PARALLEL({num_threads}) */
        """)
        self.db.execute(f"""
            CREATE INDEX idx_stop_times_stop_seq ON stop_times(stop_id, stop_sequence)
            /*+ PARALLEL({num_threads}) */
        """)
    
    def _load_trips(self) -> None:
        """Load trips data into DuckDB."""
        parquet_path = self._csv_to_parquet('trips.txt')
        if not parquet_path:
            return
            
        # First load all columns
        self.db.execute(f"""
            CREATE TABLE trips AS 
            WITH raw_trips AS (
                SELECT * FROM parquet_scan('{parquet_path}')
            )
            SELECT 
                route_id,
                service_id,
                trip_id,
                trip_headsign,
                direction_id,
                block_id,
                shape_id
            FROM raw_trips
        """)
        
        # Create indices
        self.db.execute("CREATE INDEX idx_trips_id ON trips(trip_id)")
        self.db.execute("CREATE INDEX idx_trips_route_id ON trips(route_id)")
    
    def _load_routes(self) -> List[Route]:
        """Load routes from the database and create Route objects.
        
        Returns:
            List of Route objects.
        """
        # First load routes into DuckDB
        parquet_path = self._csv_to_parquet('routes.txt')
        if not parquet_path:
            return []
        
        # Create routes table
        self.db.execute(f"""
            CREATE TABLE routes AS 
            SELECT 
                route_id,
                route_short_name,
                route_long_name,
                route_type,
                route_color,
                route_text_color,
                agency_id
            FROM parquet_scan('{parquet_path}')
        """)
        
        # Create index
        self.db.execute("CREATE INDEX idx_routes_id ON routes(route_id)")
        
        # Get all routes with their trips
        query = """
            SELECT 
                r.route_id,
                r.route_long_name,
                r.route_short_name,
                r.route_type,
                r.route_color,
                r.route_text_color,
                r.agency_id,
                t.trip_id,
                t.service_id,
                t.trip_headsign,
                t.direction_id,
                t.shape_id
            FROM routes r
            JOIN trips t ON r.route_id = t.route_id
            ORDER BY r.route_id, t.direction_id
        """
        result = self.db.execute(query).fetchdf()
        
        # Group by route_id and direction_id
        routes = []
        for (route_id, direction_id), group in result.groupby(['route_id', 'direction_id']):
            first_row = group.iloc[0]
            trip_id = first_row['trip_id']
            
            # Get stops for this trip
            route_stops = self._create_route_stops(trip_id)
            if not route_stops:
                continue
            
            # Get service days for this route
            service_ids = set(group['service_id'].dropna())
            service_days = self._get_service_days(service_ids)
            if not service_days:
                continue
            
            # Create trips for this route
            trips = []
            for _, row in group.iterrows():
                trip = Trip(
                    id=row['trip_id'],
                    route_id=row['route_id'],
                    service_id=row['service_id'],
                    headsign=row['trip_headsign'] if pd.notna(row['trip_headsign']) else None,
                    direction_id=str(row['direction_id']) if pd.notna(row['direction_id']) else None,
                    shape_id=row['shape_id'] if pd.notna(row['shape_id']) else None
                )
                trips.append(trip)
            
            # Create route object
            route = Route(
                route_id=route_id,
                route_name=first_row['route_long_name'] if pd.notna(first_row['route_long_name']) else first_row['route_short_name'],
                trip_id=trip_id,
                stops=route_stops,
                service_days=service_days,
                short_name=first_row['route_short_name'] if pd.notna(first_row['route_short_name']) else None,
                long_name=first_row['route_long_name'] if pd.notna(first_row['route_long_name']) else None,
                route_type=first_row['route_type'] if pd.notna(first_row['route_type']) else None,
                color=first_row['route_color'] if pd.notna(first_row['route_color']) else None,
                text_color=first_row['route_text_color'] if pd.notna(first_row['route_text_color']) else None,
                agency_id=first_row['agency_id'] if pd.notna(first_row['agency_id']) else None,
                direction_id=str(direction_id) if pd.notna(direction_id) else None,
                service_ids=list(service_ids),
                trips=trips
            )
            routes.append(route)
        
        return routes
    
    def _create_route_stops(self, trip_id: str) -> List[RouteStop]:
        """Create RouteStop objects for a trip.
        
        Args:
            trip_id: The trip ID to get stops for.
            
        Returns:
            List of RouteStop objects ordered by stop_sequence.
        """
        # Get stop times for this trip
        query = """
            SELECT 
                stop_id,
                arrival_time,
                departure_time,
                CAST(stop_sequence AS INTEGER) as stop_sequence
            FROM stop_times
            WHERE trip_id = ?
            ORDER BY stop_sequence
        """
        result = self.db.execute(query, [trip_id]).fetchdf()
        
        if result.empty:
            return []
        
        # Create RouteStop objects
        route_stops = []
        for _, row in result.iterrows():
            stop_id = row['stop_id']
            if stop_id not in self.stops:
                logger.warning(f"Stop {stop_id} not found in stops dictionary")
                continue
                
            route_stop = RouteStop(
                stop=self.stops[stop_id],
                arrival_time=row['arrival_time'],
                departure_time=row['departure_time'],
                stop_sequence=int(row['stop_sequence'])  # Ensure integer type
            )
            route_stops.append(route_stop)
        
        return route_stops
    
    def _load_calendar(self) -> None:
        """Load calendar data into DuckDB using parallel processing."""
        calendar_path = self._csv_to_parquet('calendar.txt')
        calendar_dates_path = self._csv_to_parquet('calendar_dates.txt')
        
        # Use multiple threads but limit based on available memory
        num_threads = min(2, os.cpu_count() or 1)  # Conservative for RPi
        
        if calendar_path:
            self.db.execute(f"""
                CREATE TABLE calendar AS 
                SELECT 
                    service_id,
                    monday, tuesday, wednesday, thursday, friday, saturday, sunday,
                    start_date,
                    end_date
                FROM parquet_scan('{calendar_path}')
                /*+ PARALLEL({num_threads}) */
            """)
            self.db.execute(f"""
                CREATE INDEX idx_calendar_service_id ON calendar(service_id)
                /*+ PARALLEL({num_threads}) */
            """)
        
        if calendar_dates_path:
            # Process calendar_dates in chunks to avoid memory issues
            self.db.execute(f"""
                CREATE TABLE calendar_dates AS 
                SELECT 
                    service_id,
                    date,
                    exception_type
                FROM parquet_scan('{calendar_dates_path}')
                /*+ PARALLEL({num_threads}) */
            """)
            self.db.execute(f"""
                CREATE INDEX idx_calendar_dates_service_id ON calendar_dates(service_id)
                /*+ PARALLEL({num_threads}) */
            """)
    
    def load_feed(self) -> Optional[FlixbusFeed]:
        """Load the GTFS feed into DuckDB and return a FlixbusFeed object."""
        logger.info("Loading GTFS feed into DuckDB...")
        
        try:
            # Load translations first
            self.translations = load_translations(self.data_dir)
            
            # Load all components
            self._load_stops()
            self._load_stop_times()
            self._load_trips()
            
            # Load routes
            routes = self._load_routes()
            
            logger.info("GTFS feed loaded successfully")
            return FlixbusFeed(
                stops=self.stops,
                routes=routes,
                translations=self.translations
            )
        except Exception as e:
            logger.error(f"Error loading GTFS feed: {e}")
            return None
    
    def find_routes_between_stations(self, start_id: str, end_id: str) -> List[Dict]:
        """Find all routes between two stations."""
        query = """
        WITH RECURSIVE 
        stop_pairs AS (
            -- Find all possible stop time pairs for the stations
            SELECT 
                st1.trip_id,
                st1.stop_sequence as start_seq,
                st2.stop_sequence as end_seq,
                st1.departure_time as start_time,
                st2.arrival_time as end_time
            FROM stop_times st1
            JOIN stop_times st2 ON st1.trip_id = st2.trip_id 
                AND st1.stop_sequence < st2.stop_sequence
            WHERE st1.stop_id = ?
                AND st2.stop_id = ?
        ),
        valid_trips AS (
            -- Get valid trips with their route info
            SELECT DISTINCT 
                sp.trip_id,
                t.route_id,
                sp.start_seq,
                sp.end_seq,
                sp.start_time,
                sp.end_time
            FROM stop_pairs sp
            JOIN trips t ON t.trip_id = sp.trip_id
        ),
        route_stops AS (
            -- Get all intermediate stops for valid trips
            SELECT 
                vt.trip_id,
                vt.route_id,
                st.stop_sequence,
                st.stop_id,
                st.arrival_time,
                st.departure_time
            FROM valid_trips vt
            JOIN stop_times st ON st.trip_id = vt.trip_id
                AND st.stop_sequence BETWEEN vt.start_seq AND vt.end_seq
        ),
        route_details AS (
            -- Combine with route and stop information
            SELECT 
                r.route_id,
                r.route_short_name,
                r.route_long_name,
                t.trip_id,
                t.trip_headsign,
                rs.stop_sequence,
                rs.stop_id,
                s.stop_name,
                s.stop_lat,
                s.stop_lon,
                rs.arrival_time,
                rs.departure_time
            FROM route_stops rs
            JOIN trips t ON t.trip_id = rs.trip_id
            JOIN routes r ON r.route_id = rs.route_id
            JOIN stops s ON s.stop_id = rs.stop_id
        )
        SELECT * FROM route_details
        ORDER BY trip_id, stop_sequence
        """
        
        try:
            result = self.db.execute(query, [start_id, end_id]).fetchdf()
            return self._process_route_results(result)
        except Exception as e:
            logger.error(f"Error finding routes between stations: {e}")
            return []
    
    def _process_route_results(self, df: pd.DataFrame) -> List[Dict]:
        """Process the route search results into a structured format."""
        if df.empty:
            return []
            
        routes = []
        for trip_id in df['trip_id'].unique():
            trip_df = df[df['trip_id'] == trip_id].copy()
            
            # Ensure stops are in sequence
            trip_df.sort_values('stop_sequence', inplace=True)
            
            route = {
                'route_id': trip_df['route_id'].iloc[0],
                'route_name': trip_df['route_long_name'].iloc[0] or trip_df['route_short_name'].iloc[0],
                'trip_id': trip_id,
                'headsign': trip_df['trip_headsign'].iloc[0],
                'stops': []
            }
            
            for _, row in trip_df.iterrows():
                # Create Stop object
                stop = Stop(
                    id=row['stop_id'],
                    name=row['stop_name'],
                    lat=float(row['stop_lat']),
                    lon=float(row['stop_lon']),
                    translations=self.stops[row['stop_id']].translations if row['stop_id'] in self.stops else {}
                )
                
                # Create RouteStop object
                route_stop = RouteStop(
                    stop=stop,
                    arrival_time=row['arrival_time'],
                    departure_time=row['departure_time'],
                    stop_sequence=int(row['stop_sequence'])
                )
                
                route['stops'].append(route_stop)
            
            routes.append(route)
        
        return routes
    
    def close(self):
        """Close the DuckDB connection."""
        if self.db:
            self.db.close()
            self.db = None 
    
    def _get_service_days(self, service_ids: Set[str]) -> Set[str]:
        """Get service days for a set of service IDs.
        
        Args:
            service_ids: Set of service IDs to get service days for.
            
        Returns:
            Set of service days.
        """
        service_days = set()
        for service_id in service_ids:
            # Check calendar.txt first
            calendar_query = """
                SELECT 
                    monday, tuesday, wednesday, thursday, friday, saturday, sunday
                FROM calendar
                WHERE service_id = ?
            """
            calendar_result = self.db.execute(calendar_query, [service_id]).fetchdf()
            
            if not calendar_result.empty:
                row = calendar_result.iloc[0]
                if row['monday']: service_days.add('monday')
                if row['tuesday']: service_days.add('tuesday')
                if row['wednesday']: service_days.add('wednesday')
                if row['thursday']: service_days.add('thursday')
                if row['friday']: service_days.add('friday')
                if row['saturday']: service_days.add('saturday')
                if row['sunday']: service_days.add('sunday')
            else:
                # Check calendar_dates.txt for type 1 exceptions
                calendar_dates_query = """
                    SELECT date
                    FROM calendar_dates
                    WHERE service_id = ? AND exception_type = 1
                """
                dates_result = self.db.execute(calendar_dates_query, [service_id]).fetchdf()
                for _, date_row in dates_result.iterrows():
                    weekday = datetime.strptime(str(date_row['date']), '%Y%m%d').strftime('%A').lower()
                    service_days.add(weekday)
        
        return service_days 