from fastapi import FastAPI, HTTPException, Query, Request, Path
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Tuple, Dict, Union, AsyncGenerator
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
from contextlib import asynccontextmanager
import asyncio

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
    BoundingBox,
)
from .gtfs_parquet import FlixbusFeed, load_feed
from .cache_manager import GTFSCache

# Configure download directory - hardcoded to project root/downloads
DOWNLOAD_DIR = FilePath(os.environ["PROJECT_ROOT"]) / "downloads"
CACHE_DIR = FilePath(os.environ["PROJECT_ROOT"]) / "cache"

# Configure graceful timeout (in seconds)
GRACEFUL_TIMEOUT = 3
# Configure grace period for temporary disconnections (in seconds)
GRACE_PERIOD = 5

# Configure logging
logger = logging.getLogger("schedule_explorer.backend")
logging.basicConfig(level=logging.DEBUG)

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
gtfs_cache: Optional[GTFSCache] = None
current_provider: Optional[str] = None
available_providers: List[Provider] = []
logger = logging.getLogger("schedule_explorer.backend")
db: Optional[MobilityAPI] = None


@app.on_event("startup")
async def startup_event():
    """Load available GTFS providers on startup"""
    global available_providers, db, gtfs_cache
    available_providers = find_gtfs_directories()
    db = MobilityAPI(data_dir=DOWNLOAD_DIR)
    gtfs_cache = GTFSCache(CACHE_DIR)


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    global gtfs_cache
    if gtfs_cache:
        gtfs_cache.close()


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@asynccontextmanager
async def check_client_connected(request: Request, operation: str):
    """Context manager to check if client is still connected.

    Args:
        request: The FastAPI request object
        operation: Description of the operation for logging

    Raises:
        HTTPException: If client disconnects during operation
    """
    start_time = time.time()
    operation_completed = False
    try:
        yield
        operation_completed = True
    finally:
        # If operation took less than GRACEFUL_TIMEOUT seconds, don't check connection
        elapsed = time.time() - start_time
        if elapsed < GRACEFUL_TIMEOUT:
            return

        # Check if client is still connected
        if await request.is_disconnected():
            # If operation is already complete, no need to wait
            if operation_completed:
                logger.info(
                    f"Operation {operation} completed despite client disconnection after {elapsed:.2f}s"
                )
                return

            # If operation is still ongoing, wait for GRACE_PERIOD to see if client reconnects
            try:
                for _ in range(GRACE_PERIOD):
                    await asyncio.sleep(1)
                    if not await request.is_disconnected():
                        logger.info(
                            f"Client reconnected during {operation} after temporary disconnection"
                        )
                        return
                    if operation_completed:
                        logger.info(
                            f"Operation {operation} completed during grace period"
                        )
                        return

                # If we get here, client is still disconnected after grace period
                logger.info(
                    f"Client disconnected during {operation} after {elapsed:.2f}s"
                )
                raise HTTPException(status_code=499, detail="Client disconnected")
            except asyncio.CancelledError:
                # If the operation completes during the grace period wait
                if operation_completed:
                    return
                raise


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


@asynccontextmanager
async def get_feed(provider_id: str) -> AsyncGenerator[Optional[FlixbusFeed], None]:
    """Context manager to get the feed for a provider from cache.

    Usage:
        async with get_feed(provider_id) as feed:
            if not feed:
                raise HTTPException(status_code=503, detail="GTFS data not loaded")
            # Use feed here
    """
    global gtfs_cache, current_provider

    if not gtfs_cache:
        yield None
        return

    # Check if we have a cached feed
    feed = gtfs_cache.get_feed(provider_id)
    if feed:
        logger.debug(f"Using cached feed for provider {provider_id}")
        yield feed
        return

    # Find the provider's dataset directory from metadata
    metadata_file = DOWNLOAD_DIR / "datasets_metadata.json"
    if not metadata_file.exists():
        logger.error(f"No metadata found for provider {provider_id}")
        yield None
        return

    try:
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
            dataset_info = None
            provider = get_provider_by_id(provider_id)
            if not provider:
                logger.error(f"Provider {provider_id} not found")
                yield None
                return

            for info in metadata.values():
                if (
                    info.get("provider_id") == provider.raw_id
                    and info.get("dataset_id") == provider.latest_dataset.id
                ):
                    dataset_info = info
                    break

            if not dataset_info:
                logger.error(f"No dataset info found for provider {provider_id}")
                yield None
                return

            dataset_dir = FilePath(dataset_info["download_path"])
            if not dataset_dir.exists():
                logger.error(f"Dataset directory not found: {dataset_dir}")
                yield None
                return

            # Get loader from cache with correct directory
            loader = gtfs_cache.get_loader(provider_id, str(dataset_dir))
            if not loader:
                logger.error(f"Failed to get loader for provider {provider_id}")
                yield None
                return

            # Load feed
            feed = loader.load_feed()
            if feed:
                # Cache the feed
                gtfs_cache.cache_feed(provider_id, feed)
                logger.info(f"Cached feed for provider {provider_id}")
            try:
                yield feed
            finally:
                # Any cleanup if needed
                pass
    except Exception as e:
        logger.error(f"Error in get_feed for provider {provider_id}: {e}", exc_info=True)
        yield None


async def ensure_provider_loaded(
    provider_id: str, auto_download: bool = False
) -> Tuple[bool, str, Optional[Provider]]:
    """Ensure provider is loaded, loading or downloading it if available."""
    global current_provider, available_providers, gtfs_cache

    # Check provider availability
    is_local, can_download, provider = await check_provider_availability(provider_id)

    if not is_local and not can_download:
        return (
            False,
            f"Provider {provider_id} is not available. Please check the provider ID or use GET /api/providers/be to list available providers.",
            None,
        )

    if not is_local and can_download:
        if not auto_download:
            return (
                False,
                f"Provider {provider_id} needs to be downloaded first. Add download=true to your request to automatically download it.",
                None,
            )

        # Download the provider
        try:
            logger.info(f"Downloading provider {provider_id}...")
            result = db.download_latest_dataset(provider_id, str(DOWNLOAD_DIR))
            if not result:
                return False, f"Failed to download provider {provider_id}", None

            # Refresh available providers after download
            available_providers = find_gtfs_directories()

            # Refresh provider info after download
            is_local, can_download, provider = await check_provider_availability(
                provider_id
            )
            if not is_local:
                return (
                    False,
                    f"Provider {provider_id} download succeeded but provider not found locally",
                    None,
                )

            logger.info(f"Successfully downloaded provider {provider_id}")
        except Exception as e:
            logger.error(f"Error downloading provider {provider_id}: {str(e)}")
            return False, f"Error downloading provider {provider_id}: {str(e)}", None

    # At this point, provider exists locally
    if current_provider == provider.id:
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

        logger.info(f"Loading GTFS data for provider {provider_id}...")

        # Get or create loader from cache
        loader = gtfs_cache.get_loader(provider.id, str(dataset_dir))
        if not loader:
            return False, f"Failed to load GTFS data for provider {provider_id}", None

        # Load feed using the loader
        feed = loader.load_feed()
        if not feed:
            return False, f"Failed to load feed for provider {provider_id}", None

        current_provider = provider.id
        logger.info(f"Successfully loaded GTFS data for provider {provider_id}")
        return True, f"Loaded GTFS data for {provider_id}", provider
    except Exception as e:
        logger.error(f"Error loading provider {provider_id}: {str(e)}")
        return False, f"Error loading provider {provider_id}: {str(e)}", None


async def handle_provider_request(
    provider_id: str, request: Request
) -> Tuple[bool, str, Optional[Provider]]:
    """Handle a request that requires a specific provider, automatically loading or downloading if needed.

    Args:
        provider_id: The ID of the provider needed
        request: The FastAPI request object to get query parameters

    Returns:
        Same as ensure_provider_loaded
    """
    # Check if auto-download is requested
    auto_download = request.query_params.get("download", "").lower() == "true"

    # Try to ensure the provider is loaded
    is_ready, message, provider = await ensure_provider_loaded(
        provider_id, auto_download
    )

    if not is_ready:
        raise HTTPException(
            status_code=(
                409 if "being loaded" in message or "download" in message else 404
            ),
            detail=message,
        )

    return is_ready, message, provider


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

                        # Create bounding box if coordinates are available
                        bounding_box = None
                        if all(
                            dataset_info.get(key) is not None
                            for key in [
                                "minimum_latitude",
                                "maximum_latitude",
                                "minimum_longitude",
                                "maximum_longitude",
                            ]
                        ):
                            bounding_box = BoundingBox(
                                min_lat=dataset_info["minimum_latitude"],
                                max_lat=dataset_info["maximum_latitude"],
                                min_lon=dataset_info["minimum_longitude"],
                                max_lon=dataset_info["maximum_longitude"],
                            )

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
                            bounding_box=bounding_box,
                        )
            except Exception as e:
                logger.error(f"Error reading metadata file {metadata_file}: {str(e)}")

    return list(providers.values())


def get_provider_by_id(provider_id: str) -> Optional[Provider]:
    """Get provider by either its raw ID or long ID."""
    global available_providers

    # Refresh available providers if empty
    if not available_providers:
        available_providers = find_gtfs_directories()

    # First try to find by raw ID (this is the preferred method)
    provider = next((p for p in available_providers if p.raw_id == provider_id), None)
    if provider:
        return provider

    # If not found, try to find by long ID (for backward compatibility)
    return next((p for p in available_providers if p.id == provider_id), None)


@app.get("/api/providers/search", response_model=List[Dict])
async def search_providers(
    country_code: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
):
    """Search for providers using any combination of criteria.

    Args:
        country_code: Two-letter ISO country code (e.g., "BE")
        name: Provider name to search for
        provider_id: Provider ID to search for

    At least one parameter must be provided.
    """
    try:
        if not any([country_code, name, provider_id]):
            raise HTTPException(
                status_code=400,
                detail="At least one search criteria must be provided (country_code, name, or provider_id)",
            )

        providers = []
        if provider_id:
            # Search by ID
            provider = db.get_provider_info(provider_id=provider_id)
            if provider:
                providers = [provider]
        elif name:
            # Search by name
            providers = db.get_provider_info(name=name)
        elif country_code:
            # Search by country
            providers = db.get_provider_info(country_code=country_code)

        logger.debug(
            f"Got {len(providers) if providers else 0} providers from MobilityAPI"
        )

        # Convert to list if single provider returned
        if isinstance(providers, dict):
            providers = [providers]
        elif providers is None:
            providers = []

        # Add sanitized names and map fields from the MobilityAPI response
        result_providers = []
        for provider in providers:
            if not isinstance(provider, dict):
                continue

            result_provider = {}

            # Copy all existing fields
            result_provider.update(provider)

            # Add sanitized name
            provider_name = provider.get("provider", "")
            if provider_name and hasattr(db, "_sanitize_provider_name"):
                result_provider["sanitized_name"] = db._sanitize_provider_name(
                    provider_name
                )
            else:
                result_provider["sanitized_name"] = ""

            # Map bounding box from latest_dataset
            latest_dataset = provider.get("latest_dataset", {})
            if latest_dataset and isinstance(latest_dataset, dict):
                bbox = latest_dataset.get("bounding_box", {})
                if isinstance(bbox, dict):
                    result_provider["bounding_box"] = {
                        "min_lat": bbox.get("minimum_latitude", 0),
                        "max_lat": bbox.get("maximum_latitude", 0),
                        "min_lon": bbox.get("minimum_longitude", 0),
                        "max_lon": bbox.get("maximum_longitude", 0),
                    }
                else:
                    result_provider["bounding_box"] = {
                        "min_lat": 0,
                        "max_lat": 0,
                        "min_lon": 0,
                        "max_lon": 0,
                    }
            else:
                result_provider["bounding_box"] = {
                    "min_lat": 0,
                    "max_lat": 0,
                    "min_lon": 0,
                    "max_lon": 0,
                }

            # Map downloaded_at from latest_dataset
            result_provider["downloaded_at"] = (
                latest_dataset.get("downloaded_at", None)
                if isinstance(latest_dataset, dict)
                else None
            )

            # Map hash from latest_dataset
            result_provider["hash"] = (
                latest_dataset.get("hash", None)
                if isinstance(latest_dataset, dict)
                else None
            )

            # Map validation_report from latest_dataset
            validation = (
                latest_dataset.get("validation_report", {})
                if isinstance(latest_dataset, dict)
                else {}
            )
            if isinstance(validation, dict):
                result_provider["validation_report"] = {
                    "total_error": validation.get("total_error", 0),
                    "total_warning": validation.get("total_warning", 0),
                    "total_info": validation.get("total_info", 0),
                }
            else:
                result_provider["validation_report"] = {
                    "total_error": 0,
                    "total_warning": 0,
                    "total_info": 0,
                }

            result_providers.append(result_provider)

        return result_providers
    except Exception as e:
        logger.error(f"Error searching providers: {str(e)}")
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


@app.post("/provider/{provider_id}")
async def set_provider(provider_id: str):
    """Set the current GTFS provider and load its data"""
    global current_provider, available_providers, gtfs_cache

    # Get provider info
    provider = get_provider_by_id(provider_id)
    if not provider:
        raise HTTPException(
            status_code=404,
            detail=f"Provider {provider_id} not found",
        )

    # If the requested provider is already loaded, return early
    if current_provider == provider.id:
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

        # Get or create loader from cache with correct directory
        loader = gtfs_cache.get_loader(provider.id, str(dataset_dir))
        if not loader:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load GTFS data for provider {provider.id}",
            )

        # Load feed
        feed = loader.load_feed()
        if not feed:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load feed for provider {provider.id}",
            )

        # Cache the feed
        gtfs_cache.cache_feed(provider.id, feed)
        logger.info(f"Cached feed for provider {provider.id}")

        current_provider = provider.id
        return {
            "status": "success",
            "message": f"Loaded GTFS data for {provider.id}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading provider {provider.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/{provider_id}/stations/search", response_model=List[StationResponse])
async def search_stations_with_provider(
    request: Request,
    provider_id: str = Path(...),
    query: str = Query(..., min_length=2),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
):
    """Search for stations by name with explicit provider"""
    await handle_provider_request(provider_id, request)
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

    async with get_feed(provider_id) as feed:
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
    request: Request,
    provider_id: str = Path(...),
    from_station: str = Query(..., description="Departure station ID"),
    to_station: str = Query(..., description="Destination station ID"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
):
    """Get all routes between two stations for a specific date with explicit provider"""
    await handle_provider_request(provider_id, request)
    return await get_routes(
        request=request,
        from_station=from_station,
        to_station=to_station,
        date=date,
        language=language,
        provider_id=provider_id,
    )


@app.get("/routes", response_model=RouteResponse)
async def get_routes(
    request: Request,
    from_station: str = Query(..., description="Departure station ID"),
    to_station: str = Query(..., description="Destination station ID"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Get all routes between two stations for a specific date"""
    async with check_client_connected(request, "route search"):
        if provider_id:
            # Check provider availability and load if needed
            is_ready, message, provider = await ensure_provider_loaded(provider_id)
            if not is_ready:
                raise HTTPException(
                    status_code=409 if "being loaded" in message else 404,
                    detail=message,
                )

        async with get_feed(provider_id) as feed:
            if not feed:
                raise HTTPException(status_code=503, detail="GTFS data not loaded")

            # Split station IDs if they contain commas
            from_stations = [s.strip() for s in from_station.split(",")]
            to_stations = [s.strip() for s in to_station.split(",")]

            # Validate stations
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
                    async with check_client_connected(
                        request, f"finding trips between {from_id} and {to_id}"
                    ):
                        routes = feed.find_trips_between_stations(from_id, to_id)
                        all_routes.extend(routes)

            # Convert to response format
            route_responses = []
            for route in all_routes:
                # Get stops for this route
                stops = route.get_stops_between(from_station, to_station)

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

                route_responses.append(
                    Route(
                        route_id=route.route_id,
                        route_name=route_name,
                        short_name=(
                            route.short_name if hasattr(route, "short_name") else None
                        ),
                        color=color,
                        text_color=text_color,
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
                            Shape(
                                shape_id=route.shape.shape_id, points=route.shape.points
                            )
                            if route.shape
                            else None
                        ),
                        line_number=(
                            route.short_name if hasattr(route, "short_name") else ""
                        ),
                        
                        
                        headsigns=route.headsigns,
                        service_ids=route.service_ids,  # Include for debugging
                    )
                )

            return RouteResponse(
                routes=route_responses, total_routes=len(route_responses)
            )


@app.get(
    "/api/{provider_id}/stations/{station_id}/routes", response_model=List[RouteInfo]
)
async def get_station_routes_with_provider(
    request: Request,
    provider_id: str = Path(...),
    station_id: str = Path(...),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
):
    """Get all routes that serve this station with detailed information with explicit provider"""
    return await get_station_routes(
        request=request,
        station_id=station_id,
        language=language,
        provider_id=provider_id,
    )


@app.get("/stations/{station_id}/routes", response_model=List[RouteInfo])
async def get_station_routes(
    request: Request,
    station_id: str = Path(...),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Get all routes that serve this station with detailed information"""
    async with check_client_connected(
        request, f"getting routes for station {station_id}"
    ):
        if provider_id:
            # Check provider availability and load if needed
            is_ready, message, provider = await ensure_provider_loaded(provider_id)
            if not is_ready:
                raise HTTPException(
                    status_code=409 if "being loaded" in message else 404,
                    detail=message,
                )

        async with get_feed(provider_id) as feed:
            if not feed:
                raise HTTPException(status_code=503, detail="GTFS data not loaded")

            if station_id not in feed.stops:
                raise HTTPException(
                    status_code=404, detail=f"Station {station_id} not found"
                )

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
                async with check_client_connected(
                    request, f"processing route {route.route_id}"
                ):
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
                                feed.get_stop_name(s.stop.id, language)
                                if language != "default"
                                else s.stop.name
                            )
                            for s in route.stops
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
                                    route.short_name
                                    if hasattr(route, "short_name")
                                    else None
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

            # Return routes_info, ensuring it's always a list
            return routes_info if routes_info else []


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
    request: Request,
    station_id: str = Path(...),
    language: Optional[str] = Query(
        None, description="Language code (e.g., 'fr', 'nl')"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Get all possible destination stations from a given station"""
    async with check_client_connected(
        request, f"finding destinations from station {station_id}"
    ):
        if provider_id:
            # Check provider availability and load if needed
            is_ready, message, provider = await ensure_provider_loaded(provider_id)
            if not is_ready:
                raise HTTPException(
                    status_code=409 if "being loaded" in message else 404,
                    detail=message,
                )

        async with get_feed(provider_id) as feed:
            if not feed:
                raise HTTPException(status_code=503, detail="GTFS data not loaded")
            # Use feed here
        if station_id not in feed.stops:
            raise HTTPException(
                status_code=404, detail=f"Station {station_id} not found"
            )

        # Find all routes that start from this station
        destinations = set()
        if not feed.routes:
            logger.warning("No routes found in feed")
            return []

        for route in feed.routes:
            if route is None:
                logger.debug("Skipping None route")
                continue

            try:
                # Get all stops in this route
                stops = route.get_stops_between(station_id, None)

                # If this station is in the route
                if stops and stops[0].stop.id == station_id:
                    # Add all subsequent stops as potential destinations
                    for stop in stops[1:]:
                        if stop and stop.stop and stop.stop.id:
                            destinations.add(stop.stop.id)

            except Exception as e:
                logger.error(
                    f"Error processing route {route.route_id if route else 'unknown'}: {e}",
                    exc_info=True,
                )
                continue

        # Convert to response format
        responses = []
        for stop_id in destinations:
            try:
                if stop_id not in feed.stops:
                    logger.warning(f"Stop {stop_id} not found in feed.stops")
                    continue

                stop = feed.stops[stop_id]
                if stop is None:
                    logger.warning(f"Stop {stop_id} is None in feed.stops")
                    continue

                name = feed.get_stop_name(stop_id, language) if language else stop.name
                if pd.isna(name) or not name:
                    logger.warning(f"Invalid name for stop {stop_id}")
                    continue

                responses.append(
                    StationResponse(
                        id=stop_id,
                        name=name,
                        location=Location(lat=stop.lat, lon=stop.lon),
                        translations=stop.translations,
                    )
                )
            except Exception as e:
                logger.error(
                    f"Error creating response for stop {stop_id}: {e}", exc_info=True
                )
                continue

        return responses


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
    request: Request,
    station_id: str = Path(...),
    language: Optional[str] = Query(
        None, description="Language code (e.g., 'fr', 'nl')"
    ),
    provider_id: Optional[str] = Query(None, description="Optional provider ID"),
):
    """Get all possible origin stations that can reach a given station"""
    async with check_client_connected(
        request, f"finding origins for station {station_id}"
    ):
        if provider_id:
            # Check provider availability and load if needed
            is_ready, message, provider = await ensure_provider_loaded(provider_id)
            if not is_ready:
                raise HTTPException(
                    status_code=409 if "being loaded" in message else 404,
                    detail=message,
                )

        async with get_feed(provider_id) as feed:
            if not feed:
                raise HTTPException(status_code=503, detail="GTFS data not loaded")
            # Use feed hereException(status_code=503, detail="GTFS data not loaded")

        if station_id not in feed.stops:
            raise HTTPException(
                status_code=404, detail=f"Station {station_id} not found"
            )

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
                location=Location(
                    lat=feed.stops[stop_id].lat, lon=feed.stops[stop_id].lon
                ),
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
    request: Request,
    provider_id: str,
    stop_id: str,
    route_id: Optional[str] = None,
    limit: Optional[int] = 2,
    time_local: Optional[str] = None,
    time_utc: Optional[str] = None,
):
    """Get waiting times for a stop."""
    return await get_waiting_times_impl(
        request=request,
        provider_id=provider_id,
        stop_id=stop_id,
        route_id=route_id,
        limit=limit,
        time_local=time_local,
        time_utc=time_utc,
    )


async def get_waiting_times_impl(
    request: Request,
    provider_id: str,
    stop_id: str,
    route_id: Optional[str] = None,
    limit: Optional[int] = 2,
    time_local: Optional[str] = None,
    time_utc: Optional[str] = None,
):
    """Implementation of get_waiting_times that handles both path and query parameter formats."""
    async with check_client_connected(
        request, f"getting waiting times for stop {stop_id}"
    ):
        start_time = time.time()

        # Use the handler to ensure the correct provider is loaded
        is_ready, message, provider = await handle_provider_request(
            provider_id, request
        )
        if not is_ready:
            raise HTTPException(
                status_code=409 if "being loaded" in message else 404,
                detail=message,
            )

        # Check cache first
        if gtfs_cache:
            cached_times = gtfs_cache.get_stop_times(provider_id, stop_id)
            if cached_times:
                logger.info(f"Using cached stop times for {provider_id}/{stop_id}")
                return cached_times

        async with get_feed(provider_id) as feed:
            if not feed:
                raise HTTPException(status_code=503, detail="GTFS data not loaded")

        # Get the stop
        gtfs_stop = feed.stops.get(stop_id)
        if not gtfs_stop:
            raise HTTPException(status_code=404, detail=f"Stop {stop_id} not found")

        # Get the agency timezone
        agency_timezone = None
        if feed.agencies:
            # Get the first agency's timezone (all agencies inside a GTFS dataset must have the same timezone)
            agency_timezone = next(iter(feed.agencies.values())).agency_timezone

        # If no agency timezone found, use the server timezone
        if not agency_timezone:
            agency_timezone = datetime.now().astimezone().tzname()

        # Parse date or use current time (converted from UTC to local)
        try:
            if time_local:
                # If time is provided, assume it's in local timezone
                target_time = datetime.strptime(time_local, "%H:%M:%S").time()
                current_time = time_local
            elif time_utc:
                # If UTC time is provided, convert it to local
                utc_time = datetime.strptime(time_utc, "%H:%M:%S")
                local_time = utc_time.astimezone(ZoneInfo(agency_timezone))
                target_time = local_time.time()
                current_time = local_time.strftime("%H:%M:%S")
            else:
                # If no time provided, use current local time
                local_time = datetime.now(ZoneInfo(agency_timezone))
                target_time = local_time.time()
                current_time = local_time.strftime("%H:%M:%S")
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid time format. Use HH:MM:SS"
            )

        # Initialize response structure
        next_arrivals: Dict[str, Dict[str, List[ArrivalInfo]]] = {}

        # Find all routes that serve this stop
        for route in feed.routes:
            # Skip if route_id is specified and doesn't match
            if route_id and route_id != route.route_id:
                continue

            # Check if this stop is served by this route
            station_in_route = False
            route_stops = []
            for stop in route.stops:
                if stop.stop.id == stop_id:
                    station_in_route = True
                    route_stops.append(stop)

            if not station_in_route:
                continue

            # Create RouteInfo for this route
            route_info = RouteInfo(
                route_id=route.route_id,
                route_name=(
                    route.route_name
                    if not pd.isna(route.route_name)
                    else f"Route {route.route_id}"
                ),
                short_name=route.short_name if hasattr(route, "short_name") else None,
                color=(
                    route.color
                    if hasattr(route, "color") and not pd.isna(route.color)
                    else None
                ),
                text_color=(
                    route.text_color
                    if hasattr(route, "text_color") and not pd.isna(route.text_color)
                    else None
                ),
                first_stop=route.stops[0].stop.name,
                last_stop=route.stops[-1].stop.name,
                stops=None,  # Don't include full stop list
                headsign=route.stops[-1].stop.name,
                service_days=route.service_days,
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

            # Initialize route in next_arrivals if needed
            if route.route_id not in next_arrivals:
                next_arrivals[route.route_id] = {
                    "_metadata": [
                        RouteMetadata(
                            route_desc=f"Route {route.route_id}",
                            route_short_name=route.short_name or route.route_id,
                        )
                    ],
                }

            # Group stops by headsign (direction)
            for route_stop in route_stops:
                # Find the terminus for this stop's trip
                terminus_idx = None
                for i, stop in enumerate(route.stops):
                    if stop.stop.id == route_stop.stop.id:
                        terminus_idx = i
                        break

                if terminus_idx is None:
                    continue

                # Get the headsign (last stop name in this direction)
                headsign = route.stops[-1].stop.name

                # Initialize headsign in next_arrivals if needed
                if headsign not in next_arrivals[route.route_id]:
                    next_arrivals[route.route_id][headsign] = []

                # Calculate waiting time
                waiting_time = calculate_minutes_until(
                    route_stop.arrival_time, current_time
                )

                # Add arrival info
                next_arrivals[route.route_id][headsign].append(
                    ArrivalInfo(
                        route=route_info,
                        waiting_time=int(waiting_time.rstrip("'")),
                        is_realtime=False,
                        provider=provider.raw_id,
                        scheduled_time=route_stop.arrival_time,
                        departure_time=route_stop.departure_time,
                    )
                )

        # Sort arrivals and limit to requested number
        for route_id, route_data in next_arrivals.items():
            # Skip _metadata field when sorting arrivals
            for headsign, arrivals in route_data.items():
                if headsign == "_metadata":
                    continue
                # Sort by waiting_time
                route_data[headsign] = sorted(
                    arrivals,
                    key=lambda x: x.waiting_time,
                )[:limit]

        # Format response
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

        # Cache the response
        if gtfs_cache:
            gtfs_cache.cache_stop_times(provider_id, stop_id, response)
            logger.info(f"Cached stop times for {provider_id}/{stop_id}")

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
    request: Request,
    provider_id: str = Path(...),
    route_id: str = Path(...),
):
    """Get the color scheme for a route."""
    # Use the new handler
    _, _, provider = await handle_provider_request(provider_id, request)
    async with get_feed(provider_id) as feed:
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
    request: Request,
    provider_id: str = Path(...),
    route_id: str = Path(...),
):
    """Get detailed information about a route/line."""
    # Use the new handler
    _, _, provider = await handle_provider_request(provider_id, request)
    async with get_feed(provider_id) as feed:
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


@app.delete("/api/datasets/{provider_id}/{dataset_id}")
async def delete_dataset(
    provider_id: str = Path(..., description="Provider ID"),
    dataset_id: str = Path(..., description="Dataset ID"),
):
    """Delete a specific dataset for a provider."""
    try:
        db.delete_dataset(provider_id, dataset_id)
        return {
            "status": "success",
            "message": f"Deleted dataset {dataset_id} for provider {provider_id}",
        }
    except Exception as e:
        logger.error(
            f"Error deleting dataset {dataset_id} for provider {provider_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/datasets/{provider_id}")
async def delete_provider_datasets(
    provider_id: str = Path(..., description="Provider ID"),
):
    """Delete all datasets for a specific provider."""
    try:
        db.delete_provider_datasets(provider_id)
        return {
            "status": "success",
            "message": f"Deleted all datasets for provider {provider_id}",
        }
    except Exception as e:
        logger.error(f"Error deleting datasets for provider {provider_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/datasets")
async def delete_all_datasets():
    """Delete all downloaded datasets."""
    try:
        db.delete_all_datasets()
        return {
            "status": "success",
            "message": "Deleted all datasets",
        }
    except Exception as e:
        logger.error(f"Error deleting all datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/{provider_id}/stops/bbox",
    response_model=Union[List[StationResponse], Dict[str, int]],
)
async def get_stops_in_bbox(
    request: Request,
    provider_id: str = Path(...),
    min_lat: float = Query(..., description="Minimum latitude of bounding box"),
    min_lon: float = Query(..., description="Minimum longitude of bounding box"),
    max_lat: float = Query(..., description="Maximum latitude of bounding box"),
    max_lon: float = Query(..., description="Maximum longitude of bounding box"),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
    offset: Optional[int] = Query(0, description="Number of stops to skip"),
    limit: Optional[int] = Query(None, description="Maximum number of stops to return"),
    count_only: bool = Query(
        False, description="Only return the count of stops in the bounding box"
    ),
):
    """Get all stops within a bounding box for a specific provider."""
    async with check_client_connected(request, "bbox search"):
        # Validate bounding box
        try:
            bbox = BoundingBox(
                min_lat=min_lat,
                min_lon=min_lon,
                max_lat=max_lat,
                max_lon=max_lon,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Check provider availability and load if needed
        is_ready, message, provider = await ensure_provider_loaded(provider_id)
        if not is_ready:
            raise HTTPException(
                status_code=409 if "being loaded" in message else 404,
                detail=message,
            )

        async with get_feed(provider_id) as feed:
            if not feed:
                raise HTTPException(status_code=503, detail="GTFS data not loaded")
        # Get stops using the new method
        result = feed.get_stops_in_bbox(bbox, count_only)

        if count_only:
            return result

        # Sort stops by ID to ensure consistent pagination
        stops = sorted(result, key=lambda x: x.id)

        # Apply pagination
        paginated_stops = stops[offset:]
        if limit is not None:
            paginated_stops = paginated_stops[:limit]

        # Now process routes only for the paginated stops
        for stop in paginated_stops:
            routes_info = []
            seen_route_ids = set()

            for route in feed.routes:
                # Skip if we've already seen this route
                if route.route_id in seen_route_ids:
                    continue

                # Check if this stop is served by this route
                station_in_route = False
                for route_stop in route.stops:
                    if route_stop.stop.id == stop.id:
                        station_in_route = True
                        break

                if station_in_route:
                    seen_route_ids.add(route.route_id)

                    # Get stop names in the correct language
                    stop_names = [
                        (
                            feed.get_stop_name(s.stop.id, language)
                            if language != "default"
                            else s.stop.name
                        )
                        for s in route.stops
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
                        if hasattr(route, "text_color")
                        and not pd.isna(route.text_color)
                        else None
                    )

                    routes_info.append(
                        RouteInfo(
                            route_id=route.route_id,
                            route_name=route_name,
                            short_name=(
                                route.short_name
                                if hasattr(route, "short_name")
                                else None
                            ),
                            color=color,
                            text_color=text_color,
                            first_stop=stop_names[0],
                            last_stop=stop_names[-1],
                            stops=stop_names,
                            headsign=route.stops[-1].stop.name,
                            service_days=route.service_days,
                            parent_station_id=getattr(stop, "parent_station", None),
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

            stop.routes = routes_info

        return paginated_stops


@app.get("/api/{provider_id}/routes/find", response_model=List[RouteInfo])
async def find_route_by_name(
    provider_id: str = Path(...),
    route_name: Optional[str] = Query(
        None, description="Full route name to search for"
    ),
    short_name: Optional[str] = Query(
        None, description="Short name (line number) to search for"
    ),
    language: Optional[str] = Query(
        "default", description="Language code (e.g., 'fr', 'nl') or 'default'"
    ),
):
    """Find route IDs by searching with route names or short names.
    Returns all matching routes with their details."""

    if not route_name and not short_name:
        raise HTTPException(
            status_code=400, detail="Either route_name or short_name must be provided"
        )

    # Check provider availability and load if needed
    is_ready, message, provider = await ensure_provider_loaded(provider_id)
    if not is_ready:
        raise HTTPException(
            status_code=409 if "being loaded" in message else 404,
            detail=message,
        )

    async with get_feed(provider_id) as feed:
            if not feed:
                raise HTTPException(status_code=503, detail="GTFS data not loaded")
    matching_routes = []
    for route in feed.routes:
        # Check if route matches any of the search criteria
        matches = False

        if route_name:
            # Check route_name against various name fields
            route_full_name = (
                route.route_name
                if hasattr(route, "route_name") and not pd.isna(route.route_name)
                else ""
            )
            if route_name.lower() in route_full_name.lower():
                matches = True

        if short_name and not matches:
            # Check short_name
            route_short = (
                route.short_name
                if hasattr(route, "short_name") and not pd.isna(route.short_name)
                else ""
            )
            if short_name.lower() == route_short.lower():
                matches = True

        if matches:
            # Get stop names in the correct language
            stop_names = [
                (
                    feed.get_stop_name(s.stop.id, language)
                    if language != "default"
                    else s.stop.name
                )
                for s in route.stops
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

            matching_routes.append(
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

    return matching_routes
