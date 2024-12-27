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
import time

from .models import (
    RouteResponse,
    StationResponse,
    Route,
    Stop,
    Location,
    Shape,
    RouteInfo,
)
from .gtfs_loader import FlixbusFeed, load_feed

# Configure download directory - hardcoded to project root/downloads
DOWNLOAD_DIR = Path(__file__).parent.parent.parent.parent / "downloads"


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
                "level": "INFO",
                "formatter": "standard",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {"": {"handlers": ["default"], "level": "INFO", "propagate": True}},
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
db: Optional[MobilityAPI] = None


def find_gtfs_directories() -> List[Dict]:
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
                            dataset_dir = Path(dataset_info.get("download_path"))
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
                        dataset_dir = Path(dataset_info.get("download_path"))
                        sanitized_name = (
                            dataset_dir.parent.name.split("_", 1)[1]
                            if "_" in dataset_dir.parent.name
                            else dataset_dir.parent.name
                        )

                        # Always append the provider_id to make each provider unique
                        provider_key = f"{sanitized_name}_{provider_id}"

                        # Convert to the format expected by the frontend
                        providers[provider_key] = {
                            "id": provider_key,  # Use sanitized name with provider_id as ID
                            "raw_id": provider_id,  # Keep the raw ID for API calls
                            "provider": dataset_info.get("provider_name"),
                            "name": dataset_info.get("provider_name"),
                            "latest_dataset": {
                                "id": dataset_info.get("dataset_id"),
                                "downloaded_at": dataset_info.get("download_date"),
                                "hash": dataset_info.get("file_hash"),
                                "hosted_url": dataset_info.get("source_url"),
                                "validation_report": {
                                    "total_error": 0,  # We don't have this info yet
                                    "total_warning": 0,
                                    "total_info": 0,
                                },
                            },
                        }
            except Exception as e:
                logger.error(f"Error reading metadata file {metadata_file}: {str(e)}")

    return list(providers.values())


@app.get("/api/providers/{country_code}", response_model=List[Dict])
async def get_providers_by_country(country_code: str):
    """Get list of available GTFS providers for a specific country"""
    try:
        providers = db.get_providers_by_country(country_code)
        # Add sanitized names to the providers
        for provider in providers:
            provider["sanitized_name"] = db._sanitize_provider_name(
                provider["provider"]
            )
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
    return [p["id"] for p in providers]


@app.on_event("startup")
async def startup_event():
    """Load available GTFS providers on startup"""
    global available_providers, db
    available_providers = find_gtfs_directories()
    db = MobilityAPI()


@app.post("/provider/{provider_name}")
async def set_provider(provider_name: str):
    """Set the current GTFS provider and load its data"""
    global feed, current_provider

    # Get the current list of available providers
    providers = find_gtfs_directories()
    providers_dict = {p["id"]: p for p in providers}  # Create a lookup dictionary

    # Check if the provider exists in the current list
    if provider_name not in providers_dict:
        # Check if this might be a race condition with duplicate providers
        base_name = (
            provider_name.rsplit("_", 1)[0] if "_" in provider_name else provider_name
        )
        matching_providers = [
            p
            for p in providers_dict.keys()
            if p.startswith(base_name + "_") or p == base_name
        ]

        if len(matching_providers) > 1:
            # There are now multiple providers with this base name
            raise HTTPException(
                status_code=409,  # Conflict
                detail="Provider list has been updated with multiple providers sharing the same name. Please reload the provider list.",
            )
        raise HTTPException(
            status_code=404, detail=f"Provider {provider_name} not found"
        )

    # If the requested provider is already loaded, return early
    if feed is not None and current_provider == provider_name:
        logger.info(f"Provider {provider_name} already loaded, skipping reload")
        return {
            "status": "success",
            "message": f"Provider {provider_name} already loaded",
        }

    try:
        logger.info(f"Loading GTFS data for provider {provider_name}")

        # Get the selected provider's info
        provider_info = providers_dict[provider_name]

        # Find the provider's dataset directory
        metadata_file = DOWNLOAD_DIR / "datasets_metadata.json"
        if not metadata_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"No metadata found for provider {provider_name}",
            )

        with open(metadata_file, "r") as f:
            metadata = json.load(f)

            # Find the dataset info that matches both the provider ID and the dataset ID
            dataset_info = None
            for info in metadata.values():
                if (
                    info.get("provider_id") == provider_info["raw_id"]
                    and info.get("dataset_id") == provider_info["latest_dataset"]["id"]
                ):
                    dataset_info = info
                    break

            if not dataset_info:
                raise HTTPException(
                    status_code=404,
                    detail=f"No dataset info found for provider {provider_name}",
                )

            dataset_dir = Path(dataset_info["download_path"])

        # Check if the dataset directory exists and contains GTFS files
        required_files = ["stops.txt", "routes.txt", "trips.txt", "stop_times.txt"]
        calendar_files = ["calendar.txt", "calendar_dates.txt"]

        if not dataset_dir.exists() or not (
            all((dataset_dir / file).exists() for file in required_files)
            and any((dataset_dir / file).exists() for file in calendar_files)
        ):
            raise HTTPException(
                status_code=404,
                detail=f"GTFS data not found for provider {provider_name}",
            )

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
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
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


@app.get("/routes", response_model=RouteResponse)
async def get_routes(
    from_station: str = Query(..., description="Departure station ID"),
    to_station: str = Query(..., description="Destination station ID"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
):
    """Get all routes between two stations for a specific date"""
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
                color=route.color if hasattr(route, "color") else None,
                text_color=route.text_color if hasattr(route, "text_color") else None,
                headsigns=route.headsigns,
                service_ids=route.service_ids,  # Include for debugging
            )
        )

    return RouteResponse(routes=route_responses, total_routes=len(route_responses))


@app.get("/stations/destinations/{station_id}", response_model=List[StationResponse])
async def get_destinations(
    station_id: str,
    language: Optional[str] = Query(
        None, description="Language code (e.g., 'fr', 'nl')"
    ),
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


@app.get("/stations/origins/{station_id}", response_model=List[StationResponse])
async def get_origins(
    station_id: str,
    language: Optional[str] = Query(
        None, description="Language code (e.g., 'fr', 'nl')"
    ),
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


@app.get("/stations/{station_id}/routes", response_model=List[RouteInfo])
async def get_station_routes(
    station_id: str,
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
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
                (
                    feed.get_stop_name(stop.stop.id, language)
                    if language != "default"
                    else stop.stop.name
                )
                for stop in route.stops
            ]

            # Get parent station ID if available
            parent_station_id = None
            if hasattr(feed.stops[station_id], "parent_station"):
                parent_station_id = feed.stops[station_id].parent_station

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
                    headsign=route.stops[
                        -1
                    ].stop.name,  # Use last stop name as headsign - this is a bug
                    service_days=route.service_days,
                    parent_station_id=parent_station_id,
                    terminus_stop_id=route.stops[-1].stop.id,
                )
            )

    return routes_info


@app.get("/providers_info", response_model=List[Dict])
async def get_providers_info():
    """Get list of available GTFS providers with full metadata"""
    return find_gtfs_directories()


@app.get("/api/{provider_id}/waiting_times")
@app.get("/api/{provider_id}/waiting_times/{route_id}")
async def get_waiting_times(
    provider_id: str,
    route_id: Optional[str] = None,
    stop_id: Optional[str] = Query(None, description="Stop ID to get arrivals for"),
    limit: Optional[int] = Query(2, description="Number of next arrivals to return"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
):
    """Get the next scheduled arrivals at a stop."""
    start_time = time.time()

    # Check if feed is loaded
    if not feed:
        raise HTTPException(
            status_code=503,
            detail="GTFS data not loaded. Please load a provider first using POST /provider/{provider_id}",
        )

    # Check if the correct provider is loaded
    if current_provider != provider_id:
        raise HTTPException(
            status_code=409,
            detail=f"Provider {provider_id} not loaded. Current provider is {current_provider}. Please load the correct provider first.",
        )

    if not stop_id:
        raise HTTPException(status_code=400, detail="stop_id is required")

    # Parse date or use today
    try:
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        else:
            target_date = datetime.now()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
        )

    # Get the stop
    gtfs_stop = feed.stops.get(stop_id)
    if not gtfs_stop:
        raise HTTPException(status_code=404, detail=f"Stop {stop_id} not found")

    # Get all routes serving this stop
    routes_info = await get_station_routes(stop_id)

    # Initialize response structure
    next_arrivals = {}

    # For each route, get the trips to its terminus
    for route_info in routes_info:
        # Skip if route_id is specified and doesn't match
        if route_id and route_id != route_info.route_id:
            continue

        # Get all trips between our stop and the terminus
        routes_response = await get_routes(
            from_station=stop_id, to_station=route_info.terminus_stop_id, date=date
        )

        # Initialize route in next_arrivals
        if route_info.route_id not in next_arrivals:
            next_arrivals[route_info.route_id] = {
                "_metadata": {
                    "route_desc": route_info.route_name,
                    "route_short_name": route_info.short_name or route_info.route_id,
                }
            }

        # Process each route's trips
        for route in routes_response.routes:
            # Get the first stop's arrival time (this is our stop)
            first_stop = next(stop for stop in route.stops if stop.id == stop_id)
            if not first_stop:
                continue

            # Initialize headsign in next_arrivals if needed
            headsign = route_info.last_stop
            if headsign not in next_arrivals[route_info.route_id]:
                next_arrivals[route_info.route_id][headsign] = []

            # Add arrival
            arrival_data = {
                "is_realtime": False,
                "provider": provider_id,
                "scheduled_time": first_stop.arrival_time,
                "scheduled_minutes": calculate_minutes_until(
                    first_stop.arrival_time, target_date.strftime("%H:%M:%S")
                ),
            }

            next_arrivals[route_info.route_id][headsign].append(arrival_data)

    # Sort arrivals and limit to requested number
    for route_id in next_arrivals:
        for headsign in next_arrivals[route_id]:
            if headsign != "_metadata":
                next_arrivals[route_id][headsign].sort(
                    key=lambda x: x["scheduled_minutes"]
                )
                next_arrivals[route_id][headsign] = next_arrivals[route_id][headsign][
                    :limit
                ]

    # Format response
    response = {
        "_metadata": {"performance": {"total_time": time.time() - start_time}},
        "stops_data": {
            stop_id: {
                "coordinates": {"lat": gtfs_stop.lat, "lon": gtfs_stop.lon},
                "lines": next_arrivals,
                "name": gtfs_stop.name,
            }
        },
    }

    return response


def calculate_minutes_until(arrival_time: str, current_time: str) -> str:
    """Calculate minutes until arrival, handling overnight times."""

    def parse_time(time_str: str) -> datetime:
        hours, minutes, seconds = map(int, time_str.split(":"))
        base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return base + timedelta(hours=hours, minutes=minutes, seconds=seconds)

    arrival = parse_time(arrival_time)
    current = parse_time(current_time)

    if arrival < current:  # Handle overnight times
        arrival += timedelta(days=1)

    diff = arrival - current
    minutes = int(diff.total_seconds() / 60)
    return f"{minutes}'"
