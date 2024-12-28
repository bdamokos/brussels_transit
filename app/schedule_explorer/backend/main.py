from fastapi import FastAPI, HTTPException, Query, Request, Path
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta
import os
from pathlib import Path as FilePath
import pandas as pd
import logging
import sys
import logging.config
import json
from mobility_db_api import MobilityAPI
import time
from zoneinfo import ZoneInfo

from .models import (
    RouteResponse,
    StationResponse,
    Route,
    Stop,
    Location,
    Shape,
    RouteInfo,
    WaitingTimeInfo,
    StopData,
    RouteArrivals,
    RouteMetadata,
    ArrivalInfo,
    Provider,
    DatasetInfo,
    DatasetValidation,
    RouteColors,
    LineInfo,
)
from .gtfs_loader import FlixbusFeed, load_feed

# Configure download directory - hardcoded to project root/downloads
DOWNLOAD_DIR = FilePath(__file__).parent.parent.parent.parent / "downloads"


# Configure logging
def setup_logging():
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
        },
        "handlers": {
            "default": {
                "level": "DEBUG",
                "formatter": "standard",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "level": "DEBUG",
                "formatter": "standard",
                "class": "logging.FileHandler",
                "filename": str(
                    FilePath(__file__).parent.parent / "logs" / "schedule_explorer.log"
                ),
                "mode": "a",
            },
        },
        "loggers": {
            "": {"handlers": ["default", "file"], "level": "DEBUG", "propagate": True}
        },
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
available_providers: List[Provider] = []
logger = setup_logging()
db: Optional[MobilityAPI] = None


async def check_provider_availability(
    provider_id: str,
) -> Tuple[bool, bool, Optional[Provider]]:
    """Check if provider is available locally or can be downloaded.

    Returns:
        Tuple[bool, bool, Optional[Provider]]:
            - is_available_locally: True if provider data exists locally
            - can_be_downloaded: True if provider exists in MobilityDB
            - provider: Provider object if found locally, None otherwise
    """
    # First check if provider exists locally
    provider = get_provider_by_id(provider_id)
    if provider:
        return True, True, provider

    # If not found locally, check if it exists in MobilityDB using get_provider_info
    try:
        provider_info = db.get_provider_info(provider_id)
        if provider_info:
            return False, True, None
    except Exception as e:
        logger.error(f"Error checking provider availability in MobilityDB: {str(e)}")

    return False, False, None


async def ensure_provider_loaded(
    provider_id: str,
) -> Tuple[bool, str, Optional[Provider]]:
    """Ensure provider is loaded, loading it if available.

    Returns:
        Tuple[bool, str, Optional[Provider]]:
            - is_ready: True if provider is loaded and ready
            - message: Status message explaining the current state
            - provider: Provider object if found, None otherwise
    """
    global feed, current_provider

    # Check provider availability
    is_local, can_download, provider = await check_provider_availability(provider_id)

    if not is_local and not can_download:
        return (
            False,
            f"Provider {provider_id} is not available. Please check the provider ID or use GET /api/providers/be to list available providers.",
            None,
        )

    if not is_local and can_download:
        return (
            False,
            f"Provider {provider_id} needs to be downloaded first. Use POST /api/download/{provider_id} to download it.",
            None,
        )

    # At this point, provider exists locally
    if feed is not None and current_provider == provider.id:
        return True, "Provider already loaded", provider

    # Try to load the provider
    try:
        # Find the provider's dataset directory from metadata
        metadata_file = DOWNLOAD_DIR / "datasets_metadata.json"
        if not metadata_file.exists():
            return False, f"No metadata found for provider {provider_id}", None

        with open(metadata_file, "r") as f:
            metadata = json.load(f)
            dataset_info = None
            for info in metadata.values():
                if (
                    info.get("provider_id") == provider.raw_id
                    and info.get("dataset_id") == provider.latest_dataset.id
                ):
                    dataset_info = info
                    break

            if not dataset_info:
                return False, f"No dataset info found for provider {provider_id}", None

            dataset_dir = FilePath(dataset_info["download_path"])

        # Check if the dataset directory exists and contains GTFS files
        required_files = ["stops.txt", "routes.txt", "trips.txt", "stop_times.txt"]
        calendar_files = ["calendar.txt", "calendar_dates.txt"]

        if not dataset_dir.exists() or not (
            all((dataset_dir / file).exists() for file in required_files)
            and any((dataset_dir / file).exists() for file in calendar_files)
        ):
            return False, f"GTFS data not found for provider {provider_id}", None

        feed = load_feed(str(dataset_dir))
        current_provider = provider.id
        return True, f"Loaded GTFS data for {provider_id}", provider
    except Exception as e:
        logger.error(f"Error loading provider {provider_id}: {str(e)}")
        return False, f"Error loading provider {provider_id}: {str(e)}", None


def find_gtfs_directories() -> List[Provider]:
    """Find all GTFS data directories in the downloads directory and their metadata."""
    providers = {}
    latest_datasets = {}  # Keep track of the latest dataset for each provider_id

    # Collect metadata from downloads
    if DOWNLOAD_DIR.exists():
        metadata_file = DOWNLOAD_DIR / "datasets_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, "r") as f:
                    metadata = json.load(f)

                    # First pass: find the latest dataset for each provider
                    for dataset_id, dataset_info in metadata.items():
                        provider_id = dataset_info.get("provider_id")
                        if provider_id:
                            dataset_dir = FilePath(dataset_info.get("download_path"))
                            if dataset_dir.exists():
                                # If we haven't seen this provider yet, or if this dataset is newer
                                if (
                                    provider_id not in latest_datasets
                                    or dataset_info["dataset_id"]
                                    > latest_datasets[provider_id]["dataset_id"]
                                ):
                                    latest_datasets[provider_id] = dataset_info

                    # Second pass: create provider entries for the latest datasets
                    for provider_id, dataset_info in latest_datasets.items():
                        dataset_dir = FilePath(dataset_info.get("download_path"))
                        sanitized_name = (
                            dataset_dir.parent.name.split("_", 1)[1]
                            if "_" in dataset_dir.parent.name
                            else dataset_dir.parent.name
                        )

                        # Always append the provider_id to make each provider unique
                        provider_key = f"{sanitized_name}_{provider_id}"

                        # Convert to the format expected by the frontend
                        providers[provider_key] = Provider(
                            id=provider_key,  # Use sanitized name with provider_id as ID
                            raw_id=provider_id,  # Keep the raw ID for API calls
                            provider=dataset_info.get("provider_name"),
                            name=dataset_info.get("provider_name"),
                            latest_dataset=DatasetInfo(
                                id=dataset_info.get("dataset_id"),
                                downloaded_at=dataset_info.get("download_date"),
                                hash=dataset_info.get("file_hash"),
                                hosted_url=dataset_info.get("source_url"),
                                validation_report=DatasetValidation(
                                    total_error=0,
                                    total_warning=0,
                                    total_info=0,
                                ),
                            ),
                        )
            except Exception as e:
                logger.error(f"Error reading metadata file {metadata_file}: {str(e)}")

    return list(providers.values())


def get_provider_by_id(provider_id: str) -> Optional[Provider]:
    """Get provider by either its long ID or raw ID."""
    global available_providers

    # Refresh available providers if empty
    if not available_providers:
        available_providers = find_gtfs_directories()

    # First try to find by long ID
    provider = next((p for p in available_providers if p.id == provider_id), None)
    if provider:
        return provider

    # If not found, try to find by raw ID
    return next((p for p in available_providers if p.raw_id == provider_id), None)


@app.get("/api/providers/{country_code}", response_model=List[Dict])
async def get_providers_by_country(country_code: str):
    """Get list of available GTFS providers for a specific country"""
    try:
        providers = db.get_providers_by_country(country_code)
        logger.debug(f"Got {len(providers)} providers from MobilityAPI")
        # Add sanitized names and map fields from the MobilityAPI response
        for provider in providers:
            # logger.debug(f"Processing provider: {provider.get('provider', '')}")
            # logger.debug(f"Latest dataset: {provider.get('latest_dataset', {})}")

            provider["sanitized_name"] = db._sanitize_provider_name(
                provider.get("provider", "")
            )
            # Map bounding box from latest_dataset
            latest_dataset = provider.get("latest_dataset")
            if latest_dataset is not None and latest_dataset.get("bounding_box"):
                bbox = latest_dataset.get("bounding_box", {})
                provider["bounding_box"] = {
                    "min_lat": bbox.get("minimum_latitude", 0),
                    "max_lat": bbox.get("maximum_latitude", 0),
                    "min_lon": bbox.get("minimum_longitude", 0),
                    "max_lon": bbox.get("maximum_longitude", 0),
                }
            else:
                # logger.debug("No bounding box found in latest_dataset")
                provider["bounding_box"] = {
                    "min_lat": 0,
                    "max_lat": 0,
                    "min_lon": 0,
                    "max_lon": 0,
                }

            # Map downloaded_at from latest_dataset
            provider["downloaded_at"] = (
                None
                if latest_dataset is None
                else latest_dataset.get("downloaded_at", None)
            )

            # Map hash from latest_dataset
            provider["hash"] = (
                None if latest_dataset is None else latest_dataset.get("hash", None)
            )

            # Map validation_report from latest_dataset
            validation = (
                {}
                if latest_dataset is None
                else latest_dataset.get("validation_report", {})
            )
            provider["validation_report"] = {
                "total_error": validation.get("total_error", 0),
                "total_warning": validation.get("total_warning", 0),
                "total_info": validation.get("total_info", 0),
            }
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
        result = db.download_latest_dataset(provider_id, str(DOWNLOAD_DIR))

        if result:
            return {
                "status": "success",
                "message": f"Downloaded GTFS data for {provider_id}",
            }
        else:
            raise HTTPException(status_code=500, detail="Download failed")

    except Exception as e:
        logger.error(
            f"Error downloading GTFS data for provider {provider_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/providers", response_model=List[str])
async def get_providers():
    """Get list of available GTFS providers"""
    providers = find_gtfs_directories()
    # Convert to the old format - just return the provider IDs
    return [p.id for p in providers]


@app.on_event("startup")
async def startup_event():
    """Load available GTFS providers on startup"""
    global available_providers, db
    available_providers = find_gtfs_directories()
    db = MobilityAPI()


@app.post("/provider/{provider_id}")
async def set_provider(provider_id: str):
    """Set the current GTFS provider and load its data"""
    global feed, current_provider, available_providers

    # Get provider info
    provider = get_provider_by_id(provider_id)
    if not provider:
        raise HTTPException(
            status_code=404,
            detail=f"Provider {provider_id} not found",
        )

    # If the requested provider is already loaded, return early
    if feed is not None and current_provider == provider.id:
        logger.info(f"Provider {provider.id} already loaded, skipping reload")
        return {
            "status": "success",
            "message": f"Provider {provider.id} already loaded",
        }

    try:
        logger.info(f"Loading GTFS data for provider {provider.id}")

        # Find the provider's dataset directory
        metadata_file = DOWNLOAD_DIR / "datasets_metadata.json"
        if not metadata_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"No metadata found for provider {provider.id}",
            )

        with open(metadata_file, "r") as f:
            metadata = json.load(f)

            # Find the dataset info that matches both the provider ID and the dataset ID
            dataset_info = None
            for info in metadata.values():
                if (
                    info.get("provider_id") == provider.raw_id
                    and info.get("dataset_id") == provider.latest_dataset.id
                ):
                    dataset_info = info
                    break

            if not dataset_info:
                raise HTTPException(
                    status_code=404,
                    detail=f"No dataset info found for provider {provider.id}",
                )

            dataset_dir = FilePath(dataset_info["download_path"])

        # Check if the dataset directory exists and contains GTFS files
        required_files = ["stops.txt", "routes.txt", "trips.txt", "stop_times.txt"]
        calendar_files = ["calendar.txt", "calendar_dates.txt"]

        if not dataset_dir.exists() or not (
            all((dataset_dir / file).exists() for file in required_files)
            and any((dataset_dir / file).exists() for file in calendar_files)
        ):
            raise HTTPException(
                status_code=404,
                detail=f"GTFS data not found for provider {provider.id}",
            )

        feed = load_feed(str(dataset_dir))
        current_provider = provider.id
        return {"status": "success", "message": f"Loaded GTFS data for {provider.id}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading provider {provider.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/{provider_id}/stations/search", response_model=List[StationResponse])
async def search_stations_with_provider(
    provider_id: str = Path(...),
    query: str = Query(..., min_length=2),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
):
    """Search for stations by name with explicit provider"""
    return await search_stations(
        query=query, language=language, provider_id=provider_id
    )


@app.get("/stations/search", response_model=List[StationResponse])
async def search_stations(
    query: Optional[str] = Query(
        None, min_length=2, description="Search query for station name"
    ),
    stop_id: Optional[str] = Query(None, description="Stop ID to search for"),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Search for stations by name or stop_id"""
    if provider_id:
        # Check provider availability and load if needed
        is_ready, message, provider = await ensure_provider_loaded(provider_id)
        if not is_ready:
            raise HTTPException(
                status_code=409 if "being loaded" in message else 404,
                detail=message,
            )

    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")

    if not query and not stop_id:
        raise HTTPException(
            status_code=400,
            detail="Either 'query' or 'stop_id' parameter must be provided",
        )

    logger.info(
        f"Searching for stations with query: {query}, stop_id: {stop_id}, language: {language}"
    )

    # Initialize matches list
    matches = []

    # Search by stop_id if provided
    if stop_id:
        if stop_id in feed.stops:
            stop = feed.stops[stop_id]
            # Get the appropriate name based on language
            display_name = stop.name  # Default name
            if (
                language != "default"
                and stop.translations
                and language in stop.translations
            ):
                display_name = stop.translations[language]

            matches.append(
                StationResponse(
                    id=stop_id,
                    name=display_name,
                    location=Location(lat=stop.lat, lon=stop.lon),
                    translations=stop.translations,
                )
            )

    # Search by name if query is provided
    if query:
        # Case-insensitive search in both default names and translations
        for stop_id, stop in feed.stops.items():
            # Search in default name and translations
            searchable_names = [stop.name.lower()]
            if stop.translations:
                searchable_names.extend(
                    trans.lower() for trans in stop.translations.values()
                )

            if any(query.lower() in name for name in searchable_names):
                # Get the appropriate name based on language
                display_name = stop.name  # Default name
                if (
                    language != "default"
                    and stop.translations
                    and language in stop.translations
                ):
                    display_name = stop.translations[language]

                # Only add if not already added by stop_id search
                if not any(m.id == stop_id for m in matches):
                    matches.append(
                        StationResponse(
                            id=stop_id,
                            name=display_name,
                            location=Location(lat=stop.lat, lon=stop.lon),
                            translations=stop.translations,
                        )
                    )

    logger.info(f"Found {len(matches)} matches")
    return matches


@app.get("/api/{provider_id}/routes", response_model=RouteResponse)
async def get_routes_with_provider(
    provider_id: str = Path(...),
    from_station: str = Query(..., description="Departure station ID"),
    to_station: str = Query(..., description="Destination station ID"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
):
    """Get all routes between two stations for a specific date with explicit provider"""
    return await get_routes(
        from_station=from_station,
        to_station=to_station,
        date=date,
        language=language,
        provider_id=provider_id,
    )


@app.get("/routes", response_model=RouteResponse)
async def get_routes(
    from_station: str = Query(..., description="Departure station ID"),
    to_station: str = Query(..., description="Destination station ID"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Get all routes between two stations for a specific date"""
    if provider_id:
        # Check provider availability and load if needed
        is_ready, message, provider = await ensure_provider_loaded(provider_id)
        if not is_ready:
            raise HTTPException(
                status_code=409 if "being loaded" in message else 404,
                detail=message,
            )

    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")

    # Handle multiple station IDs
    from_stations = from_station.split(",")
    to_stations = to_station.split(",")

    # Validate all stations exist
    for station_id in from_stations:
        if station_id not in feed.stops:
            raise HTTPException(
                status_code=404, detail=f"Station {station_id} not found"
            )
    for station_id in to_stations:
        if station_id not in feed.stops:
            raise HTTPException(
                status_code=404, detail=f"Station {station_id} not found"
            )

    # Find routes for all combinations
    all_routes = []
    for from_id in from_stations:
        for to_id in to_stations:
            routes = feed.find_trips_between_stations(from_id, to_id)
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

        # Handle NaN values in color and text_color
        color = None
        if hasattr(route, "color") and not pd.isna(route.color):
            color = route.color

        text_color = None
        if hasattr(route, "text_color") and not pd.isna(route.text_color):
            text_color = route.text_color

        route_responses.append(
            Route(
                route_id=route.route_id,
                route_name=route_name,
                trip_id=route.trip_id,
                service_days=route.service_days,
                duration_minutes=int(duration.total_seconds() / 60),
                stops=[
                    Stop(
                        id=stop.stop.id,
                        name=(
                            feed.get_stop_name(stop.stop.id, language)
                            if language != "default"
                            else stop.stop.name
                        ),
                        location=Location(lat=stop.stop.lat, lon=stop.stop.lon),
                        arrival_time=stop.arrival_time,
                        departure_time=stop.departure_time,
                        translations=stop.stop.translations,
                    )
                    for stop in stops
                ],
                shape=(
                    Shape(shape_id=route.shape.shape_id, points=route.shape.points)
                    if route.shape
                    else None
                ),
                line_number=route.short_name if hasattr(route, "short_name") else "",
                color=color,
                text_color=text_color,
                headsigns=route.headsigns,
                service_ids=route.service_ids,  # Include for debugging
            )
        )

    return RouteResponse(routes=route_responses, total_routes=len(route_responses))


@app.get(
    "/api/{provider_id}/stations/{station_id}/routes", response_model=List[RouteInfo]
)
async def get_station_routes_with_provider(
    provider_id: str = Path(...),
    station_id: str = Path(...),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
):
    """Get all routes that serve this station with detailed information with explicit provider"""
    return await get_station_routes(
        station_id=station_id,
        language=language,
        provider_id=provider_id,
    )


@app.get("/stations/{station_id}/routes", response_model=List[RouteInfo])
async def get_station_routes(
    station_id: str = Path(...),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Get all routes that serve this station with detailed information"""
    if provider_id:
        # Check provider availability and load if needed
        is_ready, message, provider = await ensure_provider_loaded(provider_id)
        if not is_ready:
            raise HTTPException(
                status_code=409 if "being loaded" in message else 404,
                detail=message,
            )

    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")

    if station_id not in feed.stops:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")

    # Get the stop and determine if it's a parent station or child stop
    stop = feed.stops[station_id]
    is_parent = getattr(stop, "location_type", 0) == 1
    parent_id = getattr(stop, "parent_station", None)

    # If this is a child stop, get its parent station
    if not is_parent and parent_id:
        parent_station = feed.stops.get(parent_id)
        if parent_station:
            is_parent = True
            station_id = parent_id

    # If this is a parent station, get all its child stops
    stop_ids_to_check = [station_id]
    if is_parent:
        # Find all child stops
        for stop_id, stop in feed.stops.items():
            if getattr(stop, "parent_station", None) == station_id:
                stop_ids_to_check.append(stop_id)

    # Find all routes that serve any of these stops
    routes_info = []
    seen_route_ids = set()

    for route in feed.routes:
        # Skip if we've already seen this route
        if route.route_id in seen_route_ids:
            continue

        # Check if any of our stops is served by this route
        station_in_route = False
        for stop in route.stops:
            if stop.stop.id in stop_ids_to_check:
                station_in_route = True
                break

        if station_in_route:
            seen_route_ids.add(route.route_id)

            # Get stop names in the correct language
            stop_names = [
                (
                    feed.get_stop_name(stop.stop.id, language)
                    if language != "default"
                    else stop.stop.name
                )
                for stop in route.stops
            ]

            # Handle NaN values in route name and colors
            route_name = route.route_name
            if pd.isna(route_name):
                route_name = f"Route {route.route_id}"

            color = (
                route.color
                if hasattr(route, "color") and not pd.isna(route.color)
                else None
            )
            text_color = (
                route.text_color
                if hasattr(route, "text_color") and not pd.isna(route.text_color)
                else None
            )

            routes_info.append(
                RouteInfo(
                    route_id=route.route_id,
                    route_name=route_name,
                    short_name=(
                        route.short_name if hasattr(route, "short_name") else None
                    ),
                    color=color,
                    text_color=text_color,
                    first_stop=stop_names[0],
                    last_stop=stop_names[-1],
                    stops=stop_names,
                    headsign=route.stops[-1].stop.name,
                    service_days=route.service_days,
                    parent_station_id=parent_id,
                    terminus_stop_id=route.stops[-1].stop.id,
                    service_days_explicit=(
                        route.service_days_explicit
                        if hasattr(route, "service_days_explicit")
                        else None
                    ),
                    calendar_dates_additions=(
                        route.calendar_dates_additions
                        if hasattr(route, "calendar_dates_additions")
                        else None
                    ),
                    calendar_dates_removals=(
                        route.calendar_dates_removals
                        if hasattr(route, "calendar_dates_removals")
                        else None
                    ),
                    valid_calendar_days=(
                        route.valid_calendar_days
                        if hasattr(route, "valid_calendar_days")
                        else None
                    ),
                    service_calendar=(
                        route.service_calendar
                        if hasattr(route, "service_calendar")
                        else None
                    ),
                )
            )

    return routes_info


@app.get(
    "/api/{provider_id}/stations/destinations/{station_id}",
    response_model=List[StationResponse],
)
async def get_destinations_with_provider(
    provider_id: str = Path(...),
    station_id: str = Path(...),
    language: Optional[str] = Query(
        None, description="Language code (e.g., 'fr', 'nl')"
    ),
):
    """Get all possible destination stations from a given station with explicit provider"""
    return await get_destinations(
        station_id=station_id,
        language=language,
        provider_id=provider_id,
    )


@app.get("/stations/destinations/{station_id}", response_model=List[StationResponse])
async def get_destinations(
    station_id: str = Path(...),
    language: Optional[str] = Query(
        None, description="Language code (e.g., 'fr', 'nl')"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Get all possible destination stations from a given station"""
    if provider_id:
        # Check provider availability and load if needed
        is_ready, message, provider = await ensure_provider_loaded(provider_id)
        if not is_ready:
            raise HTTPException(
                status_code=409 if "being loaded" in message else 404,
                detail=message,
            )

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
            name=(
                feed.get_stop_name(stop_id, language)
                if language
                else feed.stops[stop_id].name
            ),
            location=Location(lat=feed.stops[stop_id].lat, lon=feed.stops[stop_id].lon),
            translations=feed.stops[stop_id].translations,
        )
        for stop_id in destinations
        if stop_id in feed.stops
    ]


@app.get(
    "/api/{provider_id}/stations/origins/{station_id}",
    response_model=List[StationResponse],
)
async def get_origins_with_provider(
    provider_id: str = Path(...),
    station_id: str = Path(...),
    language: Optional[str] = Query(
        None, description="Language code (e.g., 'fr', 'nl')"
    ),
):
    """Get all possible origin stations that can reach a given station with explicit provider"""
    return await get_origins(
        station_id=station_id,
        language=language,
        provider_id=provider_id,
    )


@app.get("/stations/origins/{station_id}", response_model=List[StationResponse])
async def get_origins(
    station_id: str = Path(...),
    language: Optional[str] = Query(
        None, description="Language code (e.g., 'fr', 'nl')"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Get all possible origin stations that can reach a given station"""
    if provider_id:
        # Check provider availability and load if needed
        is_ready, message, provider = await ensure_provider_loaded(provider_id)
        if not is_ready:
            raise HTTPException(
                status_code=409 if "being loaded" in message else 404,
                detail=message,
            )

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
            name=(
                feed.get_stop_name(stop_id, language)
                if language
                else feed.stops[stop_id].name
            ),
            location=Location(lat=feed.stops[stop_id].lat, lon=feed.stops[stop_id].lon),
            translations=feed.stops[stop_id].translations,
        )
        for stop_id in origins
        if stop_id in feed.stops
    ]


@app.get("/providers_info", response_model=List[Provider])
async def get_providers_info():
    """Get list of available GTFS providers with full metadata"""
    return find_gtfs_directories()


@app.get(
    "/api/{provider_id}/stops/{stop_id}/waiting_times", response_model=WaitingTimeInfo
)
async def get_waiting_times(
    provider_id: str = Path(..., description="Provider ID"),
    stop_id: str = Path(..., description="Stop ID"),
    route_id: Optional[str] = Query(
        None, description="Optional route ID to filter results"
    ),
    limit: Optional[int] = Query(2, description="Number of next arrivals to return"),
    time_local: Optional[str] = Query(
        None, description="Time in HH:MM:SS format, assumed to be in local timezone"
    ),
    time_utc: Optional[str] = Query(
        None, description="Time in HH:MM:SS format, assumed to be in UTC timezone"
    ),
):
    """Get the next scheduled arrivals at a stop."""
    start_time = time.time()

    # Check provider availability and load if needed
    is_ready, message, provider = await ensure_provider_loaded(provider_id)
    if not is_ready:
        raise HTTPException(
            status_code=409 if "being loaded" in message else 404,
            detail=message,
        )

    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")

    # Get the stop
    gtfs_stop = feed.stops.get(stop_id)
    if not gtfs_stop:
        raise HTTPException(status_code=404, detail=f"Stop {stop_id} not found")

    # Determine if this is a parent station or child stop
    is_parent = getattr(gtfs_stop, "location_type", 0) == 1
    parent_id = getattr(gtfs_stop, "parent_station", None)

    # If this is a child stop, get its parent station
    if not is_parent and parent_id:
        parent_station = feed.stops.get(parent_id)
        if parent_station:
            is_parent = True
            parent_id = parent_station.id

    # If this is a parent station, get all its child stops
    stop_ids_to_check = [stop_id]
    if is_parent:
        # Find all child stops
        for child_id, stop in feed.stops.items():
            if getattr(stop, "parent_station", None) == stop_id:
                stop_ids_to_check.append(child_id)

    # Parse date or use current time (converted from UTC to local)
    try:
        if time_local:
            # If time is provided, assume it's in local timezone
            target_time = datetime.strptime(time_local, "%H:%M:%S").time()
        elif time_utc:
            # If UTC time is provided, convert it to local
            utc_time = datetime.strptime(time_utc, "%H:%M:%S")
            target_time = utc_time.astimezone(ZoneInfo("Europe/Brussels")).time()
        else:
            # If no time provided, use current local time
            target_time = datetime.now(ZoneInfo("Europe/Brussels")).time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM:SS")

    # Get current time in local timezone
    current_time = datetime.now(ZoneInfo("Europe/Brussels")).strftime("%H:%M:%S")

    # Initialize response structure with proper models
    next_arrivals: Dict[str, Dict[str, List[ArrivalInfo]]] = {}

    # For each stop ID, get its routes and waiting times
    for current_stop_id in stop_ids_to_check:
        # Get all routes serving this stop
        routes_info = await get_station_routes(current_stop_id, provider_id=provider_id)
        logger.info(f"Found {len(routes_info)} routes serving stop {current_stop_id}")

        # For each route, get the trips to its terminus
        for route_info in routes_info:
            # Skip if route_id is specified and doesn't match
            if route_id and route_id != route_info.route_id:
                continue

            # Get all trips between our stop and the terminus
            routes_response = await get_routes(
                from_station=current_stop_id,
                to_station=route_info.terminus_stop_id,
                date=None,
                language="default",
                provider_id=provider_id,
            )

            # Initialize route in next_arrivals if needed
            if route_info.route_id not in next_arrivals:
                next_arrivals[route_info.route_id] = {
                    "_metadata": [
                        RouteMetadata(
                            route_desc=route_info.route_name,
                            route_short_name=route_info.short_name
                            or route_info.route_id,
                        )
                    ],
                }

            # Process each route's trips
            for route in routes_response.routes:
                # Get the first stop's arrival time (this is our stop)
                first_stop = next(
                    (stop for stop in route.stops if stop.id == current_stop_id), None
                )
                if not first_stop:
                    continue

                # Initialize headsign in next_arrivals if needed
                headsign = route_info.last_stop
                if headsign not in next_arrivals[route_info.route_id]:
                    next_arrivals[route_info.route_id][headsign] = []

                next_arrivals[route_info.route_id][headsign].append(
                    ArrivalInfo(
                        is_realtime=False,
                        provider=provider.raw_id,
                        scheduled_time=first_stop.arrival_time,
                        scheduled_minutes=calculate_minutes_until(
                            first_stop.arrival_time, current_time
                        ),
                    )
                )

    # Sort arrivals and limit to requested number
    for route_id, route_data in next_arrivals.items():
        # Skip _metadata field when sorting arrivals
        for headsign, arrivals in route_data.items():
            if headsign == "_metadata":
                continue
            # Deduplicate arrivals based on scheduled time
            unique_arrivals = {}
            for arrival in arrivals:
                unique_arrivals[arrival.scheduled_time] = arrival
            # Convert minutes string to integer for sorting (remove the ' character)
            route_data[headsign] = sorted(
                unique_arrivals.values(),
                key=lambda x: int(x.scheduled_minutes.rstrip("'")),
            )[:limit]

    # Format response using models
    response = WaitingTimeInfo(
        _metadata={"performance": {"total_time": time.time() - start_time}},
        stops_data={
            stop_id: StopData(
                coordinates=Location(lat=gtfs_stop.lat, lon=gtfs_stop.lon),
                lines=next_arrivals,
                name=gtfs_stop.name,
            )
        },
    )

    return response


def parse_time(time_str: str) -> datetime:
    hours, minutes, seconds = map(int, time_str.split(":"))
    base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # Handle times after midnight (e.g. 25:00:00)
    if hours >= 24:
        hours = hours - 24
        base = base + timedelta(days=1)
    return base + timedelta(hours=hours, minutes=minutes, seconds=seconds)


def calculate_minutes_until(arrival_time: str, current_time: str) -> str:
    """Calculate minutes until arrival, handling overnight times."""
    arrival = parse_time(arrival_time)
    current = parse_time(current_time)

    # If arrival seems to be before current time, it might be for tomorrow
    if arrival < current:
        arrival += timedelta(days=1)

    diff = arrival - current
    minutes = int(diff.total_seconds() / 60)
    return f"{minutes}'"


@app.get("/api/{provider_id}/colors/{route_id}", response_model=RouteColors)
async def get_route_colors(
    provider_id: str = Path(...),
    route_id: str = Path(...),
):
    """Get the color scheme for a route."""
    # Check provider availability and load if needed
    is_ready, message, provider = await ensure_provider_loaded(provider_id)
    if not is_ready:
        raise HTTPException(
            status_code=409 if "being loaded" in message else 404,
            detail=message,
        )

    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")

    # Find the route
    route = next((r for r in feed.routes if r.route_id == route_id), None)
    if not route:
        raise HTTPException(status_code=404, detail=f"Route {route_id} not found")

    # Get colors from route, defaulting to black/white if not specified
    background_color = (
        f"#{route.color}" if hasattr(route, "color") and route.color else "#000000"
    )
    text_color = (
        f"#{route.text_color}"
        if hasattr(route, "text_color") and route.text_color
        else "#FFFFFF"
    )

    # Return the color scheme
    return RouteColors(
        background=background_color,
        background_border=background_color,  # Same as background
        text=text_color,
        text_border=text_color,  # Same as text
    )


@app.get("/api/{provider_id}/line_info/{route_id}", response_model=Dict[str, LineInfo])
async def get_line_info(
    provider_id: str = Path(...),
    route_id: str = Path(...),
):
    """Get detailed information about a route/line."""
    # Check provider availability and load if needed
    is_ready, message, provider = await ensure_provider_loaded(provider_id)
    if not is_ready:
        raise HTTPException(
            status_code=409 if "being loaded" in message else 404,
            detail=message,
        )

    if not feed:
        raise HTTPException(status_code=503, detail="GTFS data not loaded")

    # Find the route
    route = next((r for r in feed.routes if r.route_id == route_id), None)
    if not route:
        raise HTTPException(status_code=404, detail=f"Route {route_id} not found")

    # Get route information
    color = f"#{route.color}" if hasattr(route, "color") and route.color else None
    text_color = (
        f"#{route.text_color}"
        if hasattr(route, "text_color") and route.text_color
        else None
    )
    display_name = (
        route.short_name
        if hasattr(route, "short_name") and route.short_name
        else route_id
    )
    long_name = (
        route.route_name if hasattr(route, "route_name") and route.route_name else ""
    )
    route_type = route.route_type if hasattr(route, "route_type") else None

    # Return the line info
    return {
        route_id: LineInfo(
            color=color,
            display_name=display_name,
            long_name=long_name,
            provider=provider.raw_id,
            route_id=route_id,
            route_type=route_type,
            text_color=text_color,
            agency_id=route.agency_id if hasattr(route, "agency_id") else None,
            route_desc=route.route_desc if hasattr(route, "route_desc") else None,
            route_url=route.route_url if hasattr(route, "route_url") else None,
            route_sort_order=(
                route.route_sort_order if hasattr(route, "route_sort_order") else None
            ),
            continuous_pickup=(
                route.continuous_pickup if hasattr(route, "continuous_pickup") else None
            ),
            continuous_drop_off=(
                route.continuous_drop_off
                if hasattr(route, "continuous_drop_off")
                else None
            ),
        )
    }
