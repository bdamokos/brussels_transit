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

logger = logging.getLogger("schedule_explorer.gtfs_parquet")

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
        Convert a GTFS CSV file to Parquet format.
        Uses chunked reading to handle large files efficiently.
        
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
            # Use PyArrow for efficient conversion
            table = pa.csv.read_csv(
                csv_path,
                read_options=pa.csv.ReadOptions(
                    block_size=8192,  # 8KB chunks as recommended
                    use_threads=True
                ),
                convert_options=pa.csv.ConvertOptions(
                    strings_can_be_null=True,
                    include_columns=None  # Auto-detect
                )
            )
            
            # Write with optimized settings
            pq.write_table(
                table,
                parquet_path,
                compression='SNAPPY',  # Fast compression
                row_group_size=524288,  # 512KB row groups for RPi
                data_page_size=8192,   # 8KB pages as recommended
                use_dictionary=True,
                dictionary_pagesize_limit=512 * 1024  # 512KB
            )
            
            return parquet_path
            
        except Exception as e:
            logger.error(f"Error converting {file_name} to Parquet: {e}")
            if parquet_path.exists():
                parquet_path.unlink()
            return None
    
    def _load_stops(self) -> None:
        """Load stops data into DuckDB."""
        parquet_path = self._csv_to_parquet('stops.txt')
        if not parquet_path:
            return
            
        # First load all columns
        self.db.execute(f"""
            CREATE TABLE stops AS 
            WITH raw_stops AS (
                SELECT * FROM parquet_scan('{parquet_path}')
            )
            SELECT 
                stop_id,
                stop_name,
                CAST(stop_lat AS DOUBLE) as stop_lat,
                CAST(stop_lon AS DOUBLE) as stop_lon,
                location_type,
                parent_station,
                platform_code,
                stop_timezone
            FROM raw_stops
        """)
        
        # Create index
        self.db.execute("CREATE INDEX idx_stops_id ON stops(stop_id)")
    
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
        
        # Create indices in parallel
        self.db.execute(f"""
            CREATE INDEX idx_stop_times_trip_id ON stop_times(trip_id)
            /*+ PARALLEL({num_threads}) */
        """)
        self.db.execute(f"""
            CREATE INDEX idx_stop_times_stop_id ON stop_times(stop_id)
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
        """
        Find all routes between two stations.
        
        Args:
            start_id: Starting station ID
            end_id: Ending station ID
            
        Returns:
            List of routes connecting the stations
        """
        query = """
        WITH route_stops AS (
            SELECT DISTINCT
                r.route_id,
                r.route_short_name,
                r.route_long_name,
                t.trip_id,
                t.service_id,
                t.trip_headsign,
                st.stop_sequence,
                st.stop_id,
                st.arrival_time,
                st.departure_time,
                s.stop_name,
                s.stop_lat,
                s.stop_lon
            FROM routes r
            JOIN trips t ON t.route_id = r.route_id
            JOIN stop_times st ON st.trip_id = t.trip_id
            JOIN stops s ON s.stop_id = st.stop_id
        ),
        valid_trips AS (
            SELECT DISTINCT
                rs1.trip_id,
                rs1.route_id,
                rs1.route_short_name,
                rs1.route_long_name,
                rs1.trip_headsign,
                rs1.stop_sequence as start_seq,
                rs2.stop_sequence as end_seq
            FROM route_stops rs1
            JOIN route_stops rs2 ON rs1.trip_id = rs2.trip_id
            WHERE rs1.stop_id = ? 
            AND rs2.stop_id = ?
            AND rs1.stop_sequence < rs2.stop_sequence  -- Ensure correct direction
        ),
        trip_stops AS (
            SELECT 
                vt.*,
                rs.stop_id,
                rs.stop_name,
                rs.stop_lat,
                rs.stop_lon,
                rs.arrival_time,
                rs.departure_time,
                rs.stop_sequence
            FROM valid_trips vt
            JOIN route_stops rs ON rs.trip_id = vt.trip_id
            WHERE rs.stop_sequence BETWEEN vt.start_seq AND vt.end_seq
        )
        SELECT DISTINCT
            trip_id,
            route_id,
            route_short_name,
            route_long_name,
            trip_headsign,
            stop_id,
            stop_name,
            stop_lat,
            stop_lon,
            arrival_time,
            departure_time,
            stop_sequence
        FROM trip_stops
        ORDER BY trip_id, stop_sequence
        LIMIT 1000  -- Reasonable limit
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