from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import json
import logging
import math
from math import sqrt, sin, cos, radians, asin, degrees

from app.transit_providers.be.stib.validate_stops import (
    validate_line_stops,
    load_route_shape,
    RouteVariant,
    Terminus,
    Stop,
)


# Get logger
logger = logging.getLogger("stib.locate_vehicles")


@dataclass
class VehiclePosition:
    line: str
    direction: str
    current_segment: List[str]
    distance_to_next: float
    segment_length: float
    is_valid: bool = True
    interpolated_position: Optional[Tuple[float, float]] = None
    bearing: float = 0
    shape_segment: Optional[List[List[float]]] = None
    raw_data: Optional[Dict] = None

    def to_dict(self):
        """Convert the VehiclePosition object to a dictionary for JSON serialization"""
        return {
            "line": self.line,
            "direction": self.direction,
            "current_segment": self.current_segment,
            "distance_to_next": self.distance_to_next,
            "segment_length": self.segment_length,
            "is_valid": self.is_valid,
            "interpolated_position": self.interpolated_position,
            "bearing": self.bearing,
        }

    def __json__(self):
        return self.to_dict()


def haversine_distance(
    point1: Tuple[float, float], point2: Tuple[float, float]
) -> float:
    """
    Calculate the distance between two points on Earth using the Haversine formula.
    Points are (lat, lon) tuples.
    Returns distance in meters.
    """
    # Validate inputs
    if not all(isinstance(x, (int, float)) for x in point1 + point2):
        raise ValueError(f"Invalid coordinates: point1={point1}, point2={point2}")

    lat1, lon1 = point1
    lat2, lon2 = point2

    R = 6371000  # Earth's radius in meters

    # Convert to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))

    return R * c


def calculate_segment_distance(
    shape_coords: List[List[float]], start_idx: int, end_idx: int
) -> float:
    """
    Calculate the total distance along a shape between two points.
    """
    total_distance = 0
    for i in range(start_idx, end_idx):
        point1 = (shape_coords[i][1], shape_coords[i][0])  # lat, lon
        point2 = (shape_coords[i + 1][1], shape_coords[i + 1][0])  # lat, lon
        total_distance += haversine_distance(point1, point2)
    return total_distance


def find_stop_in_shape(
    stop_coords: Tuple[float, float],
    shape_coords: List[List[float]],
    max_distance: float = 50,
) -> Optional[int]:
    """
    Find the closest point in the shape to a stop.
    Returns the index in shape_coords or None if no close match found.
    stop_coords is (lat, lon)
    shape_coords is list of [lon, lat] pairs
    """
    min_distance = float("inf")
    best_idx = None

    # Validate stop coordinates
    if not stop_coords or len(stop_coords) != 2:
        logger.error(f"Invalid stop coordinates: {stop_coords}")
        return None

    for i, coord in enumerate(shape_coords):
        try:
            # Validate shape coordinates
            if (
                not coord
                or len(coord) != 2
                or not all(isinstance(x, (int, float)) for x in coord)
            ):
                logger.error(f"Invalid shape coordinate at index {i}: {coord}")
                continue

            # Shape coordinates are [lon, lat], need to swap for comparison
            shape_point = (coord[1], coord[0])  # Convert to (lat, lon)

            try:
                dist = haversine_distance(stop_coords, shape_point)
                if dist < min_distance:
                    min_distance = dist
                    best_idx = i
            except ValueError as e:
                logger.error(f"Distance calculation failed at index {i}: {e}")
                continue

        except (IndexError, TypeError) as e:
            logger.error(f"Invalid coordinate at index {i}: {coord}")
            logger.error(f"Error: {str(e)}")
            continue

    if min_distance <= max_distance:
        return best_idx
    return None


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the bearing between two points in degrees"""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlon = lon2 - lon1
    y = sin(dlon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    bearing = degrees(math.atan2(y, x))

    # Convert to 0-360 range
    return (bearing + 360) % 360


def validate_segment(
    from_stop: Stop,
    to_stop: Stop,
    line: str,
    direction: str,
    distance_to_next: float,
    route_variant: RouteVariant,
    raw_data: Dict,
    **kwargs,
) -> Optional[VehiclePosition]:
    """
    Validate a vehicle's position and calculate segment details.
    """
    try:
        # Load shape coordinates for this specific direction
        shape_coords = load_route_shape(line, direction)
        if not shape_coords:
            logger.error(
                f"No shape coordinates found for line {line} direction {direction}"
            )
            return None

        # Validate stop coordinates exist and have the expected structure
        if (
            not from_stop.get("coordinates")
            or not isinstance(from_stop["coordinates"], dict)
            or not to_stop.get("coordinates")
            or not isinstance(to_stop["coordinates"], dict)
        ):
            logger.error(
                f"Missing coordinates for stops: from={from_stop.get('id')}, to={to_stop.get('id')}"
            )
            return None

        # Validate lat/lon values exist
        from_lat = from_stop["coordinates"].get("lat")
        from_lon = from_stop["coordinates"].get("lon")
        to_lat = to_stop["coordinates"].get("lat")
        to_lon = to_stop["coordinates"].get("lon")

        if any(coord is None for coord in [from_lat, from_lon, to_lat, to_lon]):
            logger.error(
                f"Line {line}: Missing lat/lon values for stops {from_stop['id']} -> {to_stop['id']}: from=({from_lat}, {from_lon}), to=({to_lat}, {to_lon})"
            )
            return None

        # Create coordinate tuples only after validation
        from_coords = (from_lat, from_lon)
        to_coords = (to_lat, to_lon)

        # Find stops in shape
        from_idx = find_stop_in_shape(from_coords, shape_coords)
        to_idx = find_stop_in_shape(to_coords, shape_coords)

        if from_idx is None or to_idx is None:
            logger.error(
                f"Could not locate stops in shape: {from_stop.get('id')} ({from_stop.get('name', 'Unknown')}) or {to_stop.get('id')} ({to_stop.get('name', 'Unknown')})"
            )
            return None

        # Ensure correct order
        if from_idx > to_idx:
            from_idx, to_idx = to_idx, from_idx

        # Calculate total segment distance
        segment_length = calculate_segment_distance(shape_coords, from_idx, to_idx)

        # Extract shape segment
        shape_segment = shape_coords[from_idx : to_idx + 1]

        # Validate reported distance with 20% tolerance
        tolerance = 1.2  # Allow reported distance to be up to 20% longer
        is_valid = distance_to_next <= segment_length * tolerance

        if not is_valid:
            logger.warning(
                f"Reported distance ({distance_to_next:.0f}m) is significantly greater than "
                f"segment length ({segment_length:.0f}m) between "
                f"{from_stop.get('id')} ({from_stop.get('name', 'Unknown')}) and {to_stop.get('id')} ({to_stop.get('name', 'Unknown')})"
            )

        # Create vehicle position object
        position = VehiclePosition(
            line=line,
            direction=direction,
            current_segment=(from_stop["id"], to_stop["id"]),
            distance_to_next=min(distance_to_next, segment_length),  # Cap the distance
            segment_length=segment_length,
            is_valid=is_valid,
            shape_segment=shape_segment,
            raw_data=raw_data,
        )

        # Calculate interpolated position and bearing
        interpolated = interpolate_position(position)
        if interpolated:
            position.interpolated_position = interpolated
            # Calculate bearing from interpolated position to next point in shape
            next_point = (
                shape_segment[1] if len(shape_segment) > 1 else shape_segment[0]
            )
            position.bearing = calculate_bearing(
                interpolated[0],
                interpolated[1],  # lat, lon of interpolated position
                next_point[1],
                next_point[0],  # lat, lon of next point (swapped from [lon, lat])
            )

        return position

    except Exception as e:
        import traceback

        logger.error(f"Error validating segment: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        logger.error(f"Input data:")
        logger.error(
            f"  From stop: {from_stop.get('id')} ({from_stop.get('name', 'Unknown')}) at {from_stop.get('coordinates')}"
        )
        logger.error(
            f"  To stop: {to_stop.get('id')} ({to_stop.get('name', 'Unknown')}) at {to_stop.get('coordinates')}"
        )
        logger.error(f"  Distance to next: {distance_to_next}m")
        logger.error(f"  Line: {line}, Direction: {direction}")
        logger.error(f"  Shape coords length: {len(shape_coords)}")
        logger.error(
            f"  Found indices: from_idx={from_idx if 'from_idx' in locals() else 'N/A'}, to_idx={to_idx if 'to_idx' in locals() else 'N/A'}"
        )
        logger.error(f"  Raw vehicle data: {raw_data}")
        return None


def find_vehicle_segment(
    vehicle_data: Dict,
    route_variant: RouteVariant,
    shape_coords: List[List[float]],
    line: str,
    direction: str,
) -> Optional[VehiclePosition]:
    """
    Find which segment a vehicle is on and validate its position
    """
    next_stop_id = vehicle_data["next_stop"]
    distance = vehicle_data["distance"]

    try:
        next_stop_index = next(
            i for i, stop in enumerate(route_variant.stops) if stop.id == next_stop_id
        )

        # The previous stop is where the vehicle is coming from
        if next_stop_index > 0:
            from_stop = route_variant.stops[next_stop_index - 1]
            to_stop = route_variant.stops[next_stop_index]

            return validate_segment(
                from_stop=from_stop,
                to_stop=to_stop,
                line=line,
                direction=direction,
                distance_to_next=distance,
                route_variant=route_variant,
                raw_data=vehicle_data,
            )
        else:
            logger.warning(
                f"Vehicle reporting next stop {next_stop_id} which is first stop in route"
            )
            return None

    except StopIteration:
        logger.error(f"Next stop {next_stop_id} not found in route stop list")
        return None


async def get_terminus_stops(line: str) -> Dict[str, Terminus]:
    """
    Get terminus stop IDs for each direction of a line, including alternative IDs
    """
    variants = await validate_line_stops(line)
    terminus_map = {}

    # First, get the known terminus stops
    for variant in variants:
        if not variant.stops:
            continue

        terminus = variant.stops[-1]
        terminus_map[terminus["id"]] = Terminus(
            stop_id=terminus["id"],
            stop_name=terminus["name"],
            direction=variant.direction,
            destination=variant.destination,
        )
        logger.debug(f"\nLine {line} {variant.direction}:")
        logger.debug(f"  Terminus: {terminus['name']} (ID: {terminus['id']})")
        logger.debug(f"  Heading to: {variant.destination['fr']}")

    return terminus_map


async def process_vehicle_positions(positions_data):
    """Process vehicle positions data into VehiclePosition objects"""
    vehicle_positions = []

    for line_id, directions in positions_data.items():
        # Get route variants for this line
        variants = await validate_line_stops(line_id)
        logger.debug(f"Got {len(variants)} route variants for line {line_id}")
        if not variants:
            logger.error(f"No route variants found for line {line_id}")
            continue

        # Create a mapping of stop IDs to directions
        stop_to_direction = {}
        direction_to_stops = {}
        for variant in variants:
            direction = (
                variant.direction
                if hasattr(variant, "direction")
                else variant["direction"]
            )
            stops = variant.stops if hasattr(variant, "stops") else variant["stops"]
            logger.debug(
                f"Processing variant with direction {direction} and {len(stops)} stops"
            )
            direction_to_stops[direction] = set()
            for stop in stops:
                stop_id = stop["id"] if isinstance(stop, dict) else stop.id
                # Remove F/G suffixes for matching
                stop_id = stop_id.rstrip("FG")
                stop_to_direction[stop_id] = direction
                direction_to_stops[direction].add(stop_id)

        logger.debug(f"Stop to direction mapping: {stop_to_direction}")
        logger.debug(f"Direction to stops mapping: {direction_to_stops}")

        # Process each direction's vehicles
        for direction_id, vehicles_list in directions.items():
            # Find the route variant for this direction
            variant = next(
                (
                    v
                    for v in variants
                    if (hasattr(v, "direction") and v.direction == direction_id)
                    or (isinstance(v, dict) and v["direction"] == direction_id)
                ),
                None,
            )
            if not variant:
                logger.error(
                    f"No route variant found for line {line_id} direction {direction_id}"
                )
                continue

            # Get stops list, handling both object and dict formats
            stops = variant.stops if hasattr(variant, "stops") else variant["stops"]

            # Process each vehicle
            for vehicle_data in vehicles_list:
                try:
                    next_stop = vehicle_data["next_stop"].rstrip("FG")

                    # Find the stop in the variant's stop list
                    stop_index = next(
                        (
                            i
                            for i, stop in enumerate(stops)
                            if (
                                isinstance(stop, dict)
                                and stop["id"].rstrip("FG") == next_stop
                            )
                            or (
                                hasattr(stop, "id")
                                and stop.id.rstrip("FG") == next_stop
                            )
                        ),
                        None,
                    )
                    if stop_index is None:
                        logger.error(
                            f"Stop {next_stop} not found in variant for line {line_id}"
                        )
                        continue

                    # Get the next stop in the sequence
                    if stop_index + 1 < len(stops):
                        next_stop_obj = stops[stop_index + 1]
                        next_stop_id = (
                            next_stop_obj["id"]
                            if isinstance(next_stop_obj, dict)
                            else next_stop_obj.id
                        )
                        current_segment = [next_stop, next_stop_id]

                        # Create VehiclePosition object
                        position = VehiclePosition(
                            line=line_id,
                            direction=direction_id,
                            current_segment=current_segment,
                            distance_to_next=vehicle_data["distance"],
                            segment_length=None,  # Will be calculated later if needed
                            is_valid=True,
                            interpolated_position=None,  # Will be calculated later
                            bearing=None,  # Will be calculated later
                            shape_segment=None,  # Will be calculated later
                            raw_data=vehicle_data,
                        )
                        vehicle_positions.append(position)
                    else:
                        logger.warning(
                            f"Vehicle at terminal stop {next_stop} on line {line_id}"
                        )

                except Exception as e:
                    logger.error(f"Error processing vehicle on line {line_id}: {e}")
                    continue

    return vehicle_positions


def interpolate_position(vehicle: VehiclePosition) -> Optional[Tuple[float, float]]:
    """
    Calculate the vehicle's position along its segment.
    Returns (lat, lon) or None if invalid.
    """
    if not vehicle.is_valid or not vehicle.shape_segment:
        return None

    # Distance from start of segment
    distance_from_start = vehicle.segment_length - vehicle.distance_to_next

    # Walk along shape until we find our position
    current_distance = 0
    for i in range(len(vehicle.shape_segment) - 1):
        point1 = (vehicle.shape_segment[i][1], vehicle.shape_segment[i][0])  # lat, lon
        point2 = (
            vehicle.shape_segment[i + 1][1],
            vehicle.shape_segment[i + 1][0],
        )  # lat, lon

        segment_distance = haversine_distance(point1, point2)
        next_distance = current_distance + segment_distance

        if next_distance >= distance_from_start:
            # Our position is on this mini-segment
            fraction = (distance_from_start - current_distance) / segment_distance

            # Linear interpolation
            lat = point1[0] + fraction * (point2[0] - point1[0])
            lon = point1[1] + fraction * (point2[1] - point1[1])

            # Calculate bearing
            vehicle.bearing = calculate_bearing(lat, lon, point2[0], point2[1])

            return (lat, lon)

        current_distance = next_distance

    # If we get here, we're at the end of the segment
    last_point = vehicle.shape_segment[-1]
    return (last_point[1], last_point[0])  # Return last point instead of None


if __name__ == "__main__":
    # Example vehicle positions data
    example_positions = {
        "56": {
            "2378": [
                {"distance": 32, "next_stop": "6190"},
                {"distance": 70, "next_stop": "1062"},
            ],
            "6465": [
                {"distance": 0, "next_stop": "3080"},
                {"distance": 0, "next_stop": "6461"},
                {"distance": 0, "next_stop": "2379"},
                {"distance": 0, "next_stop": "2379"},
            ],
        },
        "59": {
            "3125": [
                {"distance": 358, "next_stop": "3099"},
                {"distance": 40, "next_stop": "6465"},
            ],
            "3130": [
                {"distance": 0, "next_stop": "3172"},
                {"distance": 359, "next_stop": "3155"},
                {"distance": 52, "next_stop": "9296"},
                {"distance": 0, "next_stop": "3125"},
            ],
        },
        "64": {
            "3134": [
                {"distance": 75, "next_stop": "3185"},
                {"distance": 6, "next_stop": "5299"},
                {"distance": 258, "next_stop": "1729"},
            ],
            "4952": [
                {"distance": 50, "next_stop": "1162"},
                {"distance": 49, "next_stop": "2915"},
            ],
        },
    }

    vehicles = process_vehicle_positions(example_positions)

    logger.info("\n=== Vehicle Positions ===")
    for vehicle in vehicles:
        logger.info(f"\nLine {vehicle.line} ({vehicle.direction})")
        logger.info(
            f"  Between stops: {vehicle.current_segment[0]} → {vehicle.current_segment[1]}"
        )
        logger.info(f"  Distance to next stop: {vehicle.distance_to_next}m")
        logger.info(f"  Segment length: {vehicle.segment_length:.0f}m")
        logger.info(f"  Valid position: {vehicle.is_valid}")

        if vehicle.is_valid:
            position = interpolate_position(vehicle)
            if position:
                logger.info(f"  Position: {position[0]:.6f}, {position[1]:.6f}")
