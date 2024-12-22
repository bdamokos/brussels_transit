from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta
import os
from pathlib import Path
import pandas as pd
import logging
import sys
import logging.config
import json
from mobility_db_api import MobilityAPI

from .models import RouteResponse, StationResponse, Route, Stop, Location, Shape, RouteInfo
from .gtfs_loader import FlixbusFeed, load_feed

# Configure download directory
DOWNLOAD_DIR = Path(os.getenv('GTFS_DOWNLOAD_DIR', Path(__file__).parent.parent.parent.parent / 'downloads'))

# Configure logging
def setup_logging():
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'default': {
                'level': 'INFO',
                'formatter': 'standard',
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stdout',
            },
        },
        'loggers': {
            '': {
                'handlers': ['default'],
                'level': 'INFO',
                'propagate': True
            }
        }
    }
    logging.config.dictConfig(logging_config)
    return logging.getLogger(__name__)

app = FastAPI(title="Schedule Explorer API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
feed: Optional[FlixbusFeed] = None
current_provider: Optional[str] = None
available_providers: List[Dict] = []
logger = setup_logging()

def find_gtfs_directories() -> List[Dict]:
    """Find all GTFS data directories in the downloads directory and their metadata."""
    providers = {}
    sanitized_names_count = {}  # Keep track of how many times each sanitized name appears
    
    # Collect metadata from downloads
    if DOWNLOAD_DIR.exists():
        metadata_file = DOWNLOAD_DIR / 'datasets_metadata.json'
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    
                    # First pass: count occurrences of sanitized names
                    for dataset_id, dataset_info in metadata.items():
                        provider_id = dataset_info.get('provider_id')
                        if provider_id:
                            dataset_dir = Path(dataset_info.get('download_path'))
                            if dataset_dir.exists():
                                sanitized_name = dataset_dir.parent.name.split('_', 1)[1] if '_' in dataset_dir.parent.name else dataset_dir.parent.name
                                sanitized_names_count[sanitized_name] = sanitized_names_count.get(sanitized_name, 0) + 1
                    
                    # Second pass: create provider entries with MDB numbers if needed
                    for dataset_id, dataset_info in metadata.items():
                        provider_id = dataset_info.get('provider_id')
                        if provider_id:
                            dataset_dir = Path(dataset_info.get('download_path'))
                            if dataset_dir.exists():
                                sanitized_name = dataset_dir.parent.name.split('_', 1)[1] if '_' in dataset_dir.parent.name else dataset_dir.parent.name
                                
                                # If this sanitized name appears more than once, append the MDB number
                                provider_key = sanitized_name
                                if sanitized_names_count[sanitized_name] > 1:
                                    provider_key = f"{sanitized_name}_{provider_id}"
                                
                                # Convert to the format expected by the frontend
                                providers[provider_key] = {
                                    'id': provider_key,  # Use sanitized name (with MDB if needed) as ID
                                    'raw_id': provider_id,  # Keep the raw ID for API calls
                                    'provider': dataset_info.get('provider_name'),
                                    'name': dataset_info.get('provider_name'),
                                    'latest_dataset': {
                                        'id': dataset_info.get('dataset_id'),
                                        'downloaded_at': dataset_info.get('download_date'),
                                        'hash': dataset_info.get('file_hash'),
                                        'hosted_url': dataset_info.get('source_url'),
                                        'validation_report': {
                                            'total_error': 0,  # We don't have this info yet
                                            'total_warning': 0,
                                            'total_info': 0
                                        }
                                    }
                                }
            except Exception as e:
                logger.error(f"Error reading metadata file {metadata_file}: {str(e)}")
    
    return list(providers.values())

@app.get("/api/providers/{country_code}", response_model=List[Dict])
async def get_providers_by_country(country_code: str):
    """Get list of available GTFS providers for a specific country"""
    try:
        db = MobilityAPI()
        providers = db.get_providers_by_country(country_code)
        # Add sanitized names to the providers
        for provider in providers:
            provider['sanitized_name'] = db._sanitize_provider_name(provider['provider'])
        return providers
    except Exception as e:
        logger.error(f"Error getting providers for country {country_code}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/download/{provider_id}")
async def download_gtfs(provider_id: str):
    """Download GTFS data for a specific provider"""
    try:
        # Create downloads directory if it doesn't exist
        DOWNLOAD_DIR.mkdir(exist_ok=True)
        
        # Download the GTFS data
        db = MobilityAPI()
        result = db.download_latest_dataset(provider_id, str(DOWNLOAD_DIR))
        
        if result:
            return {"status": "success", "message": f"Downloaded GTFS data for {provider_id}"}
        else:
            raise HTTPException(status_code=500, detail="Download failed")
            
    except Exception as e:
        logger.error(f"Error downloading GTFS data for provider {provider_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/providers", response_model=List[str])
async def get_providers():
    """Get list of available GTFS providers"""
    providers = find_gtfs_directories()
    # Convert to the old format - just return the provider IDs
    return [p['id'] for p in providers]

@app.on_event("startup")
async def startup_event():
    """Load available GTFS providers on startup"""
    global available_providers
    available_providers = find_gtfs_directories()

@app.post("/provider/{provider_name}")
async def set_provider(provider_name: str):
    """Set the current GTFS provider and load its data"""
    global feed, current_provider
    
    # Get the current list of available providers
    providers = find_gtfs_directories()
    providers_dict = {p['id']: p for p in providers}  # Create a lookup dictionary
    
    # Check if the provider exists in the current list
    if provider_name not in providers_dict:
        # Check if this might be a race condition with duplicate providers
        base_name = provider_name.rsplit('_', 1)[0] if '_' in provider_name else provider_name
        matching_providers = [p for p in providers_dict.keys() if p.startswith(base_name + '_') or p == base_name]
        
        if len(matching_providers) > 1:
            # There are now multiple providers with this base name
            raise HTTPException(
                status_code=409,  # Conflict
                detail="Provider list has been updated with multiple providers sharing the same name. Please reload the provider list."
            )
        raise HTTPException(status_code=404, detail=f"Provider {provider_name} not found")
    
    # If the requested provider is already loaded, return early
    if feed is not None and current_provider == provider_name:
        logger.info(f"Provider {provider_name} already loaded, skipping reload")
        return {"status": "success", "message": f"Provider {provider_name} already loaded"}
    
    try:
        logger.info(f"Loading GTFS data for provider {provider_name}")
        
        # Get the selected provider's info
        provider_info = providers_dict[provider_name]
        
        # Find the provider's dataset directory
        metadata_file = DOWNLOAD_DIR / 'datasets_metadata.json'
        if not metadata_file.exists():
            raise HTTPException(status_code=404, detail=f"No metadata found for provider {provider_name}")
            
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
            
            # Find the dataset info that matches both the provider ID and the dataset ID
            dataset_info = None
            for info in metadata.values():
                if (info.get('provider_id') == provider_info['raw_id'] and 
                    info.get('dataset_id') == provider_info['latest_dataset']['id']):
                    dataset_info = info
                    break
            
            if not dataset_info:
                raise HTTPException(status_code=404, detail=f"No dataset info found for provider {provider_name}")
            
            dataset_dir = Path(dataset_info['download_path'])
        
        # Check if the dataset directory exists and contains GTFS files
        required_files = ['stops.txt', 'routes.txt', 'trips.txt', 'stop_times.txt']
        calendar_files = ['calendar.txt', 'calendar_dates.txt']
        
        if not dataset_dir.exists() or not (
            all((dataset_dir / file).exists() for file in required_files) and 
            any((dataset_dir / file).exists() for file in calendar_files)
        ):
            raise HTTPException(status_code=404, detail=f"GTFS data not found for provider {provider_name}")
        
        feed = load_feed(str(dataset_dir))
        current_provider = provider_name
        return {"status": "success", "message": f"Loaded GTFS data for {provider_name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading provider {provider_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stations/search", response_model=List[StationResponse])
async def search_stations(
    query: str = Query(..., min_length=2),
    language: Optional[str] = Query('default', description="Language code (e.g., 'fr', 'nl') or 'default'")
):
    """Search for stations by name"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    logger.info(f"Searching for stations with query: {query}, language: {language}")
    
    # Case-insensitive search in both default names and translations
    matches = []
    for stop_id, stop in feed.stops.items():
        # Search in default name and translations
        searchable_names = [stop.name.lower()]
        if stop.translations:
            searchable_names.extend(trans.lower() for trans in stop.translations.values())
        
        if any(query.lower() in name for name in searchable_names):
            # Get the appropriate name based on language
            display_name = stop.name  # Default name
            if language != 'default' and stop.translations and language in stop.translations:
                display_name = stop.translations[language]
            
            matches.append(StationResponse(
                id=stop_id,
                name=display_name,
                location=Location(lat=stop.lat, lon=stop.lon),
                translations=stop.translations
            ))
    
    logger.info(f"Found {len(matches)} matches")
    return matches

@app.get("/routes", response_model=RouteResponse)
async def get_routes(
    from_station: str = Query(..., description="Departure station ID"),
    to_station: str = Query(..., description="Destination station ID"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    language: Optional[str] = Query('default', description="Language code (e.g., 'fr', 'nl') or 'default'")
):
    """Get all routes between two stations for a specific date"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    # Handle multiple station IDs
    from_stations = from_station.split(',')
    to_stations = to_station.split(',')
    
    # Validate all stations exist
    for station_id in from_stations:
        if station_id not in feed.stops:
            raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    for station_id in to_stations:
        if station_id not in feed.stops:
            raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find routes for all combinations
    all_routes = []
    for from_id in from_stations:
        for to_id in to_stations:
            routes = feed.find_routes_between_stations(from_id, to_id)
            all_routes.extend(routes)
    
    # Filter by date if provided
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
            day_name = target_date.strftime("%A").lower()
            all_routes = [r for r in all_routes if day_name in r.service_days]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    
    # Convert to response format
    route_responses = []
    for route in all_routes:
        # Get relevant stops
        # Find first matching from and to stations in this route
        route_stop_ids = [stop.stop.id for stop in route.stops]
        matching_from = next((s for s in from_stations if s in route_stop_ids), None)
        matching_to = next((s for s in to_stations if s in route_stop_ids), None)
        
        if not matching_from or not matching_to:
            continue
        
        stops = route.get_stops_between(matching_from, matching_to)
        duration = route.calculate_duration(matching_from, matching_to)
        
        if not duration:
            continue
        
        # Handle NaN values in route name
        route_name = route.route_name
        if pd.isna(route_name) or not isinstance(route_name, str):
            route_name = f"Route {route.route_id}"
            
        route_responses.append(Route(
            route_id=route.route_id,
            route_name=route_name,
            trip_id=route.trip_id,
            service_days=route.service_days,
            duration_minutes=int(duration.total_seconds() / 60),
            stops=[
                Stop(
                    id=stop.stop.id,
                    name=feed.get_stop_name(stop.stop.id, language) if language != 'default' else stop.stop.name,
                    location=Location(lat=stop.stop.lat, lon=stop.stop.lon),
                    arrival_time=stop.arrival_time,
                    departure_time=stop.departure_time,
                    translations=stop.stop.translations
                )
                for stop in stops
            ],
            shape=Shape(
                shape_id=route.shape.shape_id,
                points=route.shape.points
            ) if route.shape else None,
            line_number=route.short_name if hasattr(route, 'short_name') else "",
            color=route.color if hasattr(route, 'color') else None,
            text_color=route.text_color if hasattr(route, 'text_color') else None,
            headsigns=route.headsigns,
            service_ids=route.service_ids  # Include for debugging
        ))
    
    return RouteResponse(
        routes=route_responses,
        total_routes=len(route_responses)
    )

@app.get("/stations/destinations/{station_id}", response_model=List[StationResponse])
async def get_destinations(
    station_id: str,
    language: Optional[str] = Query(None, description="Language code (e.g., 'fr', 'nl')")
):
    """Get all possible destination stations from a given station"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    if station_id not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find all routes that start from this station
    destinations = set()
    for route in feed.routes:
        # Get all stops in this route
        stops = route.get_stops_between(station_id, None)
        
        # If this station is in the route
        if stops and stops[0].stop.id == station_id:
            # Add all subsequent stops as potential destinations
            for stop in stops[1:]:
                destinations.add(stop.stop.id)
    
    # Convert to response format
    return [
        StationResponse(
            id=stop_id,
            name=feed.get_stop_name(stop_id, language) if language else feed.stops[stop_id].name,
            location=Location(
                lat=feed.stops[stop_id].lat,
                lon=feed.stops[stop_id].lon
            ),
            translations=feed.stops[stop_id].translations
        )
        for stop_id in destinations
        if stop_id in feed.stops
    ]

@app.get("/stations/origins/{station_id}", response_model=List[StationResponse])
async def get_origins(
    station_id: str,
    language: Optional[str] = Query(None, description="Language code (e.g., 'fr', 'nl')")
):
    """Get all possible origin stations that can reach a given station"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    if station_id not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find all routes that end at this station
    origins = set()
    for route in feed.routes:
        # Get all stops in this route
        stops = route.get_stops_between(None, station_id)
        
        # If this station is in the route
        if stops and stops[-1].stop.id == station_id:
            # Add all previous stops as potential origins
            for stop in stops[:-1]:
                origins.add(stop.stop.id)
    
    # Convert to response format
    return [
        StationResponse(
            id=stop_id,
            name=feed.get_stop_name(stop_id, language) if language else feed.stops[stop_id].name,
            location=Location(
                lat=feed.stops[stop_id].lat,
                lon=feed.stops[stop_id].lon
            ),
            translations=feed.stops[stop_id].translations
        )
        for stop_id in origins
        if stop_id in feed.stops
    ]

@app.get("/stations/{station_id}/routes", response_model=List[RouteInfo])
async def get_station_routes(
    station_id: str,
    language: Optional[str] = Query('default', description="Language code (e.g., 'fr', 'nl') or 'default'")
):
    """Get all routes that serve this station with detailed information"""
    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")
    
    if station_id not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    
    # Find all routes that serve this station
    routes_info = []
    seen_route_ids = set()
    
    for route in feed.routes:
        # Skip if we've already seen this route
        if route.route_id in seen_route_ids:
            continue
            
        # Check if this station is served by this route
        station_in_route = False
        for stop in route.stops:
            if stop.stop.id == station_id:
                station_in_route = True
                break
        
        if station_in_route:
            seen_route_ids.add(route.route_id)
            
            # Get stop names in the correct language
            stop_names = [
                feed.get_stop_name(stop.stop.id, language) if language != 'default' else stop.stop.name
                for stop in route.stops
            ]
            
            # Get parent station ID if available
            parent_station_id = None
            if hasattr(feed.stops[station_id], 'parent_station'):
                parent_station_id = feed.stops[station_id].parent_station
            
            # Handle NaN values in route name
            route_name = route.route_name
            if pd.isna(route_name):
                route_name = f"Route {route.route_id}"
            
            routes_info.append(RouteInfo(
                route_id=route.route_id,
                route_name=route_name,
                short_name=route.short_name if hasattr(route, 'short_name') else None,
                color=route.color if hasattr(route, 'color') else None,
                text_color=route.text_color if hasattr(route, 'text_color') else None,
                first_stop=stop_names[0],
                last_stop=stop_names[-1],
                stops=stop_names,
                headsign=route.stops[-1].stop.name,  # Use last stop name as headsign
                service_days=route.service_days,
                parent_station_id=parent_station_id
            ))
    
    return routes_info 



@app.get("/providers_info", response_model=List[Dict])
async def get_providers_info():
    """Get list of available GTFS providers with full metadata"""
    return find_gtfs_directories()