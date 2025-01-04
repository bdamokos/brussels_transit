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
from typing import Dict, List, Optional, Set, Union
from datetime import datetime, timedelta
import pandas as pd
import os
import tempfile
import uuid
import shutil

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
from .models import BoundingBox, StationResponse, Location

logger = logging.getLogger("schedule_explorer.gtfs_parquet")



def load_translations(gtfs_dir: Path) -> Dict[str, Dict[str, str]]:
    """
    Load translations from translations.txt if it exists.
    Handles both translation formats:
    1. Simple format (STIB): trans_id,translation,lang
    2. Table-based format (SNCB): table_name,field_name,language,translation,record_id[,record_sub_id,field_value]

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
            logger.info(f"Translation file header: {header}")

        db = duckdb.connect(":memory:")

            # Load translations and stops
        logger.info(f"Loading translations from {translations_file}")
        logger.info(f"Loading stops from {gtfs_dir}/stops.txt")
        
        db.execute(f"""
                CREATE VIEW translations AS 
                SELECT * FROM read_csv_auto('{translations_file}', header=true);
                
                CREATE VIEW stops AS 
                SELECT * FROM read_csv_auto('{gtfs_dir}/stops.txt', header=true);
            """)

        # Sample the data to understand what we're working with
        trans_sample = db.execute("SELECT * FROM translations LIMIT 5").fetchdf()
        stops_sample = db.execute("SELECT * FROM stops LIMIT 5").fetchdf()
        logger.info(f"Translation sample:\n{trans_sample}")
        logger.info(f"Stops sample:\n{stops_sample}")

        if "table_name" in header:  # Table-based format (SNCB)
            logger.info("Using table-based format for translations")

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
            logger.info(f"Found {len(result)} table-based translations")

        else:  # Simple format (STIB)
            logger.info("Using simple format for translations")

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
            logger.info(f"Found {len(result)} simple format translations")

        # Process results into the required format
        for _, row in result.iterrows():
            stop_id = str(row['stop_id'])
            if stop_id not in translations:
                translations[stop_id] = {}
            translations[stop_id][row['language']] = row['translation']

        logger.info(f"Created translations map with {len(translations)} entries")
        # Log a sample of the translations
        sample_stops = list(translations.keys())[:5]
        for stop_id in sample_stops:
            logger.info(f"Sample translation for stop {stop_id}: {translations[stop_id]}")
        
        return translations

    except Exception as e:
        logger.error(f"Error loading translations: {e}", exc_info=True)
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
            # Validate data before conversion
            if filename == 'stop_times.txt':
                df = pd.read_csv(csv_path)
                negative_rows = df[(df[['stop_sequence', 'pickup_type', 'drop_off_type']] < 0).any(axis=1)]
                if not negative_rows.empty:
                    logger.warning(f"Negative values found in {filename}. Skipping {len(negative_rows)} rows.")
                    df = df.drop(negative_rows.index)
                    df.to_csv(csv_path, index=False)

            # Create a unique temporary directory for this process
            temp_dir = Path(tempfile.gettempdir()) / f"gtfs_parquet_{uuid.uuid4()}"
            temp_dir.mkdir(exist_ok=True)
            
            # Use the temporary directory for the parquet file
            parquet_path = temp_dir / f"{filename}.parquet"
            
            # Define column types based on the file
            column_types = {
                'stop_times.txt': {
                    'trip_id': 'VARCHAR',
                    'arrival_time': 'VARCHAR',  # Handle times > 24:00:00
                    'departure_time': 'VARCHAR',  # Handle times > 24:00:00
                    'stop_id': 'VARCHAR',
                    'stop_sequence': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'stop_headsign': 'VARCHAR',
                    'pickup_type': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'drop_off_type': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'continuous_pickup': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'continuous_drop_off': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'shape_dist_traveled': 'DOUBLE',
                    'timepoint': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'start_service_area_id': 'VARCHAR',
                    'end_service_area_id': 'VARCHAR',
                    'start_service_area_radius': 'DOUBLE',
                    'end_service_area_radius': 'DOUBLE',
                    'pickup_area_id': 'VARCHAR',
                    'drop_off_area_id': 'VARCHAR',
                    'pickup_service_area_radius': 'DOUBLE',
                    'drop_off_service_area_radius': 'DOUBLE'
                },
                'trips.txt': {
                    'route_id': 'VARCHAR',
                    'service_id': 'VARCHAR',
                    'trip_id': 'VARCHAR',
                    'trip_headsign': 'VARCHAR',
                    'trip_short_name': 'VARCHAR',
                    'direction_id': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'block_id': 'VARCHAR',
                    'shape_id': 'VARCHAR',
                    'wheelchair_accessible': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'bikes_allowed': 'BIGINT'  # Changed from INTEGER to BIGINT
                },
                'routes.txt': {
                    'agency_id': 'VARCHAR',
                    'route_id': 'VARCHAR',
                    'route_short_name': 'VARCHAR',
                    'route_long_name': 'VARCHAR',
                    'route_type': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'route_desc': 'VARCHAR',
                    'route_color': 'VARCHAR',
                    'route_text_color': 'VARCHAR',
                    'route_sort_order': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'route_url': 'VARCHAR',
                    'continuous_pickup': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'continuous_drop_off': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'network_id': 'VARCHAR'
                },
                'shapes.txt': {
                    'shape_id': 'VARCHAR',
                    'shape_pt_lat': 'DOUBLE',
                    'shape_pt_lon': 'DOUBLE',
                    'shape_pt_sequence': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'shape_dist_traveled': 'DOUBLE'
                },
                'stops.txt': {
                    'stop_id': 'VARCHAR',
                    'stop_code': 'VARCHAR',
                    'stop_name': 'VARCHAR',
                    'stop_desc': 'VARCHAR',
                    'stop_lat': 'DOUBLE',
                    'stop_lon': 'DOUBLE',
                    'zone_id': 'VARCHAR',
                    'stop_url': 'VARCHAR',
                    'location_type': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'parent_station': 'VARCHAR',
                    'stop_timezone': 'VARCHAR',
                    'wheelchair_boarding': 'INTEGER',
                    'level_id': 'VARCHAR',
                    'platform_code': 'VARCHAR',
                    'entrance_restriction': 'INTEGER',
                    'exit_restriction': 'INTEGER',
                    'entry_doors': 'VARCHAR',
                    'exit_doors': 'VARCHAR',
                    'signposted_as': 'VARCHAR',
                    'tts_stop_name': 'VARCHAR'
                },
                'calendar.txt': {
                    'service_id': 'VARCHAR',
                    'monday': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'tuesday': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'wednesday': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'thursday': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'friday': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'saturday': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'sunday': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'start_date': 'VARCHAR',
                    'end_date': 'VARCHAR'
                },
                'calendar_dates.txt': {
                    'service_id': 'VARCHAR',
                    'date': 'VARCHAR',
                    'exception_type': 'BIGINT'  # Changed from INTEGER to BIGINT
                },
                'fare_attributes.txt': {
                    'fare_id': 'VARCHAR',
                    'price': 'DOUBLE',
                    'currency_type': 'VARCHAR',
                    'payment_method': 'INTEGER',
                    'transfers': 'INTEGER',
                    'agency_id': 'VARCHAR',
                    'transfer_duration': 'INTEGER'
                },
                'fare_rules.txt': {
                    'fare_id': 'VARCHAR',
                    'route_id': 'VARCHAR',
                    'origin_id': 'VARCHAR',
                    'destination_id': 'VARCHAR',
                    'contains_id': 'VARCHAR'
                },
                'frequencies.txt': {
                    'trip_id': 'VARCHAR',
                    'start_time': 'VARCHAR',
                    'end_time': 'VARCHAR',
                    'headway_secs': 'INTEGER',
                    'exact_times': 'INTEGER'
                },
                'transfers.txt': {
                    'from_stop_id': 'VARCHAR',
                    'to_stop_id': 'VARCHAR',
                    'transfer_type': 'INTEGER',
                    'min_transfer_time': 'INTEGER',
                    'from_route_id': 'VARCHAR',
                    'to_route_id': 'VARCHAR',
                    'from_trip_id': 'VARCHAR',
                    'to_trip_id': 'VARCHAR'
                },
                'pathways.txt': {
                    'pathway_id': 'VARCHAR',
                    'from_stop_id': 'VARCHAR',
                    'to_stop_id': 'VARCHAR',
                    'pathway_mode': 'INTEGER',
                    'is_bidirectional': 'INTEGER',
                    'length': 'DOUBLE',
                    'traversal_time': 'INTEGER',
                    'stair_count': 'INTEGER',
                    'max_slope': 'DOUBLE',
                    'min_width': 'DOUBLE',
                    'signposted_as': 'VARCHAR',
                    'reversed_signposted_as': 'VARCHAR',
                    'entrance_restriction': 'INTEGER',
                    'exit_restriction': 'INTEGER'
                },
                'levels.txt': {
                    'level_id': 'VARCHAR',
                    'level_index': 'DOUBLE',
                    'level_name': 'VARCHAR'
                },
                'feed_info.txt': {
                    'feed_publisher_name': 'VARCHAR',
                    'feed_publisher_url': 'VARCHAR',
                    'feed_lang': 'VARCHAR',
                    'default_lang': 'VARCHAR',
                    'feed_start_date': 'VARCHAR',
                    'feed_end_date': 'VARCHAR',
                    'feed_version': 'VARCHAR',
                    'feed_contact_email': 'VARCHAR',
                    'feed_contact_url': 'VARCHAR'
                },
                'translations.txt': {
                    'table_name': 'VARCHAR',
                    'field_name': 'VARCHAR',
                    'language': 'VARCHAR',
                    'translation': 'VARCHAR',
                    'record_id': 'VARCHAR',
                    'record_sub_id': 'VARCHAR',
                    'field_value': 'VARCHAR'
                },
                'attributions.txt': {
                    'attribution_id': 'VARCHAR',
                    'agency_id': 'VARCHAR',
                    'route_id': 'VARCHAR',
                    'trip_id': 'VARCHAR',
                    'organization_name': 'VARCHAR',
                    'is_producer': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'is_operator': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'is_authority': 'BIGINT',  # Changed from INTEGER to BIGINT
                    'attribution_url': 'VARCHAR',
                    'attribution_email': 'VARCHAR',
                    'attribution_phone': 'VARCHAR'
                }
            }
            
            # Get column types for this file
            types = column_types.get(filename, {})
            if not types:
                logger.warning(f"No type definitions for {filename}, using auto-detection")
            
            # First read the header to get actual columns
            with open(csv_path, 'r', encoding='utf-8') as f:
                header = f.readline().strip().split(',')
                header = [col.strip('"') for col in header]  # Remove quotes if present
            
            # Filter type specs to only include columns that exist in the file
            type_specs = []
            for col in header:
                col_type = types.get(col, 'VARCHAR')  # Default to VARCHAR if type not specified
                type_specs.append(f"{col} {col_type}")
            
            # Create a temporary table from the CSV with explicit types
            table_name = f"temp_{filename.replace('.', '_')}"
            
            if type_specs:
                # Create table with explicit types
                self.db.execute(f"""
                    CREATE TABLE {table_name} (
                        {', '.join(type_specs)}
                    )
                """)
                
                # Load data with COPY
                self.db.execute(f"""
                    COPY {table_name} FROM '{csv_path}' (
                        AUTO_DETECT FALSE,
                        HEADER TRUE,
                        DELIMITER ',',
                        QUOTE '"'
                    )
                """)
            else:
                # Fallback to auto-detection for files without type definitions
                self.db.execute(f"""
                CREATE TABLE {table_name} AS 
                    SELECT * FROM read_csv_auto('{csv_path}', header=true, sample_size=-1)
            """)
            
            # Write to Parquet using DuckDB's COPY command
            self.db.execute(f"""
                COPY {table_name} TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY')
            """)
            
            # Drop temporary table
            self.db.execute(f"DROP TABLE {table_name}")
            
            # Move the file to its final destination
            final_path = self.data_dir / f"{filename}.parquet"
            shutil.move(str(parquet_path), str(final_path))
            
            # Clean up temporary directory
            temp_dir.rmdir()
            
            return final_path
        except Exception as e:
            logger.error(f"Error converting {filename} to Parquet: {e}")
            return None
        finally:
            # Ensure cleanup of temporary resources
            try:
                if 'temp_dir' in locals() and temp_dir.exists():
                    shutil.rmtree(str(temp_dir))
            except Exception as cleanup_error:
                logger.warning(f"Error cleaning up temporary directory: {cleanup_error}")
    
    def _load_stops(self) -> None:
        """Load stops from stops.txt into memory."""
        parquet_path = self._csv_to_parquet("stops.txt")
        if not parquet_path:
            return

        # First, get the available columns
        self.db.execute(f"""
            CREATE TEMP TABLE temp_stops AS 
            SELECT * FROM read_parquet('{parquet_path}')
        """)
        columns = self.db.execute("DESCRIBE temp_stops").fetchdf()['column_name'].tolist()

        # Build the query dynamically based on available columns
        optional_columns = {
            'location_type': 'NULL',
            'parent_station': 'NULL',
            'platform_code': 'NULL',
            'stop_timezone': 'NULL'
        }

        select_parts = [
            'stop_id',
            'stop_name',
            'stop_lat',
            'stop_lon'
        ]

        for col, default in optional_columns.items():
            select_parts.append(f"COALESCE({col}, {default}) as {col}" if col in columns else f"{default} as {col}")

        query = f"""
            SELECT 
                {', '.join(select_parts)}
            FROM temp_stops
        """
        result = self.db.execute(query).fetchdf()
        
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
                timezone=None if pd.isna(row["stop_timezone"]) else row["stop_timezone"]
            )
            self.stops[stop.id] = stop

        # Clean up
        self.db.execute("DROP TABLE temp_stops")
    
    def _load_stop_times(self) -> None:
        """Load stop times data into DuckDB using parallel processing."""
        parquet_path = self._csv_to_parquet('stop_times.txt')
        if not parquet_path:
            logger.error("Failed to convert stop_times.txt to Parquet")
            return
            
        # Use multiple threads but limit based on available memory
        num_threads = min(2, os.cpu_count() or 1)  # Conservative for RPi
        logger.info(f"Loading stop times with {num_threads} threads")
            
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
        
        # Log table info
        count = self.db.execute("SELECT COUNT(*) FROM stop_times").fetchone()[0]
        logger.info(f"Loaded {count} stop times")
        
        # Sample some data
        sample = self.db.execute("SELECT * FROM stop_times LIMIT 5").fetchdf()
        logger.info("Sample stop times:")
        for _, row in sample.iterrows():
            logger.info(f"  Trip {row['trip_id']}: Stop {row['stop_id']} at {row['arrival_time']}")
        
        # Create optimized indices for route search
        logger.info("Creating indices...")
        self.db.execute(f"""
            CREATE INDEX idx_stop_times_trip_stop ON stop_times(trip_id, stop_id)
            /*+ PARALLEL({num_threads}) */
        """)
        self.db.execute(f"""
            CREATE INDEX idx_stop_times_stop_seq ON stop_times(stop_id, stop_sequence)
            /*+ PARALLEL({num_threads}) */
        """)
        logger.info("Stop times loading complete")
    
    def _load_trips(self) -> None:
        """Load trips data into DuckDB."""
        parquet_path = self._csv_to_parquet('trips.txt')
        if not parquet_path:
            logger.error("Failed to convert trips.txt to Parquet")
            return
            
        logger.info("Loading trips table...")
        # Create trips table
        try:
            # First try with all optional fields
            self.db.execute(f"""
            CREATE TABLE trips AS 
            SELECT 
                route_id,
                service_id,
                trip_id,
                    COALESCE(trip_headsign, NULL) as trip_headsign,
                    COALESCE(direction_id, '0') as direction_id,
                    COALESCE(block_id, NULL) as block_id,
                    COALESCE(shape_id, NULL) as shape_id
                FROM parquet_scan('{parquet_path}')
            """)
        except Exception as e:
            logger.debug(f"Failed to create trips table with all fields: {e}")
            # If that fails, try with only required fields
            self.db.execute(f"""
                CREATE TABLE trips AS 
                SELECT 
                    route_id,
                    service_id,
                    trip_id,
                    COALESCE(trip_headsign, NULL) as trip_headsign,
                    COALESCE(direction_id, '0') as direction_id,
                    COALESCE(shape_id, NULL) as shape_id
                FROM parquet_scan('{parquet_path}')
            """)
            # Add missing optional columns with NULL values
            self.db.execute("""
                ALTER TABLE trips ADD COLUMN block_id VARCHAR
            """)
            
        # Get some sample trips for logging
        sample_trips = self.db.execute("""
            SELECT trip_id, route_id, service_id
            FROM trips
            LIMIT 5
        """).fetchdf()
        
        logger.info(f"Loaded {len(self.db.execute('SELECT * FROM trips').fetchdf())} trips")
        logger.info("Sample trips:")
        for _, row in sample_trips.iterrows():
            logger.info(f"  Trip {row['trip_id']}: Route {row['route_id']}, Service {row['service_id']}")
            
        logger.info("Creating indices...")
        self.db.execute("""
            CREATE INDEX trips_trip_id_idx ON trips(trip_id);
            CREATE INDEX trips_route_id_idx ON trips(route_id);
            CREATE INDEX trips_service_id_idx ON trips(service_id);
        """)
        logger.info("Trips loading complete")
    
    def _load_shapes(self) -> Dict[str, Shape]:
        """Load shapes from shapes.txt into memory.
        
        Returns:
            Dictionary mapping shape_id to Shape objects.
        """
        parquet_path = self._csv_to_parquet('shapes.txt')
        if not parquet_path:
            logger.warning("No shapes.txt found, routes will use stop coordinates")
            return {}

        # Create shapes table
        self.db.execute(f"""
            CREATE TABLE shapes AS 
            SELECT 
                shape_id,
                CAST(shape_pt_lat AS FLOAT) as shape_pt_lat,
                CAST(shape_pt_lon AS FLOAT) as shape_pt_lon,
                CAST(shape_pt_sequence AS INTEGER) as shape_pt_sequence
            FROM parquet_scan('{parquet_path}')
        """)
        
        # Create index for faster lookups
        self.db.execute("CREATE INDEX idx_shapes_id ON shapes(shape_id)")
        
        # Get all shapes with their points, properly ordered by sequence
        query = """
            WITH ordered_points AS (
                SELECT 
                    shape_id,
                    shape_pt_lat,
                    shape_pt_lon,
                    shape_pt_sequence
                FROM shapes
                ORDER BY shape_id, shape_pt_sequence
            )
            SELECT 
                shape_id,
                array_agg([shape_pt_lat, shape_pt_lon] ORDER BY shape_pt_sequence) as points
            FROM ordered_points
            GROUP BY shape_id
        """
        result = self.db.execute(query).fetchdf()
        
        # Create Shape objects
        shapes = {}
        for _, row in result.iterrows():
            shapes[row['shape_id']] = Shape(
                shape_id=str(row['shape_id']),
                points=row['points']
            )
        
        logger.info(f"Loaded {len(shapes)} shapes")
        return shapes
    
    def _load_routes(self) -> List[Route]:
        """Load routes from the database and create Route objects."""
        # First load routes into DuckDB
        parquet_path = self._csv_to_parquet('routes.txt')
        if not parquet_path:
            logger.error("Failed to convert routes.txt to Parquet")
            return []
            
        logger.info("Loading routes table...")
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
        
        # Log table info
        count = self.db.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
        logger.info(f"Loaded {count} routes")
        
        # Sample some data
        sample = self.db.execute("SELECT * FROM routes LIMIT 5").fetchdf()
        logger.info("Sample routes:")
        for _, row in sample.iterrows():
            logger.info(f"  Route {row['route_id']}: {row['route_long_name'] or row['route_short_name']}")
        
        # Create index
        logger.info("Creating route index...")
        self.db.execute("CREATE INDEX idx_routes_id ON routes(route_id)")
        
        # Load shapes
        logger.info("Loading shapes...")
        shapes = self._load_shapes()
        
        # Get representative trip for each route
        logger.info("Getting representative trips...")
        query = """
            WITH trip_ranks AS (
            SELECT 
                    t.route_id,
                    t.trip_id,
                    t.service_id,
                    t.trip_headsign,
                    t.direction_id,
                    t.shape_id,
                    ROW_NUMBER() OVER (PARTITION BY t.route_id ORDER BY t.trip_id) as rn
                FROM trips t
            )
            SELECT 
                r.route_id,
                r.route_short_name,
                r.route_long_name,
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
            JOIN trip_ranks t ON r.route_id = t.route_id AND t.rn = 1
            ORDER BY r.route_id
        """
        result = self.db.execute(query).fetchdf()
        logger.info(f"Found {len(result)} routes with trips")
        
        # Group by route_id and direction_id
        routes = []
        for (route_id, direction_id), group in result.groupby(['route_id', 'direction_id']):
            logger.debug(f"Processing route {route_id}, direction {direction_id}")
            first_row = group.iloc[0]
            trip_id = first_row['trip_id']
            
            # Get stops for this trip
            route_stops = self._create_route_stops(trip_id)
            if not route_stops:
                logger.warning(f"No stops found for route {route_id}, trip {trip_id}")
                continue
            
            # Get service days for this route
            service_ids = set(group['service_id'].dropna())
            service_days = self._get_service_days(service_ids)
            if not service_days:
                logger.warning(f"No service days found for route {route_id}")
                continue
            
            # Get shape for this trip if available
            shape = None
            if pd.notna(first_row['shape_id']) and first_row['shape_id'] in shapes:
                shape = shapes[first_row['shape_id']]
            
            # Create trips for this route
            trips = []
            for _, row in group.iterrows():
                trip_id = str(row['trip_id'])
                logger.debug(f"Creating trip {trip_id} for route {route_id}")
                trip = Trip(
                    id=trip_id,
                    route_id=str(row['route_id']),
                    service_id=str(row['service_id']),
                    headsign=row['trip_headsign'] if pd.notna(row['trip_headsign']) else None,
                    direction_id=str(row['direction_id']) if pd.notna(row['direction_id']) else None,
                    block_id=str(row['block_id']) if 'block_id' in row and pd.notna(row['block_id']) else None,
                    shape_id=str(row['shape_id']) if pd.notna(row['shape_id']) else None,
                    stop_times=self._create_stop_times(trip_id)
                )
                trips.append(trip)
                logger.debug(f"Created trip {trip_id} with {len(trip.stop_times)} stop times")
            
            # Create route object
            route = Route(
                route_id=route_id,
                route_name=first_row['route_long_name'] if pd.notna(first_row['route_long_name']) else first_row['route_short_name'],
                trip_id=trip_id,
                stops=route_stops,
                service_days=service_days,
                shape=shape,
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
            logger.debug(f"Created route {route_id} with {len(trips)} trips")
        
        logger.info(f"Created {len(routes)} route objects")
        return routes
    
    def _create_route_stops(self, trip_id: str) -> List[RouteStop]:
        """Create RouteStop objects for a trip.
        
        Args:
            trip_id: The trip ID to get stops for.
            
        Returns:
            List of RouteStop objects ordered by stop_sequence.
        """
        logger.debug(f"Creating route stops for trip {trip_id}")
        
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
            logger.warning(f"No stop times found for trip {trip_id}")
            return []
        
        logger.debug(f"Found {len(result)} stop times for trip {trip_id}")
        
        # Create RouteStop objects
        route_stops = []
        for _, row in result.iterrows():
            stop_id = str(row['stop_id'])
            
            if stop_id not in self.stops:
                logger.warning(f"Stop {stop_id} not found in stops dictionary")
                continue
            
            route_stop = RouteStop(
                stop=self.stops[stop_id],
                arrival_time=row['arrival_time'],
                departure_time=row['departure_time'],
                stop_sequence=int(row['stop_sequence'])
            )
            route_stops.append(route_stop)
        
        logger.debug(f"Created {len(route_stops)} route stops for trip {trip_id}")
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
                    CAST(monday AS BOOLEAN) as monday,
                    CAST(tuesday AS BOOLEAN) as tuesday,
                    CAST(wednesday AS BOOLEAN) as wednesday,
                    CAST(thursday AS BOOLEAN) as thursday,
                    CAST(friday AS BOOLEAN) as friday,
                    CAST(saturday AS BOOLEAN) as saturday,
                    CAST(sunday AS BOOLEAN) as sunday,
                    strptime(start_date, '%Y%m%d') as start_date,
                    strptime(end_date, '%Y%m%d') as end_date
                FROM parquet_scan('{calendar_path}')
                /*+ PARALLEL({num_threads}) */
            """)
            self.db.execute(f"""
                CREATE INDEX idx_calendar_service_id ON calendar(service_id)
                /*+ PARALLEL({num_threads}) */
            """)
        
        if calendar_dates_path:
            self.db.execute(f"""
                CREATE TABLE calendar_dates AS 
                SELECT 
                    service_id,
                    strptime(date, '%Y%m%d') as date,
                    CAST(exception_type AS INTEGER) as exception_type
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
            self._setup_db()  # Set up DuckDB configuration
            self._load_stops()
            self._load_stop_times()
            self._load_trips()
            self._load_calendar()
            
            # Load routes
            routes = self._load_routes()
            
            # Get calendars and calendar dates
            calendars = self._get_calendars()
            calendar_dates = self._get_calendar_dates()
            
            logger.info("GTFS feed loaded successfully")
            return FlixbusFeed(
                stops=self.stops,
                routes=routes,
                translations=self.translations,
                calendars=calendars,
                calendar_dates=calendar_dates
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
        """Get the service days for a set of service IDs."""
        logger.debug(f"Getting service days for service IDs: {service_ids}")
        service_days = set()
        
        # Check if calendar table exists
        has_calendar = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'calendar'
            )
        """).fetchone()[0]
        logger.debug(f"Has calendar table: {has_calendar}")
        
        # Check if calendar_dates table exists
        has_calendar_dates = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'calendar_dates'
            )
        """).fetchone()[0]
        logger.debug(f"Has calendar_dates table: {has_calendar_dates}")
        
        if has_calendar_dates:
            # First check calendar_dates.txt for type 1 exceptions (added service)
            calendar_dates_query = """
                SELECT service_id, date, exception_type
                FROM calendar_dates
                WHERE service_id = ?
            """
            
            # Check calendar_dates for type 1 exceptions first
            for service_id in service_ids:
                dates_result = self.db.execute(calendar_dates_query, [service_id]).fetchdf()
                if not dates_result.empty:
                    # Only consider type 1 exceptions (additions)
                    additions = dates_result[dates_result['exception_type'] == 1]
                    for _, row in additions.iterrows():
                        weekday = row['date'].strftime('%A').lower()
                        service_days.add(weekday)
                        logger.debug(f"Added service day {weekday} from calendar_dates for service {service_id}")
        
        if has_calendar:
            # Then check calendar.txt for regular service
            calendar_query = """
                SELECT 
                    service_id,
                    monday, tuesday, wednesday, thursday, friday, saturday, sunday,
                    start_date, end_date
                FROM calendar
                WHERE service_id = ?
            """
            
            has_regular_calendar = False
            for service_id in service_ids:
                # Check regular calendar
                calendar_result = self.db.execute(calendar_query, [service_id]).fetchdf()
                if not calendar_result.empty:
                    row = calendar_result.iloc[0]
                    # Only consider this calendar if it has at least one day set to 1
                    if any([row['monday'], row['tuesday'], row['wednesday'], row['thursday'], 
                           row['friday'], row['saturday'], row['sunday']]):
                        has_regular_calendar = True
                        logger.debug(f"Found regular calendar for service {service_id}")
                    if row['monday']: service_days.add('monday')
                    if row['tuesday']: service_days.add('tuesday')
                    if row['wednesday']: service_days.add('wednesday')
                    if row['thursday']: service_days.add('thursday')
                    if row['friday']: service_days.add('friday')
                    if row['saturday']: service_days.add('saturday')
                    if row['sunday']: service_days.add('sunday')
            
            # If we have regular calendar, check for type 2 exceptions (removals)
            if has_regular_calendar and has_calendar_dates:
                for service_id in service_ids:
                    dates_result = self.db.execute(calendar_dates_query, [service_id]).fetchdf()
                    if not dates_result.empty:
                        removals = dates_result[dates_result['exception_type'] == 2]
                        if not removals.empty:
                            # Group removals by weekday
                            removals_by_day = {}
                            for _, row in removals.iterrows():
                                weekday = row['date'].strftime('%A').lower()
                                if weekday not in removals_by_day:
                                    removals_by_day[weekday] = set()
                                removals_by_day[weekday].add(row['service_id'])
                            
                            # Remove days that are completely excluded by type 2 exceptions
                            for day, removed_services in removals_by_day.items():
                                if removed_services == service_ids:  # All services have this day removed
                                    service_days.discard(day)
                                    logger.debug(f"Removed service day {day} due to type 2 exception")
        
        logger.debug(f"Final service days: {sorted(list(service_days))}")
        return service_days 
    
    def _create_stop_times(self, trip_id: str) -> List[StopTime]:
        """Create StopTime objects for a trip.
        
        Args:
            trip_id: The trip ID to get stop times for.
            
        Returns:
            List of StopTime objects ordered by stop_sequence.
        """
        # Get stop times for this trip
        query = """
            SELECT 
                trip_id,
                stop_id,
                -- Handle times that might exceed 24:00:00 (service past midnight)
                CASE 
                    WHEN arrival_time ~ '^[0-9]{1,2}:[0-9]{2}:[0-9]{2}$' 
                    THEN arrival_time 
                    ELSE REGEXP_REPLACE(arrival_time, '^([0-9]{2,3}):', '\1:')
                END as arrival_time,
                CASE 
                    WHEN departure_time ~ '^[0-9]{1,2}:[0-9]{2}:[0-9]{2}$' 
                    THEN departure_time 
                    ELSE REGEXP_REPLACE(departure_time, '^([0-9]{2,3}):', '\1:')
                END as departure_time,
                stop_sequence
            FROM stop_times
            WHERE trip_id = ?
            ORDER BY stop_sequence
        """
        logger.debug(f"Loading stop times for trip {trip_id}")
        result = self.db.execute(query, [trip_id]).fetchdf()
        
        if result.empty:
            logger.warning(f"No stop times found for trip {trip_id}")
            return []
        
        # Create StopTime objects
        stop_times = []
        for _, row in result.iterrows():
            stop_time = StopTime(
                trip_id=str(row['trip_id']),
                stop_id=str(row['stop_id']),
                arrival_time=str(row['arrival_time']),
                departure_time=str(row['departure_time']),
                stop_sequence=int(row['stop_sequence'])
            )
            stop_times.append(stop_time)
        
        logger.debug(f"Created {len(stop_times)} stop times for trip {trip_id}")
        return stop_times 
    
    def _create_trip(self, row: pd.Series) -> Trip:
        """Create a Trip object from a row of data."""
        # Get stop times for this trip
        stop_times = self._create_stop_times(row['trip_id'])
        
        # Create the Trip object
        return Trip(
            id=str(row['trip_id']),
            route_id=str(row['route_id']),
            service_id=str(row['service_id']),
            headsign=str(row['trip_headsign']) if pd.notna(row['trip_headsign']) else None,
            direction_id=str(row['direction_id']) if pd.notna(row['direction_id']) else None,
            block_id=str(row['block_id']) if 'block_id' in row and pd.notna(row['block_id']) else None,
            shape_id=str(row['shape_id']) if pd.notna(row['shape_id']) else None,
            stop_times=stop_times
        ) 
    
    def _get_trips_for_route(self, route_id: str) -> List[Trip]:
        """Get all trips for a route."""
        trips = []
        
        # Get all trips for this route
        trips_df = self.db.execute("""
            SELECT t.*, r.route_short_name, r.route_long_name
            FROM trips t
            JOIN routes r ON t.route_id = r.route_id
            WHERE t.route_id = ?
        """, [route_id]).fetchdf()
        
        if trips_df.empty:
            logger.warning(f"No trips found for route {route_id}")
            return []
            
        # Group by route_id to get route info
        for route_id, group in trips_df.groupby('route_id'):
            first_row = group.iloc[0]
            
            # Get service days for this route
            service_ids = set(group['service_id'].dropna())
            service_days = self._get_service_days(service_ids)
            if not service_days:
                logger.warning(f"No service days found for route {route_id}")
                continue
            
            # Create trip objects
            for _, row in group.iterrows():
                trip_id = str(row['trip_id'])
                logger.debug(f"Creating trip {trip_id} for route {route_id}")
                trip = Trip(
                    id=trip_id,
                    route_id=str(row['route_id']),
                    service_id=str(row['service_id']),
                    headsign=row['trip_headsign'] if pd.notna(row['trip_headsign']) else None,
                    direction_id=str(row['direction_id']) if pd.notna(row['direction_id']) else None,
                    block_id=str(row['block_id']) if 'block_id' in row and pd.notna(row['block_id']) else None,
                    shape_id=str(row['shape_id']) if pd.notna(row['shape_id']) else None,
                    stop_times=self._create_stop_times(trip_id)
                )
                trips.append(trip)
                logger.debug(f"Created trip {trip_id} with {len(trip.stop_times)} stop times")
            
            # Create route object
            route = Route(
                route_id=route_id,
                route_name=first_row['route_long_name'] if pd.notna(first_row['route_long_name']) else first_row['route_short_name'],
                trip_id=trip_id,
                trips=trips,
                service_days=sorted(list(service_days)),
                service_ids=list(service_ids)
            )
            
            return trips
            
        return [] 
    
    def _get_calendars(self) -> Dict[str, Calendar]:
        """Get calendars from DuckDB as Calendar objects."""
        calendars = {}
        
        # Check if calendar table exists
        has_calendar = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'calendar'
            )
        """).fetchone()[0]
        
        if has_calendar:
            result = self.db.execute("""
                SELECT 
                    service_id,
                    monday, tuesday, wednesday, thursday, friday, saturday, sunday,
                    start_date,
                    end_date
                FROM calendar
            """).fetchdf()
            
            for _, row in result.iterrows():
                calendars[str(row['service_id'])] = Calendar(
                    service_id=str(row['service_id']),
                    monday=bool(row['monday']),
                    tuesday=bool(row['tuesday']),
                    wednesday=bool(row['wednesday']),
                    thursday=bool(row['thursday']),
                    friday=bool(row['friday']),
                    saturday=bool(row['saturday']),
                    sunday=bool(row['sunday']),
                    start_date=row['start_date'],
                    end_date=row['end_date']
                )
        
        return calendars
    
    def _get_calendar_dates(self) -> List[CalendarDate]:
        """Get calendar dates from DuckDB as CalendarDate objects."""
        calendar_dates = []
        
        # Check if calendar_dates table exists
        has_calendar_dates = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'calendar_dates'
            )
        """).fetchone()[0]
        
        if has_calendar_dates:
            result = self.db.execute("""
                SELECT 
                    service_id,
                    date,
                    exception_type
                FROM calendar_dates
            """).fetchdf()
            
            for _, row in result.iterrows():
                calendar_dates.append(CalendarDate(
                    service_id=str(row['service_id']),
                    date=row['date'],
                    exception_type=int(row['exception_type'])
                ))
        
        return calendar_dates 

    def get_stops_in_bbox(self, bbox: BoundingBox, count_only: bool = False) -> Union[List[StationResponse], Dict[str, int]]:
        """Get all stops within a bounding box.
        
        Args:
            bbox: BoundingBox object with min/max lat/lon
            count_only: If True, only return the count of stops
            
        Returns:
            If count_only is True, returns Dict with count
            Otherwise returns List of StationResponse objects
        """
        # Filter stops within the bounding box
        stops_in_bbox = []
        for stop_id, stop in self.stops.items():
            if (bbox.min_lat <= stop.lat <= bbox.max_lat) and (
                bbox.min_lon <= stop.lon <= bbox.max_lon
            ):
                # If we only need the count, just add the ID
                if count_only:
                    stops_in_bbox.append(stop_id)
                    continue

                # Create StationResponse object
                stops_in_bbox.append(
                    StationResponse(
                        id=stop_id,
                        name=stop.name,
                        location=Location(lat=stop.lat, lon=stop.lon),
                        translations=stop.translations,
                        routes=[]  # Routes will be added by the API endpoint
                    )
                )

        if count_only:
            return {"count": len(stops_in_bbox)}

        return stops_in_bbox


def load_feed(data_dir: str | Path = None) -> Optional[FlixbusFeed]:
    """Load a GTFS feed from the specified directory.
    
    Args:
        data_dir: Directory containing GTFS files. If None, uses current directory.
        
    Returns:
        A FlixbusFeed object if successful, None otherwise.
    """
    loader = ParquetGTFSLoader(data_dir)
    try:
        return loader.load_feed()
    finally:
        loader.close()

