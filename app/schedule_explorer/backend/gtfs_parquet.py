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
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import pandas as pd
import os

logger = logging.getLogger("schedule_explorer.gtfs_parquet")

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
    translations: Dict[str, str] = field(default_factory=dict)  # language -> translated name
    location_type: Optional[int] = None
    parent_station: Optional[str] = None
    platform_code: Optional[str] = None
    timezone: Optional[str] = None

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
    
    def __init__(self, data_dir: Path, cache_dir: Optional[Path] = None):
        """
        Initialize the loader with paths to GTFS data and cache directories.
        
        Args:
            data_dir: Directory containing GTFS txt files
            cache_dir: Directory for storing Parquet files (defaults to data_dir/.parquet)
        """
        self.data_dir = Path(data_dir)
        self.cache_dir = Path(cache_dir) if cache_dir else self.data_dir / ".parquet"
        self.cache_dir.mkdir(exist_ok=True)
        
        # Initialize DuckDB connection with optimized settings
        self.db = duckdb.connect(":memory:")
        self._setup_db()
        
        # Initialize data structures
        self.stops: Dict[str, Stop] = {}
    
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
    
    def _csv_to_parquet(self, file_name: str) -> Optional[Path]:
        """
        Convert a GTFS CSV file to Parquet format using DuckDB's native CSV reader.
        
        Args:
            file_name: Name of the GTFS file (e.g., 'stops.txt')
            
        Returns:
            Path to the Parquet file or None if conversion failed
        """
        csv_path = self.data_dir / file_name
        if not csv_path.exists():
            return None
            
        parquet_path = self.cache_dir / f"{file_name}.parquet"
        
        # Skip if Parquet file already exists
        if parquet_path.exists():
            return parquet_path
        
        try:
            # Use DuckDB's native CSV reader and Parquet writer
            self.db.execute(f"""
                COPY (
                    SELECT * FROM read_csv_auto('{csv_path}', 
                        header=true, 
                        sample_size=1000,
                        all_varchar=false)
                ) TO '{parquet_path}' (
                    FORMAT 'parquet',
                    COMPRESSION 'SNAPPY',
                    ROW_GROUP_SIZE 524288
                )
            """)
            
            return parquet_path
            
        except Exception as e:
            logger.error(f"Error converting {file_name} to Parquet: {e}")
            if parquet_path.exists():
                parquet_path.unlink()
            return None
    
    def _load_stops(self) -> None:
        """Load stops data into DuckDB and create Stop objects."""
        parquet_path = self._csv_to_parquet('stops.txt')
        if not parquet_path:
            return
            
        # Load translations first
        translations = load_translations(self.data_dir)
        logger.info(f"Loaded translations for {len(translations)} stops")
            
        # Load stops with all fields
        self.db.execute(f"""
            CREATE TABLE stops AS 
            WITH raw_stops AS (
                SELECT * FROM parquet_scan('{parquet_path}')
            )
            SELECT 
                stop_id::VARCHAR as stop_id,
                stop_name::VARCHAR as stop_name,
                CAST(stop_lat AS DOUBLE) as stop_lat,
                CAST(stop_lon AS DOUBLE) as stop_lon,
                TRY_CAST(location_type AS INTEGER) as location_type,
                NULLIF(parent_station, '') as parent_station,
                NULLIF(platform_code, '') as platform_code,
                NULLIF(stop_timezone, '') as stop_timezone
            FROM raw_stops
        """)
        
        # Create index for efficient lookups
        self.db.execute("CREATE INDEX idx_stops_id ON stops(stop_id)")
        
        # Load stops into memory as Stop objects
        result = self.db.execute("""
            SELECT * FROM stops
        """).fetchdf()
        
        # Create Stop objects
        for _, row in result.iterrows():
            stop = Stop(
                id=str(row['stop_id']),
                name=row['stop_name'],
                lat=float(row['stop_lat']),
                lon=float(row['stop_lon']),
                translations=translations.get(str(row['stop_id']), {}),
                location_type=int(row['location_type']) if pd.notna(row['location_type']) else None,
                parent_station=str(row['parent_station']) if pd.notna(row['parent_station']) else None,
                platform_code=str(row['platform_code']) if pd.notna(row['platform_code']) else None,
                timezone=str(row['stop_timezone']) if pd.notna(row['stop_timezone']) else None
            )
            self.stops[stop.id] = stop
            
        logger.info(f"Loaded {len(self.stops)} stops")
    
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
    
    def _load_routes(self) -> None:
        """Load routes data into DuckDB."""
        parquet_path = self._csv_to_parquet('routes.txt')
        if not parquet_path:
            return
            
        # First load all columns
        self.db.execute(f"""
            CREATE TABLE routes AS 
            WITH raw_routes AS (
                SELECT * FROM parquet_scan('{parquet_path}')
            )
            SELECT 
                route_id,
                route_short_name,
                route_long_name,
                route_type,
                route_color,
                route_text_color,
                agency_id
            FROM raw_routes
        """)
        
        # Create index
        self.db.execute("CREATE INDEX idx_routes_id ON routes(route_id)")
    
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
    
    def load_feed(self) -> None:
        """Load all GTFS data into DuckDB."""
        logger.info("Loading GTFS feed into DuckDB...")
        
        self._load_stops()
        self._load_routes()
        self._load_trips()
        self._load_stop_times()
        self._load_calendar()
        
        logger.info("GTFS feed loaded successfully")
    
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
                route['stops'].append({
                    'id': row['stop_id'],
                    'name': row['stop_name'],
                    'lat': float(row['stop_lat']),
                    'lon': float(row['stop_lon']),
                    'arrival_time': row['arrival_time'],
                    'departure_time': row['departure_time'],
                    'sequence': int(row['stop_sequence'])
                })
            
            routes.append(route)
        
        return routes
    
    def close(self):
        """Close the DuckDB connection."""
        if self.db:
            self.db.close()
            self.db = None 