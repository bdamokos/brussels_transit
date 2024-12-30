import httpx
from typing import Dict, List, Tuple
import json
from pathlib import Path
from datetime import datetime, timedelta
import os
import asyncio
from get_stop_names import get_stop_names
import logging
from utils import RateLimiter, get_client
from config import get_config


# Get logger
logger = logging.getLogger("routes")

# Create cache directories for shapefiles and stops
SHAPES_CACHE_DIR = get_config("CACHE_DIR") / "shapes"
STOPS_CACHE_DIR = get_config("CACHE_DIR") / "stops"
SHAPES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
STOPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DURATION = get_config("CACHE_DURATION")
API_KEY = get_config("STIB_API_KEY")

RATE_LIMIT_DELAY = get_config("RATE_LIMIT_DELAY")

# Keep track of last API call time
last_api_call = datetime.min

# Create a global rate limiter instance
rate_limiter = RateLimiter()

# Variante 2: goint to city centre, variante 1: going to the suburbs


def load_cached_shape(line: str) -> tuple[List[Dict], bool]:
    """Load shapefile from cache if it exists and is not expired"""
    cache_file = SHAPES_CACHE_DIR / f"line_{line}.json"

    logger.debug(f"Checking cache for line {line} at {cache_file}")

    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            # Check if cache is expired based on date_fin
            current_date = datetime.now().date()
            cache_expiry = datetime.strptime(cache_data["date_fin"], "%d/%m/%Y").date()

            logger.debug(f"Cache found for line {line}:")
            logger.debug(f"  Current date: {current_date}")
            logger.debug(f"  Cache expiry: {cache_expiry}")

            if current_date > cache_expiry:
                logger.debug(f"  Cache expired")
                return [], True

            logger.debug(f"  Cache valid")
            return cache_data["variants"], False
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error reading cache for line {line}: {e}")
            return [], True

    logger.debug(f"No cache file found for line {line}")
    return [], True


def save_shape_to_cache(line: str, variants: List[Dict]) -> None:
    """Save shapefile data to cache"""
    cache_file = SHAPES_CACHE_DIR / f"line_{line}.json"

    logger.info(f"Saving shape data to cache for line {line}")
    logger.debug(f"  Variants: {len(variants)}")

    # Find the latest date_fin among all variants
    latest_date_fin = max(v["date_fin"] for v in variants)
    logger.debug(f"  Cache will expire on: {latest_date_fin}")

    cache_data = {
        "variants": variants,
        "date_fin": latest_date_fin,
        "cached_at": datetime.now().isoformat(),
    }

    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)
        logger.debug(f"Successfully saved cache for line {line}")
    except Exception as e:
        import traceback

        logger.error(
            f"Error saving cache for line {line}: {e}\n{traceback.format_exc()}"
        )


async def get_route_shape(line: str) -> List[Dict]:
    """Get route shape for a line, including all variants"""
    logger.debug(f"\n=== Starting shape fetch for line {line} ===")

    cached_variants, should_refresh = load_cached_shape(line)
    if cached_variants and not should_refresh:
        return cached_variants

    try:
        # Format line number to match API expectations
        formatted_line = f"{int(line):03}b"  # For bus lines
        formatted_line_fallback = f"{int(line):03}t"  # For tram lines
        formatted_line_fallback_2 = f"{int(line):03}m"  # For metro lines
        url = "https://stibmivb.opendatasoft.com/api/explore/v2.1/catalog/datasets/shapefiles-production/records"
        params = {
            "where": f'ligne="{formatted_line}" or ligne="{formatted_line_fallback}" or ligne="{formatted_line_fallback_2}"',
            "limit": 20,
            "apikey": API_KEY,
        }

        logger.debug(f"Making API request for line {line}")

        async with await get_client() as client:
            response = await client.get(url, params=params)
            # Update rate limits from response headers
            rate_limiter.update_from_headers(response.headers)

            logger.debug(f"API Response status: {response.status_code}")

            if response.status_code != 200:
                logger.error(f"Error response content: {response.text}")
            response.raise_for_status()

            data = response.json()
            logger.debug(f"API returned {len(data.get('results', []))} results")

            variants = []
            for result in data["results"]:
                variant_data = {
                    "variante": result["variante"],
                    "date_debut": result["date_debut"],
                    "date_fin": result["date_fin"],
                    "coordinates": result["geo_shape"]["geometry"]["coordinates"],
                }
                logger.debug(
                    f"  Found variant {variant_data['variante']}: "
                    f"{len(variant_data['coordinates'])} coordinates, "
                    f"valid {variant_data['date_debut']} to {variant_data['date_fin']}"
                )
                variants.append(variant_data)

            if variants:
                logger.debug(
                    f"Successfully processed {len(variants)} variants for line {line}"
                )
                save_shape_to_cache(line, variants)
                return variants

            logger.warning(f"No shape data found for line {line}")
            logger.info(f"Full API Response: {response.text}")
            return cached_variants or []

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:  # Too Many Requests
            logger.warning(
                f"Rate limit hit for line {line}, using cached data if available"
            )
            if hasattr(e.response, "headers"):
                logger.info(f"Response headers: {e.response.headers}")
            return cached_variants
        else:
            logger.error(f"HTTP error fetching route shape for line {line}: {str(e)}")
            logger.info(
                f"Response content: {e.response.text if hasattr(e, 'response') else 'No response content'}"
            )
            return cached_variants or []
    except Exception as e:
        logger.error(f"Unexpected error fetching route shape for line {line}: {str(e)}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return cached_variants or []
    finally:
        logger.debug(f"=== Finished shape fetch for line {line} ===\n")


def load_cached_stops(line: str) -> tuple[Dict, bool]:
    """Load stops from cache if it exists and is not expired"""
    cache_file = STOPS_CACHE_DIR / f"line_{line}_stops.json"

    logger.debug(f"Checking stops cache for line {line} at {cache_file}")

    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            cache_date = datetime.fromisoformat(cache_data["cached_at"])
            if datetime.now() - cache_date < CACHE_DURATION:
                logger.debug(f"Using cached stops data for line {line}")
                return cache_data["stops"], False

            logger.info(f"Stops cache expired for line {line}")
            return cache_data["stops"], True
        except Exception as e:
            logger.error(f"Error reading stops cache for line {line}: {e}")
            return {}, True

    logger.info(f"No stops cache found for line {line}")
    return {}, True


def save_stops_to_cache(line: str, stops_data: Dict) -> None:
    """Save stops data to cache"""
    cache_file = STOPS_CACHE_DIR / f"line_{line}_stops.json"

    cache_data = {"stops": stops_data, "cached_at": datetime.now().isoformat()}

    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)
        logger.debug(f"Saved stops cache for line {line}")
    except Exception as e:
        import traceback

        logger.error(
            f"Error saving stops cache for line {line}: {e}\n{traceback.format_exc()}"
        )


async def get_stops_for_line(line: str) -> Dict[str, List[Dict]]:
    """Get ordered stops for both directions of a line"""
    cached_stops, should_refresh = load_cached_stops(line)
    if not should_refresh:
        return cached_stops

    url = "https://stibmivb.opendatasoft.com/api/explore/v2.1/catalog/datasets/stops-by-line-production/records"
    params = {"where": f"lineid={line}", "limit": 20, "apikey": API_KEY}

    try:
        async with await get_client() as client:
            response = await client.get(url, params=params)
            # Update rate limits from response headers
            rate_limiter.update_from_headers(response.headers)

            data = response.json()

            stops_by_direction = {
                "City": [],  # Will match with variant 2
                "Suburb": [],  # Will match with variant 1
            }

            for route in data["results"]:
                direction = route["direction"]
                try:
                    destination = json.loads(route["destination"])
                    points = json.loads(route["points"])
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing JSON for {direction} direction: {e}")
                    logger.info(f"Raw destination: {route['destination']}")
                    logger.info(f"Raw points: {route['points']}")
                    continue

                logger.debug(f"Processing direction: {direction}")
                logger.debug(f"Destination: {destination['fr']} / {destination['nl']}")
                logger.debug(f"Found {len(points)} stops")

                stops_by_direction[direction] = {
                    "stops": points,
                    "destination": destination,
                }

            # Save to cache if we got valid data
            if any(stops_by_direction.values()):
                save_stops_to_cache(line, stops_by_direction)

            return stops_by_direction

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:  # Too Many Requests
            logger.warning(
                f"Rate limit hit for stops on line {line}, using cached data if available"
            )
            return cached_stops
        else:
            logger.error(f"HTTP error fetching stops for line {line}: {str(e)}")
            logger.info(
                f"Response content: {e.response.text if hasattr(e, 'response') else 'No response content'}"
            )
            return cached_stops or {"City": [], "Suburb": []}
    except Exception as e:
        logger.error(f"Unexpected error fetching stops for line {line}: {str(e)}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return cached_stops or {"City": [], "Suburb": []}


def match_stops_to_variants(shapes: Dict, stops_by_direction: Dict) -> Dict:
    """Match stops to the correct shape variants"""
    result = {}

    for line, variants in shapes.items():
        result[line] = []
        for variant in variants:
            direction = "City" if variant["variante"] == 2 else "Suburb"
            variant_data = {
                "variante": variant["variante"],
                "coordinates": variant["coordinates"],
                "date_fin": variant["date_fin"],
                "direction": direction,
                "stops": stops_by_direction.get(direction, {}).get("stops", []),
                "destination": stops_by_direction.get(direction, {}).get(
                    "destination", {}
                ),
            }
            result[line].append(variant_data)

    return result


async def get_route_data(line: str) -> Dict:
    """Get complete route data including shapes and stops"""
    shapes = await get_route_shape(line)
    stops_by_direction = await get_stops_for_line(line)

    # Get all unique stop IDs from both directions
    all_stop_ids = set()
    for direction_data in stops_by_direction.values():
        for stop in direction_data.get("stops", []):
            all_stop_ids.add(stop["id"])

    # Get stop details using existing function
    stop_details = get_stop_names(list(all_stop_ids))

    # Add stop details to the data structure
    for direction, direction_data in stops_by_direction.items():
        for stop in direction_data.get("stops", []):
            stop_id = stop["id"]
            if stop_id in stop_details:
                stop["name"] = stop_details[stop_id]["name"]
                stop["coordinates"] = stop_details[stop_id]["coordinates"]

    return {line: match_stops_to_variants({line: shapes}, stops_by_direction)[line]}
