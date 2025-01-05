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
    Agency,
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
    
    # Column type definitions for GTFS files
    column_types = {
        'stop_times.txt': {
            'trip_id': 'VARCHAR',
            'arrival_time': 'VARCHAR',
            'departure_time': 'VARCHAR',
            'stop_id': 'VARCHAR',
            'stop_sequence': 'INTEGER',
            'stop_headsign': 'VARCHAR',
            'pickup_type': 'INTEGER',
            'drop_off_type': 'INTEGER',
            'continuous_pickup': 'INTEGER',
            'continuous_drop_off': 'INTEGER',
            'shape_dist_traveled': 'DOUBLE',
            'timepoint': 'INTEGER'
        },
        'trips.txt': {
            'route_id': 'VARCHAR',
            'service_id': 'VARCHAR',
            'trip_id': 'VARCHAR',
            'trip_headsign': 'VARCHAR',
            'trip_short_name': 'VARCHAR',
            'direction_id': 'INTEGER',
            'block_id': 'VARCHAR',
            'shape_id': 'VARCHAR',
            'wheelchair_accessible': 'INTEGER',
            'bikes_allowed': 'INTEGER'
        },
        'routes.txt': {
            'route_id': 'VARCHAR',
            'route_short_name': 'VARCHAR',
            'route_long_name': 'VARCHAR',
            'route_type': 'INTEGER',
            'route_color': 'VARCHAR',
            'route_text_color': 'VARCHAR',
            'agency_id': 'VARCHAR'
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
            'location_type': 'INTEGER',
            'parent_station': 'VARCHAR',
            'stop_timezone': 'VARCHAR',
            'wheelchair_boarding': 'INTEGER',
            'platform_code': 'VARCHAR'
        },
        'calendar.txt': {
            'service_id': 'VARCHAR',
            'monday': 'INTEGER',
            'tuesday': 'INTEGER',
            'wednesday': 'INTEGER',
            'thursday': 'INTEGER',
            'friday': 'INTEGER',
            'saturday': 'INTEGER',
            'sunday': 'INTEGER',
            'start_date': 'VARCHAR',
            'end_date': 'VARCHAR'
        },
        'calendar_dates.txt': {
            'service_id': 'VARCHAR',
            'date': 'VARCHAR',
            'exception_type': 'INTEGER'
        }
    }
    
    def __init__(self, data_dir: str | Path = None):
        """Initialize the loader with the GTFS data directory."""
        self.data_dir = Path(data_dir) if data_dir else Path.cwd()
        
        # Create a unique database file in a temporary directory
        self._temp_dir = Path(tempfile.gettempdir()) / f"duckdb_temp_{uuid.uuid4()}"
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._db_file = self._temp_dir / "gtfs.db"
        
        logger.info(f"Using DuckDB database file: {self._db_file}")
        self.db = duckdb.connect(str(self._db_file))
        self.stops = {}
        self.routes = {}
        self.translations = {}
        
    def _setup_db(self):
        """Set up DuckDB configuration for optimal performance."""
        # Configure memory limits based on available system memory
        total_memory = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
        memory_limit = max(128 * 1024 * 1024, total_memory // 8)  # Use 12.5% of system memory or at least 128MB
        
        # Create a unique temporary directory for this instance
        temp_dir = Path(tempfile.gettempdir()) / f"duckdb_temp_{uuid.uuid4()}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using temporary directory: {temp_dir}")
        
        try:
            self.db.execute(f"SET memory_limit='{memory_limit}B'")
            self.db.execute("SET enable_progress_bar=false")
            self.db.execute("PRAGMA threads=4")  # Limit thread usage
            self.db.execute("PRAGMA memory_limit='1GB'")  # Hard limit
            self.db.execute(f"PRAGMA temp_directory='{temp_dir}'")  # Use our temp directory
            
            # Store the temp directory path for cleanup
            self._temp_dir = temp_dir
            
        except Exception as e:
            logger.error(f"Error setting up DuckDB: {e}", exc_info=True)
            # Clean up if setup fails
            try:
                shutil.rmtree(str(temp_dir))
            except:
                pass
            raise

    def _validate_gtfs_data(self, csv_path: Path, filename: str) -> bool:
        """Validate and clean GTFS data before conversion.
        
        Args:
            csv_path: Path to the CSV file
            filename: Name of the file being processed
            
        Returns:
            bool: True if validation passed (or has recoverable errors), False if critical failure
        """
        try:
            # Read the first few rows to check data
            df = pd.read_csv(csv_path, nrows=5)
            has_warnings = False
            
            # Check for required columns based on file type
            required_columns = {
                'stop_times.txt': ['trip_id', 'arrival_time', 'departure_time', 'stop_id', 'stop_sequence'],
                'trips.txt': ['route_id', 'service_id', 'trip_id'],
                'routes.txt': ['route_id', 'route_type'],
                'stops.txt': ['stop_id', 'stop_name', 'stop_lat', 'stop_lon'],
                'calendar.txt': ['service_id', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'start_date', 'end_date'],
                'calendar_dates.txt': ['service_id', 'date', 'exception_type']
            }
            
            if filename in required_columns:
                missing_cols = [col for col in required_columns[filename] if col not in df.columns]
                if missing_cols:
                    logger.error(f"Missing required columns in {filename}: {missing_cols}")
                    return False  # This is a critical error
            
            # Specific validations for each file type
            if filename == 'stop_times.txt':
                # Check for valid time format (HH:MM:SS)
                time_pattern = r'^([0-9]{1,2}|[0-9]{3,}):([0-5][0-9]):([0-5][0-9])$'
                for col in ['arrival_time', 'departure_time']:
                    invalid_times = df[~df[col].str.match(time_pattern, na=True)]
                    if not invalid_times.empty:
                        logger.warning(f"Invalid time format found in {col} - these rows will be ignored")
                        has_warnings = True
                
                # Check for negative values in numeric columns
                numeric_cols = ['stop_sequence', 'pickup_type', 'drop_off_type']
                for col in numeric_cols:
                    if col in df.columns:
                        negative_vals = df[df[col] < 0]
                        if not negative_vals.empty:
                            logger.warning(f"Negative values found in {col} - these will be treated as NULL")
                            has_warnings = True
            
            elif filename == 'stops.txt':
                # Validate lat/lon ranges
                invalid_lat = df[(df['stop_lat'] < -90) | (df['stop_lat'] > 90)]
                invalid_lon = df[(df['stop_lon'] < -180) | (df['stop_lon'] > 180)]
                if not invalid_lat.empty or not invalid_lon.empty:
                    logger.warning(f"Invalid lat/lon values found in {filename} - these stops will be ignored")
                    has_warnings = True
            
            elif filename == 'calendar.txt':
                # Validate binary values for weekdays
                weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                for day in weekdays:
                    invalid_vals = df[~df[day].isin([0, 1])]
                    if not invalid_vals.empty:
                        logger.warning(f"Invalid values found in {day} column - non-binary values will be treated as 0")
                        has_warnings = True
                
                # Validate date format (YYYYMMDD)
                date_pattern = r'^[0-9]{8}$'
                for col in ['start_date', 'end_date']:
                    invalid_dates = df[~df[col].astype(str).str.match(date_pattern, na=True)]
                    if not invalid_dates.empty:
                        logger.warning(f"Invalid date format found in {col} - these rows will be ignored")
                        has_warnings = True
            
            if has_warnings:
                logger.warning(f"Validation completed for {filename} with warnings - proceeding with data loading")
            else:
                logger.info(f"Validation completed for {filename} successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error validating {filename}: {e}")
            return False

    def _csv_to_parquet(self, filename: str) -> Optional[Path]:
        """Convert a CSV file to Parquet format using DuckDB."""
        csv_path = self.data_dir / filename
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return None
        
        try:
            # Validate data before conversion
            if not self._validate_gtfs_data(csv_path, filename):
                logger.error(f"Validation failed for {filename}")
                return None

            # Create a subdirectory in our temp directory for this file
            file_temp_dir = self._temp_dir / f"parquet_{uuid.uuid4()}"
            file_temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Use the temporary directory for the parquet file
            parquet_path = file_temp_dir / f"{filename}.parquet"
            
            # First read the header to get actual columns
            with open(csv_path, 'r', encoding='utf-8') as f:
                header = f.readline().strip().split(',')
                header = [col.strip('"') for col in header]  # Remove quotes if present

            # Create a new connection for each file to avoid state issues
            db = duckdb.connect(":memory:")
            db.execute("SET enable_progress_bar=false")
            db.execute("PRAGMA threads=4")
            db.execute("PRAGMA memory_limit='1GB'")
            db.execute(f"PRAGMA temp_directory='{self._temp_dir}'")  # Use our temp directory

            # Get column types for this file
            types = self.column_types.get(filename, {})
            
            # Filter type specs to only include columns that exist in the file
            type_specs = []
            for col in header:
                col_type = types.get(col, 'VARCHAR')  # Default to VARCHAR if type not specified
                type_specs.append(f"{col} {col_type}")
            
            # Create a temporary table with explicit types
            table_name = f"temp_{filename.replace('.', '_')}"
            
            # Create table with explicit types
            create_table_sql = f"""
                CREATE TABLE {table_name} (
                    {', '.join(type_specs)}
                )
            """
            db.execute(create_table_sql)
            
            # Load data with COPY, handling invalid data
            try:
                db.execute(f"""
                    COPY {table_name} FROM '{csv_path}' (
                        AUTO_DETECT FALSE,
                        HEADER TRUE,
                        DELIMITER ',',
                        QUOTE '"',
                        IGNORE_ERRORS TRUE
                    )
                """)
            except Exception as e:
                logger.warning(f"Error during COPY operation for {filename}: {e}")
                # Try to load with auto-detection as fallback
                db.execute(f"DROP TABLE IF EXISTS {table_name}")
                db.execute(f"""
                    CREATE TABLE {table_name} AS 
                    SELECT * FROM read_csv_auto(
                        '{csv_path}',
                        header=true,
                        sample_size=-1,
                        ignore_errors=true
                    )
                """)
            
            # Write to Parquet using DuckDB's COPY command with compression
            db.execute(f"""
                COPY {table_name} TO '{parquet_path}' (
                    FORMAT 'parquet',
                    COMPRESSION 'SNAPPY'
                )
            """)
            
            # Drop temporary table and close connection
            db.execute(f"DROP TABLE {table_name}")
            db.close()
            
            # Move the file to its final destination
            final_path = self.data_dir / f"{filename}.parquet"
            shutil.move(str(parquet_path), str(final_path))
            
            return final_path
            
        except Exception as e:
            logger.error(f"Error converting {filename} to Parquet: {e}", exc_info=True)
            return None
        finally:
            # Clean up temporary resources
            try:
                if 'file_temp_dir' in locals() and file_temp_dir.exists():
                    shutil.rmtree(str(file_temp_dir))
                if 'db' in locals():
                    db.close()
            except Exception as cleanup_error:
                logger.warning(f"Error cleaning up temporary resources: {cleanup_error}")
    
    def _load_stops(self) -> None:
        """Load stops from stops.txt into memory."""
        parquet_path = self._csv_to_parquet("stops.txt")
        if not parquet_path:
            return

        # First, get the available columns by loading just a few rows
        self.db.execute(f"""
            CREATE TEMP TABLE temp_stops AS 
            SELECT * FROM parquet_scan('{parquet_path}') LIMIT 5
        """)
        columns = self.db.execute("DESCRIBE temp_stops").fetchdf()['column_name'].tolist()

        # Build the query dynamically based on available columns
        optional_columns = {
            'location_type': '0',  # Default to 0 for stops
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
            select_parts.append(f"COALESCE(NULLIF({col}, ''), {default}) as {col}" if col in columns else f"{default} as {col}")

        # Drop temporary table before creating the final one
        self.db.execute("DROP TABLE temp_stops")

        # Create the final stops table with all data
        query = f"""
            CREATE TEMP TABLE temp_stops AS
            WITH raw_stops AS (
                SELECT * FROM parquet_scan('{parquet_path}')
            )
            SELECT 
                stop_id::VARCHAR as stop_id,
                stop_name::VARCHAR as stop_name,
                CAST(stop_lat AS DOUBLE) as stop_lat,
                CAST(stop_lon AS DOUBLE) as stop_lon,
                CASE 
                    WHEN location_type IS NULL THEN 0
                    ELSE CAST(location_type AS INTEGER)
                END as location_type,
                parent_station::VARCHAR as parent_station,
                NULL::VARCHAR as platform_code,
                NULL::VARCHAR as stop_timezone
            FROM raw_stops;
            
            SELECT * FROM temp_stops;
        """
        result = self.db.execute(query).fetchdf()
        
        # Create Stop objects
        for _, row in result.iterrows():
            stop = Stop(
                id=str(row['stop_id']),
                name=str(row['stop_name']),
                lat=float(row['stop_lat']),
                lon=float(row['stop_lon']),
                translations=self.translations.get(str(row['stop_id']), {}),
                location_type=int(row['location_type']),  # Now safe because we handle NaN with COALESCE
                parent_station=str(row['parent_station']) if pd.notna(row['parent_station']) else None,
                platform_code=str(row['platform_code']) if pd.notna(row['platform_code']) else None,
                timezone=str(row['stop_timezone']) if pd.notna(row['stop_timezone']) else None
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
        
        try:
            # Drop existing table and indices if they exist
            self.db.execute("DROP TABLE IF EXISTS stop_times")
            self.db.execute("DROP INDEX IF EXISTS idx_stop_times_trip_stop")
            self.db.execute("DROP INDEX IF EXISTS idx_stop_times_stop_seq")
            
            # Create stop_times table with proper time formatting
            self.db.execute(f"""
                CREATE TABLE stop_times AS 
                SELECT 
                    trip_id,
                    -- Handle times that might exceed 24:00:00 (service past midnight)
                    CASE 
                        WHEN arrival_time ~ '^[0-9]{1,2}:[0-9]{2}:[0-9]{2}$' 
                        THEN arrival_time 
                        ELSE REGEXP_REPLACE(arrival_time, '^([0-9]{2,3}):', '\\1:')
                    END as arrival_time,
                    CASE 
                        WHEN departure_time ~ '^[0-9]{1,2}:[0-9]{2}:[0-9]{2}$' 
                        THEN departure_time 
                        ELSE REGEXP_REPLACE(departure_time, '^([0-9]{2,3}):', '\\1:')
                    END as departure_time,
                    stop_id,
                    CAST(stop_sequence AS INTEGER) as stop_sequence
                FROM parquet_scan('{parquet_path}')
                WHERE 
                    arrival_time IS NOT NULL 
                    AND departure_time IS NOT NULL 
                    AND stop_id IS NOT NULL
                    AND stop_sequence IS NOT NULL
                /*+ PARALLEL({num_threads}) */
            """)
            
            # Log table info
            count = self.db.execute("SELECT COUNT(*) FROM stop_times").fetchone()[0]
            logger.info(f"Loaded {count} stop times")
            
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
            
            # Verify data quality
            sample = self.db.execute("""
                SELECT * FROM stop_times 
                WHERE NOT (
                    arrival_time ~ '^[0-9]{1,3}:[0-9]{2}:[0-9]{2}$' 
                    AND departure_time ~ '^[0-9]{1,3}:[0-9]{2}:[0-9]{2}$'
                )
                LIMIT 5
            """).fetchdf()
            
            if not sample.empty:
                logger.warning(f"Found some potentially invalid time formats:\n{sample}")
            
            logger.info("Stop times loading complete")
            
        except Exception as e:
            logger.error(f"Error loading stop times: {e}", exc_info=True)
            # Try to clean up if something went wrong
            self.db.execute("DROP TABLE IF EXISTS stop_times")
            self.db.execute("DROP INDEX IF EXISTS idx_stop_times_trip_stop")
            self.db.execute("DROP INDEX IF EXISTS idx_stop_times_stop_seq")
            raise  # Re-raise the exception to be handled by the caller
    
    def _load_trips(self) -> None:
        """Load trips data into DuckDB."""
        parquet_path = self._csv_to_parquet('trips.txt')
        if not parquet_path:
            logger.error("Failed to convert trips.txt to Parquet")
            return
            
        logger.info("Loading trips table...")
        
        try:
            # Drop existing table and indices if they exist
            self.db.execute("DROP TABLE IF EXISTS trips")
            self.db.execute("DROP INDEX IF EXISTS trips_trip_id_idx")
            self.db.execute("DROP INDEX IF EXISTS trips_route_id_idx")
            self.db.execute("DROP INDEX IF EXISTS trips_service_id_idx")
            
            # First, verify the Parquet file has data
            sample_df = self.db.execute(f"SELECT * FROM parquet_scan('{parquet_path}') LIMIT 5").fetchdf()
            if sample_df.empty:
                logger.error("Parquet file appears to be empty")
                return
                
            logger.info(f"Sample data from trips.txt:\n{sample_df}")
            
            # Get the available columns
            columns = sample_df.columns.tolist()
            logger.info(f"Available columns: {columns}")
            
            # Build the query dynamically based on available columns
            required_columns = ['route_id', 'service_id', 'trip_id']
            optional_columns = {
                'trip_headsign': 'NULL',
                'direction_id': '0',
                'block_id': 'NULL',
                'shape_id': 'NULL'
            }
            
            # Verify required columns exist
            missing_columns = [col for col in required_columns if col not in columns]
            if missing_columns:
                logger.error(f"Missing required columns in trips.txt: {missing_columns}")
                return
                
            # Build select parts
            select_parts = required_columns.copy()
            for col, default in optional_columns.items():
                select_parts.append(f"COALESCE({col}, {default}) as {col}" if col in columns else f"{default} as {col}")
            
            # Create trips table
            query = f"""
                CREATE TABLE trips AS 
                SELECT 
                    {', '.join(select_parts)}
                FROM parquet_scan('{parquet_path}')
            """
            logger.info(f"Creating trips table with query: {query}")
            self.db.execute(query)
            
            # Verify data was loaded
            count = self.db.execute("SELECT COUNT(*) as count FROM trips").fetchone()[0]
            if count == 0:
                logger.error("No trips were loaded into the table")
                return
                
            logger.info(f"Created trips table with {count} trips")
            
            # Log some sample data
            sample = self.db.execute("SELECT * FROM trips LIMIT 5").fetchdf()
            logger.info(f"Sample trips data:\n{sample}")
            
            # Create indices
            logger.info("Creating indices...")
            self.db.execute("CREATE INDEX trips_trip_id_idx ON trips(trip_id)")
            self.db.execute("CREATE INDEX trips_route_id_idx ON trips(route_id)")
            self.db.execute("CREATE INDEX trips_service_id_idx ON trips(service_id)")
            
            # Verify the indices were created
            indices = self.db.execute("SELECT * FROM duckdb_indexes() WHERE table_name = 'trips'").fetchdf()
            logger.info(f"Created indices for trips table:\n{indices}")
            
            logger.info("Trips loading complete")
            
        except Exception as e:
            logger.error(f"Error loading trips: {e}", exc_info=True)
            # Clean up if something went wrong
            self.db.execute("DROP TABLE IF EXISTS trips")
            self.db.execute("DROP INDEX IF EXISTS trips_trip_id_idx")
            self.db.execute("DROP INDEX IF EXISTS trips_route_id_idx")
            self.db.execute("DROP INDEX IF EXISTS trips_service_id_idx")
            raise  # Re-raise the exception to be handled by the caller
    
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
    
    def _load_routes(self, trip_ids: Optional[List[str]] = None) -> List[Route]:
        """Load routes from DuckDB as Route objects."""
        logger.info("Starting route loading...")
        routes = []
        
        # First load routes into DuckDB if not already loaded
        parquet_path = self._csv_to_parquet('routes.txt')
        if not parquet_path:
            logger.error("Failed to convert routes.txt to Parquet")
            raise RuntimeError("Failed to convert routes.txt to Parquet")
        
        # Check if routes table exists
        has_routes = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'routes'
            )
        """).fetchone()[0]
        
        if not has_routes:
            logger.info("Creating routes table...")
            self.db.execute(f"""
                CREATE TABLE routes AS 
                SELECT * FROM parquet_scan('{parquet_path}')
            """)
            
            # Create index for faster lookups
            self.db.execute("CREATE INDEX idx_routes_id ON routes(route_id)")
            logger.info("Routes table created with index")
        
        # Base query for routes
        base_query = """
            SELECT DISTINCT r.*, t.service_id, t.trip_id
            FROM routes r
            JOIN trips t ON r.route_id = t.route_id
        """
        
        # Add trip_id filter if provided
        if trip_ids:
            base_query += " WHERE t.trip_id IN (SELECT UNNEST(?))"
            result = self.db.execute(base_query, [trip_ids]).fetchdf()
        else:
            result = self.db.execute(base_query).fetchdf()
        
        if result.empty:
            logger.warning("No routes found")
            return []
            
        # Group by route_id to get service_ids for each route
        for route_id, group in result.groupby('route_id'):
            first_row = group.iloc[0]
            
            # Get service days for this route's services
            service_ids = set(group['service_id'].dropna())
            service_days = list(self._get_service_days(service_ids))
            if not service_days:
                logger.warning(f"No service days found for route {route_id}")
                continue
            
            # Get stops for this route's first trip
            trip_id = str(first_row['trip_id'])
            stops_query = """
                SELECT 
                    st.stop_id,
                    st.arrival_time,
                    st.departure_time,
                    st.stop_sequence
                FROM stop_times st
                WHERE st.trip_id = ?
                ORDER BY st.stop_sequence
            """
            stops_result = self.db.execute(stops_query, [trip_id]).fetchdf()
            
            # Create RouteStop objects
            route_stops = []
            for _, stop_row in stops_result.iterrows():
                stop_id = str(stop_row['stop_id'])
                if stop_id not in self.stops:
                    logger.warning(f"Stop {stop_id} not found in stops dictionary")
                    continue
                
                route_stop = RouteStop(
                    stop=self.stops[stop_id],
                    arrival_time=stop_row['arrival_time'],
                    departure_time=stop_row['departure_time'],
                    stop_sequence=int(stop_row['stop_sequence'])
                )
                route_stops.append(route_stop)
            
            # Create route object with all service day information
            route = Route(
                route_name=str(first_row['route_long_name']) if pd.notna(first_row['route_long_name']) else f"Route {route_id}",
                trip_id=str(first_row['trip_id']),
                stops=route_stops,  # Now populated with actual stops
                route_id=str(route_id),
                short_name=str(first_row['route_short_name']) if pd.notna(first_row['route_short_name']) else None,
                long_name=str(first_row['route_long_name']) if pd.notna(first_row['route_long_name']) else None,
                route_desc=str(first_row['route_desc']) if 'route_desc' in first_row and pd.notna(first_row['route_desc']) else None,
                route_type=int(first_row['route_type']),
                route_url=str(first_row['route_url']) if 'route_url' in first_row and pd.notna(first_row['route_url']) else None,
                color=str(first_row['route_color']) if pd.notna(first_row['route_color']) else None,
                text_color=str(first_row['route_text_color']) if pd.notna(first_row['route_text_color']) else None,
                service_days=service_days,
                translations=self.translations.get(str(route_id), {}),
                service_days_explicit=self._get_service_days_explicit(service_ids),
                calendar_dates_additions=self._get_calendar_dates_additions(service_ids),
                calendar_dates_removals=self._get_calendar_dates_removals(service_ids),
                valid_calendar_days=self._get_valid_calendar_days(service_ids)
            )
            routes.append(route)
            logger.debug(f"Created route {route_id} with {len(route_stops)} stops and service days {service_days}")
        
        logger.info(f"Loaded {len(routes)} routes")
        return routes
    
    def _load_calendar(self) -> None:
        """Load calendar data into DuckDB using parallel processing."""
        calendar_path = self._csv_to_parquet('calendar.txt')
        calendar_dates_path = self._csv_to_parquet('calendar_dates.txt')
        
        # Use multiple threads but limit based on available memory
        num_threads = min(2, os.cpu_count() or 1)  # Conservative for RPi
        
        try:
            # Drop existing tables if they exist
            self.db.execute("DROP TABLE IF EXISTS calendar")
            self.db.execute("DROP TABLE IF EXISTS calendar_dates")
            
            if calendar_path:
                logger.info("Creating calendar table...")
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
                        start_date,
                        end_date
                    FROM parquet_scan('{calendar_path}')
                    /*+ PARALLEL({num_threads}) */
                """)
                
                # Create index
                self.db.execute("CREATE INDEX idx_calendar_service_id ON calendar(service_id)")
                
                # Log some statistics
                count = self.db.execute("SELECT COUNT(*) FROM calendar").fetchone()[0]
                logger.info(f"Created calendar table with {count} entries")
                
                # Log a sample
                sample = self.db.execute("SELECT * FROM calendar LIMIT 5").fetchdf()
                logger.info(f"Sample calendar entries:\n{sample}")
            else:
                logger.warning("No calendar.txt found")
            
            if calendar_dates_path:
                logger.info("Creating calendar_dates table...")
                self.db.execute(f"""
                    CREATE TABLE calendar_dates AS 
                    SELECT 
                        service_id,
                        date,
                        CAST(exception_type AS INTEGER) as exception_type
                    FROM parquet_scan('{calendar_dates_path}')
                    /*+ PARALLEL({num_threads}) */
                """)
                
                # Create index
                self.db.execute("CREATE INDEX idx_calendar_dates_service_id ON calendar_dates(service_id)")
                
                # Log some statistics
                count = self.db.execute("SELECT COUNT(*) FROM calendar_dates").fetchone()[0]
                logger.info(f"Created calendar_dates table with {count} entries")
                
                # Log a sample
                sample = self.db.execute("SELECT * FROM calendar_dates LIMIT 5").fetchdf()
                logger.info(f"Sample calendar_dates entries:\n{sample}")
            else:
                logger.warning("No calendar_dates.txt found")
            
            # Verify tables were created
            tables = self.db.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name IN ('calendar', 'calendar_dates')
            """).fetchdf()
            logger.info(f"Created tables: {tables['table_name'].tolist()}")
        
        except Exception as e:
            logger.error(f"Error loading calendar data: {e}", exc_info=True)
            # Clean up if something went wrong
            self.db.execute("DROP TABLE IF EXISTS calendar")
            self.db.execute("DROP TABLE IF EXISTS calendar_dates")
            raise
    
    def load_feed(
        self, 
        target_stops: Optional[Set[str]] = None
    ) -> FlixbusFeed:
        """Load the GTFS feed into DuckDB and return a FlixbusFeed object."""
        logger.info("Starting GTFS feed loading...")
        
        try:
            # Set up DuckDB configuration first
            self._setup_db()

            # Load translations first (doesn't require DuckDB)
            self.translations = load_translations(self.data_dir)
            logger.info(f"Loaded {len(self.translations)} translations")
            
            # Load calendar data first as it's needed for route service days
            logger.info("Loading calendar data...")
            self._load_calendar()
            
            # Load only the essential components initially
            logger.info("Loading stops...")
            self._load_stops()
            logger.info(f"Loaded {len(self.stops)} stops")
            
            # Load stop times and trips before routes to enable filtering
            logger.info("Loading stop times...")
            self._load_stop_times()
            
            logger.info("Loading trips...")
            self._load_trips()

            # If we have target stops, pre-filter the trips that contain them
            if target_stops:
                logger.info(f"Pre-filtering trips containing stops: {target_stops}")
                trip_ids = self.db.execute("""
                    SELECT DISTINCT trip_id 
                    FROM stop_times 
                    WHERE stop_id IN (
                        SELECT UNNEST(?)
                    )
                """, [list(target_stops)]).fetchdf()['trip_id'].tolist()
                
                logger.info(f"Found {len(trip_ids)} trips containing target stops")
            else:
                trip_ids = None
            
            logger.info("Loading routes...")
            routes = self._load_routes(trip_ids)
            logger.info(f"Loaded {len(routes)} routes")
            
            # Get calendars and calendar dates objects
            logger.info("Creating calendar objects...")
            calendars = self._get_calendars()
            calendar_dates = self._get_calendar_dates()
            logger.info(f"Created {len(calendars)} calendar objects and {len(calendar_dates)} calendar date objects")

            # Load agencies
            logger.info("Loading agencies...")
            agencies = self._load_agencies()
            logger.info(f"Loaded {len(agencies)} agencies")
            
            logger.info("Creating FlixbusFeed object...")
            feed = FlixbusFeed(
                stops=self.stops,
                routes=routes,
                calendars=calendars,
                calendar_dates=calendar_dates,
                trips={},
                stop_times_dict={},
                agencies=agencies,
                translations=self.translations
            )

            # Set feed reference on all routes
            logger.info("Setting feed reference on routes...")
            for route in routes:
                route._feed = feed
                #logger.debug(f"Set feed reference for route {route.route_id}")

            logger.info("GTFS feed loading completed successfully")
            return feed
        except Exception as e:
            logger.error(f"Error loading GTFS feed: {e}", exc_info=True)
            raise RuntimeError(f"Failed to load GTFS data: {str(e)}")
        finally:
            # Clean up any temporary tables
            try:
                self.db.execute("DROP TABLE IF EXISTS temp_stops")
                self.db.execute("DROP TABLE IF EXISTS temp_trips")
                self.db.execute("DROP TABLE IF EXISTS temp_routes")
                self.db.execute("DROP TABLE IF EXISTS temp_agencies")
            except:
                pass
    
    def find_routes_between_stations(self, start_id: str, end_id: str) -> List[Dict]:
        """Find all routes between two stations."""
        if not start_id or not end_id:
            logger.warning("Invalid station IDs provided")
            return []

        if start_id not in self.stops:
            logger.warning(f"Start station not found: {start_id}")
            return []
            
        if end_id not in self.stops:
            logger.warning(f"End station not found: {end_id}")
            return []

        try:
            logger.info(f"Searching for routes between stations {start_id} and {end_id}")
            
            # First check if the tables exist
            tables_exist = self.db.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'stop_times'
                ) AND EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'trips'
                ) AND EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'routes'
                ) AND EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'stops'
                )
            """).fetchone()[0]
            
            if not tables_exist:
                logger.error("Required tables do not exist. Make sure the GTFS feed is loaded properly.")
                return []

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
                    COALESCE(r.route_short_name, '') as route_short_name,
                    COALESCE(r.route_long_name, '') as route_long_name,
                    t.trip_id,
                    COALESCE(t.trip_headsign, '') as trip_headsign,
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
            
            result = self.db.execute(query, [start_id, end_id])
            if result is None:
                logger.warning("Query returned None result")
                return []
                
            df = result.fetchdf()
            if df is None:
                logger.warning("Failed to fetch results as DataFrame")
                return []
                
            if df.empty:
                logger.info(f"No routes found between stations {start_id} and {end_id}")
                return []
                
            # Log some statistics about the results
            trip_count = len(df['trip_id'].unique())
            route_count = len(df['route_id'].unique())
            logger.info(f"Found {trip_count} trips on {route_count} routes between stations")
                
            return self._process_route_results(df)
            
        except Exception as e:
            logger.error(f"Error finding routes between stations: {e}", exc_info=True)
            return []
    
    def _process_route_results(self, df: pd.DataFrame) -> List[Dict]:
        """Process the route search results into a structured format."""
        if df is None or df.empty:
            logger.warning("No route results to process")
            return []
            
        routes = []
        try:
            # Get unique trip IDs and process each trip
            trip_ids = df['trip_id'].unique()
            if trip_ids is None or len(trip_ids) == 0:
                logger.warning("No valid trips found in results")
                return []
                
            for trip_id in trip_ids:
                if pd.isna(trip_id):
                    logger.debug(f"Skipping invalid trip ID: {trip_id}")
                    continue
                    
                trip_df = df[df['trip_id'] == trip_id].copy()
                if trip_df.empty:
                    logger.debug(f"No data found for trip {trip_id}")
                    continue
                
                # Ensure stops are in sequence
                trip_df.sort_values('stop_sequence', inplace=True)
                
                # Get route info, with fallbacks for missing data
                try:
                    route = {
                        'route_id': str(trip_df['route_id'].iloc[0]),
                        'route_name': (
                            str(trip_df['route_long_name'].iloc[0]) if not pd.isna(trip_df['route_long_name'].iloc[0]) else
                            str(trip_df['route_short_name'].iloc[0]) if not pd.isna(trip_df['route_short_name'].iloc[0]) else
                            f"Route {str(trip_df['route_id'].iloc[0])}"
                        ),
                        'trip_id': str(trip_id),
                        'headsign': str(trip_df['trip_headsign'].iloc[0]) if not pd.isna(trip_df['trip_headsign'].iloc[0]) else None,
                        'stops': []
                    }
                except Exception as e:
                    logger.error(f"Error creating route info for trip {trip_id}: {e}", exc_info=True)
                    continue
                
                valid_stops = []  # Collect valid stops first
                for _, row in trip_df.iterrows():
                    try:
                        stop_id = str(row['stop_id'])
                        if pd.isna(stop_id) or stop_id not in self.stops:
                            logger.warning(f"Invalid stop ID {stop_id} for trip {trip_id}")
                            continue
                            
                        # Create Stop object
                        stop = Stop(
                            id=str(row['stop_id']),
                            name=str(row['stop_name']),
                            lat=float(row['stop_lat']),
                            lon=float(row['stop_lon']),
                            translations=self.stops[stop_id].translations if stop_id in self.stops else {}
                        )
                        
                        # Create RouteStop object
                        route_stop = RouteStop(
                            stop=stop,
                            arrival_time=row['arrival_time'],
                            departure_time=row['departure_time'],
                            stop_sequence=int(row['stop_sequence'])
                        )
                        
                        valid_stops.append(route_stop)
                    except Exception as e:
                        logger.error(f"Error processing stop for trip {trip_id}: {e}", exc_info=True)
                        continue
                
                if len(valid_stops) >= 2:  # Only add routes with at least 2 stops
                    route['stops'] = valid_stops
                    routes.append(route)
                else:
                    logger.warning(f"Trip {trip_id} has fewer than 2 valid stops, skipping")
            
            if not routes:
                logger.warning("No valid routes found after processing")
            else:
                logger.info(f"Found {len(routes)} valid routes")
                
            return routes
            
        except Exception as e:
            logger.error(f"Error processing route results: {e}", exc_info=True)
            return []
    
    def close(self):
        """Close the DuckDB connection and clean up resources."""
        try:
            if hasattr(self, 'db'):
                self.db.close()
            if hasattr(self, '_temp_dir') and self._temp_dir.exists():
                shutil.rmtree(str(self._temp_dir))
        except Exception as e:
            logger.warning(f"Error closing DuckDB connection: {e}")

    def __del__(self):
        """Ensure resources are cleaned up when the object is deleted."""
        self.close()
    
    def _get_service_days(self, service_ids: Set[str]) -> Set[str]:
        """Get the service days for a set of service IDs."""
        logger.info(f"Calculating service days for service IDs: {service_ids}")
        service_days = set()
        
        # Check if calendar table exists
        has_calendar = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'calendar'
            )
        """).fetchone()[0]
        logger.info(f"Calendar table exists: {has_calendar}")
        
        # Check if calendar_dates table exists
        has_calendar_dates = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'calendar_dates'
            )
        """).fetchone()[0]
        logger.info(f"Calendar dates table exists: {has_calendar_dates}")
        
        # If neither table exists, we can't determine service days
        if not has_calendar and not has_calendar_dates:
            logger.warning("Neither calendar.txt nor calendar_dates.txt found - assuming service runs every day")
            return {'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}
        
        if has_calendar:
            # First check regular calendar
            calendar_query = """
                SELECT 
                    service_id,
                    monday, tuesday, wednesday, thursday, friday, saturday, sunday,
                    start_date, end_date
                FROM calendar
                WHERE service_id = ?
                AND CAST(
                    CONCAT(
                        SUBSTR(start_date, 1, 4), '-',
                        SUBSTR(start_date, 5, 2), '-',
                        SUBSTR(start_date, 7, 2)
                    ) AS DATE
                ) <= CURRENT_DATE
                AND CAST(
                    CONCAT(
                        SUBSTR(end_date, 1, 4), '-',
                        SUBSTR(end_date, 5, 2), '-',
                        SUBSTR(end_date, 7, 2)
                    ) AS DATE
                ) >= CURRENT_DATE
            """
            
            for service_id in service_ids:
                # Check regular calendar
                calendar_result = self.db.execute(calendar_query, [service_id]).fetchdf()
                logger.debug(f"Calendar query result for service_id {service_id}:\n{calendar_result}")
                
                if not calendar_result.empty:
                    row = calendar_result.iloc[0]
                    # Only consider this calendar if it has at least one day set to 1
                    if any([row['monday'], row['tuesday'], row['wednesday'], row['thursday'], 
                           row['friday'], row['saturday'], row['sunday']]):
                        logger.debug(f"Found regular calendar for service {service_id}")
                        if row['monday']: service_days.add('monday')
                        if row['tuesday']: service_days.add('tuesday')
                        if row['wednesday']: service_days.add('wednesday')
                        if row['thursday']: service_days.add('thursday')
                        if row['friday']: service_days.add('friday')
                        if row['saturday']: service_days.add('saturday')
                        if row['sunday']: service_days.add('sunday')
                        logger.debug(f"Service days after calendar check: {service_days}")
        
        if has_calendar_dates:
            # Then check calendar_dates.txt for type 1 exceptions (added service)
            calendar_dates_query = """
                SELECT service_id, date, exception_type
                FROM calendar_dates
                WHERE service_id = ?
                AND CAST(
                    CONCAT(
                        SUBSTR(date, 1, 4), '-',
                        SUBSTR(date, 5, 2), '-',
                        SUBSTR(date, 7, 2)
                    ) AS DATE
                ) >= CURRENT_DATE
                AND CAST(
                    CONCAT(
                        SUBSTR(date, 1, 4), '-',
                        SUBSTR(date, 5, 2), '-',
                        SUBSTR(date, 7, 2)
                    ) AS DATE
                ) <= date_add(CURRENT_DATE, INTERVAL 3 MONTH)  -- Look ahead 3 months
            """
            
            for service_id in service_ids:
                dates_result = self.db.execute(calendar_dates_query, [service_id]).fetchdf()
                logger.debug(f"Calendar dates query result for service_id {service_id}:\n{dates_result}")
                
                if not dates_result.empty:
                    # Only consider type 1 exceptions (additions)
                    additions = dates_result[dates_result['exception_type'] == 1]
                    for _, row in additions.iterrows():
                        weekday = datetime.strptime(str(row['date']), '%Y%m%d').strftime('%A').lower()
                        service_days.add(weekday)
                        logger.debug(f"Added service day {weekday} from calendar_dates for service {service_id}")
                    
                    # If we have regular calendar, check for type 2 exceptions (removals)
                    if has_calendar:
                        removals = dates_result[dates_result['exception_type'] == 2]
                        if not removals.empty:
                            # Group removals by weekday
                            removals_by_day = {}
                            for _, row in removals.iterrows():
                                weekday = datetime.strptime(str(row['date']), '%Y%m%d').strftime('%A').lower()
                                if weekday not in removals_by_day:
                                    removals_by_day[weekday] = set()
                                removals_by_day[weekday].add(service_id)
                            
                            # Remove days that are completely excluded by type 2 exceptions
                            for day, removed_services in removals_by_day.items():
                                if removed_services == service_ids:  # All services have this day removed
                                    service_days.discard(day)
                                    logger.debug(f"Removed service day {day} due to type 2 exception")
        
        # If we still have no service days after checking both tables, assume service runs every day
        if not service_days:
            logger.warning(f"No service days found for services {service_ids} - assuming service runs every day")
            service_days = {'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}
        
        logger.info(f"Final service days for {service_ids}: {sorted(list(service_days))}")
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
        
        return trips
    
    def _get_calendars(self) -> Dict[str, Calendar]:
        """Get calendars from DuckDB as Calendar objects."""
        logger.info("Starting calendar data loading...")
        calendars = {}
        
        # Check if calendar table exists
        has_calendar = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'calendar'
            )
        """).fetchone()[0]
        
        logger.info(f"Calendar table exists: {has_calendar}")
        
        if has_calendar:
            result = self.db.execute("""
                SELECT 
                    service_id,
                    monday, tuesday, wednesday, thursday, friday, saturday, sunday,
                    start_date,
                    end_date
                FROM calendar
            """).fetchdf()
            
            logger.info(f"Found {len(result)} calendar entries")
            logger.info(f"Sample calendar data:\n{result.head()}")
            
            for _, row in result.iterrows():
                try:
                    # Convert date strings to datetime objects if they're strings
                    start_date = row['start_date']
                    end_date = row['end_date']
                    if isinstance(start_date, str):
                        start_date = datetime.strptime(start_date, '%Y%m%d')
                    if isinstance(end_date, str):
                        end_date = datetime.strptime(end_date, '%Y%m%d')

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
                        start_date=start_date,
                        end_date=end_date
                    )
                    #logger.debug(f"Created calendar for service_id {service_id}: {calendars[service_id]}")
                except Exception as e:
                    logger.error(f"Error creating Calendar object for service_id {row['service_id']}: {e}", exc_info=True)
                    continue
        
        logger.info(f"Loaded {len(calendars)} calendar entries")
        return calendars
    
    def _get_calendar_dates(self) -> List[CalendarDate]:
        """Get calendar dates from DuckDB as CalendarDate objects."""
        logger.info("Starting calendar dates loading...")
        calendar_dates = []
        
        # Check if calendar_dates table exists
        has_calendar_dates = self.db.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = 'calendar_dates'
            )
        """).fetchone()[0]
        
        logger.info(f"Calendar dates table exists: {has_calendar_dates}")
        
        if has_calendar_dates:
            result = self.db.execute("""
                SELECT 
                    service_id,
                    date,
                    exception_type
                FROM calendar_dates
            """).fetchdf()
            
            logger.info(f"Found {len(result)} calendar date entries")
            logger.info(f"Sample calendar dates:\n{result.head()}")
            
            for _, row in result.iterrows():
                try:
                    # Convert date string to datetime object if it's a string
                    date = row['date']
                    if isinstance(date, str):
                        date = datetime.strptime(date, '%Y%m%d')

                    service_id = str(row['service_id'])
                    calendar_date = CalendarDate(
                        service_id=service_id,
                        date=date,
                        exception_type=int(row['exception_type'])
                    )
                    calendar_dates.append(calendar_date)
                    #logger.debug(f"Created calendar date for service_id {service_id}: {calendar_date}")
                except Exception as e:
                    logger.error(f"Error creating CalendarDate object for service_id {row['service_id']}: {e}", exc_info=True)
                    continue
        
        logger.info(f"Loaded {len(calendar_dates)} calendar date entries")
        return calendar_dates

    def get_stops_in_bbox(self, bbox: BoundingBox, count_only: bool = False) -> Union[List[Stop], Dict[str, int]]:
        """Get all stops within a bounding box."""
        logger.debug(f"Getting stops in bbox: {bbox}")
        
        query = """
            SELECT *
            FROM stops
            WHERE stop_lat BETWEEN ? AND ?
            AND stop_lon BETWEEN ? AND ?
        """
        
        result = self.db.execute(query, [bbox.min_lat, bbox.max_lat, bbox.min_lon, bbox.max_lon]).fetchdf()
        
        if count_only:
            return {"count": len(result)}

        stops = []
        for _, row in result.iterrows():
            stop = Stop(
                id=str(row['stop_id']),
                name=str(row['stop_name']),
                lat=float(row['stop_lat']),
                lon=float(row['stop_lon']),
                translations=self.translations.get(str(row['stop_id']), {}),
                location_type=int(row['location_type']),  # Now safe because we handle NaN with COALESCE
                parent_station=str(row['parent_station']) if pd.notna(row['parent_station']) else None,
                platform_code=str(row['platform_code']) if pd.notna(row['platform_code']) else None,
                timezone=str(row['stop_timezone']) if pd.notna(row['stop_timezone']) else None
            )
            stops.append(stop)
        
        return stops or []

    def _load_agencies(self) -> Dict[str, Agency]:
        """Load agencies from agency.txt into DuckDB.

        Returns:
            Dict mapping agency_id to Agency objects.
        """
        parquet_path = self._csv_to_parquet('agency.txt')
        if not parquet_path:
            logger.warning("No agency.txt found")
            return {}

        logger.info("Loading agencies...")
        try:
            # First, get the available columns
            self.db.execute(f"""
                CREATE TEMP TABLE temp_agencies AS 
                SELECT * FROM read_parquet('{parquet_path}')
            """)
            columns = self.db.execute("DESCRIBE temp_agencies").fetchdf()['column_name'].tolist()

            # Build the query dynamically based on available columns
            select_parts = [
                'agency_id',
                'agency_name',
                'agency_url',
                'agency_timezone'
            ]

            optional_columns = {
                'agency_lang': 'NULL',
                'agency_phone': 'NULL',
                'agency_fare_url': 'NULL',
                'agency_email': 'NULL'
            }

            for col, default in optional_columns.items():
                if col in columns:
                    select_parts.append(f"COALESCE({col}, {default}) as {col}")
                else:
                    select_parts.append(f"{default} as {col}")

            # Create agencies table
            self.db.execute(f"""
                CREATE TABLE agencies AS 
                SELECT 
                    {', '.join(select_parts)}
                FROM temp_agencies
            """)

            # Create index
            self.db.execute("DROP INDEX IF EXISTS idx_agency_id")
            self.db.execute("CREATE INDEX idx_agency_id ON agencies(agency_id)")

            # Get agency data
            result = self.db.execute("""
                SELECT * FROM agencies
            """).fetchdf()

            agencies = {}
            for _, row in result.iterrows():
                agency = Agency(
                    agency_id=str(row['agency_id']),
                    agency_name=str(row['agency_name']),
                    agency_url=str(row['agency_url']),
                    agency_timezone=str(row['agency_timezone']),
                    agency_lang=str(row['agency_lang']) if pd.notna(row['agency_lang']) else None,
                    agency_phone=str(row['agency_phone']) if pd.notna(row['agency_phone']) else None,
                    agency_fare_url=str(row['agency_fare_url']) if pd.notna(row['agency_fare_url']) else None,
                    agency_email=str(row['agency_email']) if pd.notna(row['agency_email']) else None
                )
                agencies[agency.agency_id] = agency

            logger.info(f"Loaded {len(agencies)} agencies")
            return agencies

        except Exception as e:
            logger.error(f"Error loading agencies: {e}", exc_info=True)
            return {}
        finally:
            # Clean up temporary table
            self.db.execute("DROP TABLE IF EXISTS temp_agencies")

    def find_trips_between_stations(self, start_id: str, end_id: str) -> List[Route]:
        """Find all trips/services between two stations, including duplicates for different times."""
        if not start_id or not end_id:
            logger.warning("Invalid station IDs provided")
            return []

        if start_id not in self.stops:
            logger.warning(f"Start station not found: {start_id}")
            return []
            
        if end_id not in self.stops:
            logger.warning(f"End station not found: {end_id}")
            return []

        try:
            logger.info(f"Searching for trips between stations {start_id} and {end_id}")
            
            # First check if the tables exist
            tables_exist = self.db.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'stop_times'
                ) AND EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'trips'
                ) AND EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'routes'
                ) AND EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'stops'
                )
            """).fetchone()[0]
            
            if not tables_exist:
                logger.error("Required tables do not exist. Make sure the GTFS feed is loaded properly.")
                return []

            # Find all trips that serve both stations in sequence
            query = """
            WITH stop_pairs AS (
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
                    COALESCE(r.route_short_name, '') as route_short_name,
                    COALESCE(r.route_long_name, '') as route_long_name,
                    t.trip_id,
                    COALESCE(t.trip_headsign, '') as trip_headsign,
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
            
            logger.debug(f"Executing query to find trips: {query}")
            trips_df = self.db.execute(query, [start_id, end_id]).fetchdf()
            logger.debug(f"Found {len(trips_df) if not trips_df.empty else 0} trips")
            
            if trips_df.empty:
                # Let's check if the stops exist in stop_times
                stop_check = self.db.execute("""
                    SELECT stop_id, COUNT(*) as count
                    FROM stop_times
                    WHERE stop_id IN (?, ?)
                    GROUP BY stop_id
                """, [start_id, end_id]).fetchdf()
                logger.debug(f"Stop occurrences in stop_times: {stop_check}")
                return []

            routes = []
            for _, trip_row in trips_df.iterrows():
                trip_id = str(trip_row['trip_id'])
                route_id = str(trip_row['route_id'])
                logger.debug(f"Processing trip {trip_id} on route {route_id}")

                # Get all stops for this trip between start and end
                stops_query = """
                WITH trip_stops AS (
                    SELECT 
                        st1.stop_sequence as start_seq,
                        st2.stop_sequence as end_seq
                    FROM stop_times st1
                    JOIN stop_times st2 ON st1.trip_id = st2.trip_id
                    WHERE st1.trip_id = ?
                        AND st1.stop_id = ?
                        AND st2.stop_id = ?
                        AND st1.stop_sequence < st2.stop_sequence
                    LIMIT 1
                )
                SELECT 
                    st.stop_id,
                    st.arrival_time,
                    st.departure_time,
                    st.stop_sequence,
                    s.stop_name,
                    s.stop_lat,
                    s.stop_lon
                FROM stop_times st
                JOIN trip_stops ts ON st.stop_sequence BETWEEN ts.start_seq AND ts.end_seq
                JOIN stops s ON s.stop_id = st.stop_id
                WHERE st.trip_id = ?
                ORDER BY st.stop_sequence
                """
                
                logger.debug(f"Executing query to get stops for trip {trip_id}")
                stops_df = self.db.execute(stops_query, [trip_id, start_id, end_id, trip_id]).fetchdf()
                logger.debug(f"Found {len(stops_df) if not stops_df.empty else 0} stops for trip {trip_id}")
                
                if stops_df.empty:
                    continue

                # Create RouteStop objects
                route_stops = []
                for _, stop_row in stops_df.iterrows():
                    stop_id = str(stop_row['stop_id'])
                    if stop_id not in self.stops:
                        logger.warning(f"Stop {stop_id} not found in stops dictionary")
                        continue

                    route_stop = RouteStop(
                        stop=self.stops[stop_id],
                        arrival_time=stop_row['arrival_time'],
                        departure_time=stop_row['departure_time'],
                        stop_sequence=int(stop_row['stop_sequence'])
                    )
                    route_stops.append(route_stop)

                if len(route_stops) < 2:
                    logger.warning(f"Trip {trip_id} has fewer than 2 valid stops")
                    continue

                # Get service days for this trip
                service_days = list(self._get_service_days({str(trip_row['service_id'])}))
                logger.debug(f"Service days for trip {trip_id}: {service_days}")

                # Create Route object with trip-specific information
                route = Route(
                    route_id=route_id,
                    route_name=str(trip_row['route_long_name']) if pd.notna(trip_row['route_long_name']) else str(trip_row['route_short_name']) if pd.notna(trip_row['route_short_name']) else f"Route {route_id}",
                    trip_id=trip_id,
                    service_days=service_days,
                    stops=route_stops,
                    short_name=str(trip_row['route_short_name']) if pd.notna(trip_row['route_short_name']) else None,
                    long_name=str(trip_row['route_long_name']) if pd.notna(trip_row['route_long_name']) else None,
                    route_type=int(trip_row['route_type']) if pd.notna(trip_row['route_type']) else None,
                    color=str(trip_row['route_color']) if pd.notna(trip_row['route_color']) else None,
                    text_color=str(trip_row['route_text_color']) if pd.notna(trip_row['route_text_color']) else None,
                    agency_id=str(trip_row['agency_id']) if pd.notna(trip_row['agency_id']) else None,
                    service_ids=[str(trip_row['service_id'])],
                    direction_id=str(trip_row['direction_id']) if pd.notna(trip_row['direction_id']) else None
                )
                routes.append(route)
                logger.debug(f"Added route {route_id} with {len(route_stops)} stops")

            logger.info(f"Found {len(routes)} trips between stations {start_id} and {end_id}")
            return routes

        except Exception as e:
            logger.error(f"Error finding trips between stations: {e}", exc_info=True)
            return []

    def _get_service_days_explicit(self, service_ids: set[str]) -> List[str]:
        """Get explicit service days from calendar.txt."""
        if not service_ids:
            return []
        
        result = self.db.execute("""
            SELECT DISTINCT
                CASE WHEN monday = 1 THEN 'Monday' END as monday,
                CASE WHEN tuesday = 1 THEN 'Tuesday' END as tuesday,
                CASE WHEN wednesday = 1 THEN 'Wednesday' END as wednesday,
                CASE WHEN thursday = 1 THEN 'Thursday' END as thursday,
                CASE WHEN friday = 1 THEN 'Friday' END as friday,
                CASE WHEN saturday = 1 THEN 'Saturday' END as saturday,
                CASE WHEN sunday = 1 THEN 'Sunday' END as sunday
            FROM calendar
            WHERE service_id IN (SELECT UNNEST(?))
        """, [list(service_ids)]).fetchdf()
        
        days = []
        for _, row in result.iterrows():
            days.extend([day for day in row if pd.notna(day)])
        return sorted(list(set(days)))

    def _get_calendar_dates_additions(self, service_ids: set[str]) -> List[datetime]:
        """Get dates added via exceptions."""
        if not service_ids:
            return []
        
        result = self.db.execute("""
            SELECT DISTINCT date
            FROM calendar_dates
            WHERE service_id IN (SELECT UNNEST(?))
            AND exception_type = 1
            ORDER BY date
        """, [list(service_ids)]).fetchdf()
        
        return [datetime.strptime(date, '%Y%m%d') for date in result['date']]

    def _get_calendar_dates_removals(self, service_ids: set[str]) -> List[datetime]:
        """Get dates removed via exceptions."""
        if not service_ids:
            return []
        
        result = self.db.execute("""
            SELECT DISTINCT date
            FROM calendar_dates
            WHERE service_id IN (SELECT UNNEST(?))
            AND exception_type = 2
            ORDER BY date
        """, [list(service_ids)]).fetchdf()
        
        return [datetime.strptime(date, '%Y%m%d') for date in result['date']]

    def _get_valid_calendar_days(self, service_ids: set[str]) -> List[datetime]:
        """Get all valid service days."""
        if not service_ids:
            return []
        
        result = self.db.execute("""
            WITH service_days AS (
                SELECT service_id, start_date, end_date
                FROM calendar
                WHERE service_id IN (SELECT UNNEST(?))
            ),
            calendar_dates_exceptions AS (
                SELECT service_id, date, exception_type
                FROM calendar_dates
                WHERE service_id IN (SELECT UNNEST(?))
            ),
            date_series AS (
                SELECT DISTINCT
                    service_id,
                    unnest(
                        generate_series(
                            strptime(MIN(start_date), '%Y%m%d'),
                            strptime(MAX(end_date), '%Y%m%d'),
                            INTERVAL '1 day'
                        )
                    )::DATE as service_date
                FROM service_days
                GROUP BY service_id
            )
            SELECT DISTINCT 
                strftime(service_date, '%Y%m%d') as date
            FROM date_series d
            JOIN service_days s ON d.service_id = s.service_id
            WHERE service_date >= strptime(s.start_date, '%Y%m%d')::DATE
            AND service_date <= strptime(s.end_date, '%Y%m%d')::DATE
            AND service_date NOT IN (
                SELECT strptime(date, '%Y%m%d')::DATE
                FROM calendar_dates_exceptions
                WHERE service_id = d.service_id
                AND exception_type = 2
            )
            UNION
            SELECT DISTINCT date
            FROM calendar_dates_exceptions
            WHERE service_id IN (SELECT UNNEST(?))
            AND exception_type = 1
            ORDER BY date
        """, [list(service_ids), list(service_ids), list(service_ids)]).fetchdf()
        
        return [datetime.strptime(date, '%Y%m%d') for date in result['date']]


def load_feed(
    data_dir: str | Path = None, 
    target_stops: Optional[Set[str]] = None
) -> FlixbusFeed:
    """Load GTFS feed from the specified directory.
    If target_stops is provided, only loads routes that contain those stops.

    Args:
        data_dir: Path to the GTFS data directory. Can be either a string or Path object.
        target_stops: Optional set of stop IDs to filter routes by.

    Returns:
        FlixbusFeed object containing the loaded GTFS data.

    Raises:
        ValueError: If data_dir is None or does not exist.
        RuntimeError: If loading fails.
    """
    if not data_dir:
        raise ValueError("No data directory provided to load_feed()")
    
    # Convert data_dir to Path if it's a string
    data_path = Path(data_dir)

    if not data_path.exists():
        raise ValueError(f"Data directory does not exist: {data_path}")

    logger.info(f"Loading GTFS feed from: {data_path}")

    loader = ParquetGTFSLoader(data_dir)
    try:
        feed = loader.load_feed(target_stops=target_stops)
        if not isinstance(feed, FlixbusFeed):
            raise RuntimeError(f"Expected FlixbusFeed object but got {type(feed)}")
        return feed
    finally:
        loader.close()

