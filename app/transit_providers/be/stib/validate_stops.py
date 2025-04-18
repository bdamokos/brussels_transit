import json
from dataclasses import dataclass
from typing import Dict, List, Optional, TypedDict, Tuple
from pathlib import Path
import logging
from math import sqrt
import os

from .routes import get_route_data

# Get logger
logger = logging.getLogger("stib.validate_stops")


@dataclass
class Stop:
    id: str
    order: int
    name: str
    coordinates: Tuple[float, float]


@dataclass
class RouteVariant:
    line: str
    direction: str  # 'City' or 'Suburb'
    stops: List[Stop]
    destination: Dict[str, str]  # {'fr': str, 'nl': str}
    shape: List[List[float]]


@dataclass
class Terminus:
    stop_id: str
    stop_name: str
    direction: str
    destination: Dict[str, str]

    def get(self, key, default=None):
        """Add get method to make the class more dict-like"""
        return getattr(self, key, default)


def load_stops_data() -> Dict[str, Dict]:
    """Load the master stops data with coordinates"""
    try:
        with open("cache/stops.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"File cache/stops.json not found. Initializing empty cache.")
        # Create empty cache file
        with open("cache/stops.json", "w") as f:
            json.dump({}, f)
        return {}


async def load_line_stops(line: str) -> Dict:
    """Load stops data for a line, fetching from API if needed"""
    cache_path = f"cache/stops/line_{line}_stops.json"

    try:
        with open(cache_path, "r") as f:
            if data := json.load(f):
                return data["stops"]
            else:
                logger.warning(f"Cache file {cache_path} is empty")
                return {}
    except FileNotFoundError:
        logger.info(f"No cache found for line {line}, fetching from API...")
        # Import here to avoid circular imports


        # Fetch the route data which includes stops
        route_data = await get_route_data(line)
        if route_data and line in route_data:
            # Extract stops data from route_data and save to cache
            stops_data = {
                "City": next(
                    (
                        variant
                        for variant in route_data[line]
                        if variant["direction"] == "City"
                    ),
                    {},
                ),
                "Suburb": next(
                    (
                        variant
                        for variant in route_data[line]
                        if variant["direction"] == "Suburb"
                    ),
                    {},
                ),
            }

            # Ensure cache directory exists
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)

            # Save to cache
            with open(cache_path, "w") as f:
                json.dump({"stops": stops_data}, f)

            return stops_data
        else:
            logger.error(f"Failed to fetch route data for line {line}")
            return {}
    except Exception as e:
        logger.error(f"Error loading stops for line {line}: {e}")
        return {}


async def validate_line_stops(line):
    try:
        # Get route data
        from routes import get_route_data  # Import the correct function

        route_data = await get_route_data(line)
        logger.debug(f"Got route data for line {line}: {route_data}")
        if not route_data or line not in route_data:
            logger.error(f"No route data found for line {line}")
            return []

        # Load stops data with coordinates
        stops_data = load_stops_data()
        logger.debug(f"Loaded stops data with {len(stops_data)} stops")

        variants = []
        for variant in route_data[line]:
            if "stops" not in variant:
                logger.warning(f"No stops data found for line {line} variant")
                continue

            try:
                stops = variant["stops"]
                direction = variant.get("direction", "Unknown")
                destination = variant.get("destination", {"fr": "Unknown"})

                logger.debug(f"Processing variant for line {line}:")
                logger.debug(f"  Direction: {direction}")
                logger.debug(f"  Destination: {destination}")
                logger.debug(f"  Stops: {stops}")

                # Add coordinates to stops
                for stop in stops:
                    stop_id = stop["id"]
                    # Try with and without F/G suffix
                    base_id = stop_id.rstrip("FG")
                    if base_id in stops_data:
                        stop["coordinates"] = stops_data[base_id]["coordinates"]
                        stop["name"] = stops_data[base_id].get(
                            "name", stop_id
                        )  # Use stop ID as fallback name
                    elif stop_id in stops_data:
                        stop["coordinates"] = stops_data[stop_id]["coordinates"]
                        stop["name"] = stops_data[stop_id].get(
                            "name", stop_id
                        )  # Use stop ID as fallback name
                    else:
                        logger.warning(f"No coordinates found for stop {stop_id}")
                        stop["coordinates"] = {"lat": None, "lon": None}
                        stop["name"] = stop_id  # Use stop ID as name if not found

                # Get shape data for this variant
                shape = load_route_shape(line, direction)

                # Create a variant for this direction
                variants.append(
                    RouteVariant(
                        line=line,
                        direction=direction,  # Use City/Suburb directly
                        destination=destination,
                        stops=stops,
                        shape=shape,
                    )
                )
                logger.debug(f"Added variant for direction {direction}")

            except Exception as e:
                logger.error(f"Error processing variant for line {line}: {e}")
                continue

        logger.debug(f"Returning {len(variants)} variants for line {line}")
        return variants

    except Exception as e:
        logger.error(f"Error validating stops for line {line}: {e}")
        return []


def load_json_file(file_path: str) -> Dict:
    """Load a JSON file and return its contents as a dictionary"""
    with open(file_path, "r") as f:
        if data := json.load(f):
            return data
        else:
            logger.warning(f"Cache file {file_path} is empty")
            return {}


def load_route_shape(line: str, direction: str = None) -> List[List[float]]:
    """
    Load shape coordinates for a route line.
    Returns list of [lon, lat] coordinates for the specified direction.
    """
    try:
        shape_file = f"cache/shapes/line_{line}.json"

        if not Path(shape_file).exists():
            logger.error(f"Shape file {shape_file} not found")
            return []

        shape_data = load_json_file(shape_file)
        if not shape_data or "variants" not in shape_data:
            logger.error(f"No valid shape data found for line {line}")
            return []

        # Find the correct variant based on direction
        variants = shape_data["variants"]
        variant = None

        if direction:
            # Variant 1 is City, Variant 2 is Suburb
            variant = next(
                (
                    v
                    for v in variants
                    if (v["variante"] == 1 and direction == "City")
                    or (v["variante"] == 2 and direction == "Suburb")
                ),
                None,
            )
        else:
            # If no direction specified, use the first variant
            variant = variants[0] if variants else None

        if not variant:
            logger.error(
                f"No matching variant found for line {line} direction {direction}"
            )
            return []

        coordinates = variant.get("coordinates", [])
        if not coordinates:
            logger.error(f"No coordinates found in shape data for line {line}")
            return []

        logger.debug(
            f"Loaded {len(coordinates)} coordinates for line {line} direction {direction}"
        )
        return coordinates

    except Exception as e:
        logger.error(f"Error loading shape for line {line}: {str(e)}")
        import traceback

        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return []


def point_to_line_distance(
    point: Tuple[float, float],
    line_start: Tuple[float, float],
    line_end: Tuple[float, float],
) -> float:
    """Calculate the shortest distance from a point to a line segment"""
    # Convert to x,y coordinates (simplified, assuming small distances)
    px, py = point[1], point[0]  # lon, lat
    x1, y1 = line_start[1], line_start[0]
    x2, y2 = line_end[1], line_end[0]

    # Calculate line segment length squared
    line_length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2

    if line_length_sq == 0:
        # Line segment is actually a point
        return sqrt((px - x1) ** 2 + (py - y1) ** 2)

    # Calculate projection point parameter
    t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_length_sq))

    # Calculate closest point on line segment
    proj_x = x1 + t * (x2 - x1)
    proj_y = y1 + t * (y2 - y1)

    # Calculate distance
    return sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


def validate_stops_on_route(
    variant: RouteVariant, shape_coords: List[List[float]], max_distance: float = 0.001
) -> List[Dict]:
    """
    Validate that stops are near the route line
    max_distance is in degrees (approximately 111m per 0.001 degrees at the equator)
    """
    issues = []

    # For each stop
    for stop in variant.stops:
        min_distance = float("inf")
        stop_coords = (stop.coordinates[0], stop.coordinates[1])

        # Check distance to each line segment
        for i in range(len(shape_coords) - 1):
            start_point = shape_coords[i]
            end_point = shape_coords[i + 1]

            distance = point_to_line_distance(
                stop_coords,
                (start_point[1], start_point[0]),  # lat, lon
                (end_point[1], end_point[0]),
            )

            min_distance = min(min_distance, distance)

        if min_distance > max_distance:
            issues.append(
                {
                    "stop_id": stop.id,
                    "stop_name": stop.name,
                    "distance": min_distance * 111000,  # Convert to approximate meters
                    "coordinates": stop_coords,
                }
            )

    return issues


async def validate_line(line: str):
    """Validate all stops for a line against its route shapes"""
    variants = await validate_line_stops(line)
    shapes = load_route_shape(line)

    for variant in variants:
        # Match variant with shape (variant 2 = City, variant 1 = Suburb)
        shape_variant = next(
            (
                s
                for s in shapes
                if (s["variante"] == 2 and variant.direction == "City")
                or (s["variante"] == 1 and variant.direction == "Suburb")
            ),
            None,
        )

        if not shape_variant:
            logger.error(f"No matching shape found for line {line} {variant.direction}")
            continue

        issues = validate_stops_on_route(variant, shape_variant["coordinates"])

        if issues:
            logger.warning(
                f"\nLine {line} {variant.direction} has stops far from route:"
            )
            for issue in issues:
                logger.warning(
                    f"  {issue['stop_name']} (ID: {issue['stop_id']}) "
                    f"is {issue['distance']:.0f}m from route"
                )
        else:
            logger.debug(f"\nLine {line} {variant.direction}: All stops are on route")


def get_terminus_stops(line: str) -> Dict[str, Dict]:
    """
    Get terminus stop IDs for each direction of a line.
    Returns a dict mapping terminus stop IDs to their direction and destination info
    """
    variants = validate_line_stops(line)
    terminus_map = {}

    for variant in variants:
        if not variant.stops:
            logger.error(f"No stops found for line {line} {variant.direction}")
            continue

        # Get both first and last stops of route
        first_stop = variant.stops[0]
        last_stop = variant.stops[-1]

        # Add both terminus stops to the map with all necessary info as a dictionary
        terminus_map[first_stop.id] = {
            "stop_id": first_stop.id,
            "stop_name": first_stop.name,
            "direction": variant.direction,
            "destination": variant.destination,
        }

        terminus_map[last_stop.id] = {
            "stop_id": last_stop.id,
            "stop_name": last_stop.name,
            "direction": variant.direction,
            "destination": variant.destination,
        }

        logger.debug(f"\nLine {line} {variant.direction}:")
        logger.debug(f"  Start terminus: {first_stop.name} (ID: {first_stop.id})")
        logger.debug(f"  End terminus: {last_stop.name} (ID: {last_stop.id})")
        logger.debug(
            f"  Heading to: {variant.destination['fr']} / {variant.destination['nl']}"
        )

    return terminus_map


if __name__ == "__main__":
    # Test with lines 56 and 59
    for line in ["56", "59", "64"]:
        logger.info(f"\n=== Validating line {line} ===")
        validate_line(line)

    # Test with all lines
    all_terminus = {}
    for line in ["56", "59", "64"]:
        logger.info(f"\n=== Analyzing terminus stops for line {line} ===")
        terminus_stops = get_terminus_stops(line)
        all_terminus[line] = terminus_stops

    # Print summary
    logger.info("\n=== Terminus Summary ===")
    for line, terminus_data in all_terminus.items():
        logger.info(f"\nLine {line}:")
        for terminus_id, terminus in terminus_data.items():
            logger.info(f"  {terminus['stop_id']} ({terminus['stop_name']})")
            logger.info(f"    Direction: {terminus['direction']}")
            logger.info(f"    Destination: {terminus['destination']['fr']}")
