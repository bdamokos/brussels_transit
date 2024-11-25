from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import json
import logging
import os
import sys

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.validate_stops import validate_line_stops, load_route_shape, RouteVariant, Terminus, Stop
except ImportError:
    from validate_stops import validate_line_stops, load_route_shape, RouteVariant, Terminus, Stop

from math import sqrt, sin, cos, radians, asin, degrees
import math
from config import get_config
from logging.config import dictConfig

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('locate_vehicles')


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
            'line': self.line,
            'direction': self.direction,
            'current_segment': self.current_segment,
            'distance_to_next': self.distance_to_next,
            'segment_length': self.segment_length,
            'is_valid': self.is_valid,
            'interpolated_position': self.interpolated_position,
            'bearing': self.bearing
        }

    def __json__(self):
        return self.to_dict()


def haversine_distance(point1: Tuple[float, float], point2: Tuple[float, float]) -> float:
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
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    return R * c


def calculate_segment_distance(shape_coords: List[List[float]], 
                             start_idx: int, 
                             end_idx: int) -> float:
    """
    Calculate the total distance along a shape between two points.
    """
    total_distance = 0
    for i in range(start_idx, end_idx):
        point1 = (shape_coords[i][1], shape_coords[i][0])    # lat, lon
        point2 = (shape_coords[i+1][1], shape_coords[i+1][0])  # lat, lon
        total_distance += haversine_distance(point1, point2)
    return total_distance


def find_stop_in_shape(stop_coords: Tuple[float, float], 
                      shape_coords: List[List[float]], 
                      max_distance: float = 50) -> Optional[int]:
    """
    Find the closest point in the shape to a stop.
    Returns the index in shape_coords or None if no close match found.
    stop_coords is (lat, lon)
    shape_coords is list of [lon, lat] pairs
    """
    min_distance = float('inf')
    best_idx = None
    
    # Validate stop coordinates
    if not stop_coords or len(stop_coords) != 2:
        logger.error(f"Invalid stop coordinates: {stop_coords}")
        return None
        
    for i, coord in enumerate(shape_coords):
        try:
            # Validate shape coordinates
            if not coord or len(coord) != 2 or not all(isinstance(x, (int, float)) for x in coord):
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

def validate_segment(from_stop: Stop, 
                    to_stop: Stop, 
                    line: str,
                    direction: str,
                    distance_to_next: float,
                    route_variant: RouteVariant,
                    raw_data: Dict,
                    **kwargs) -> Optional[VehiclePosition]:
    """
    Validate a vehicle's position and calculate segment details.
    """
    try:
        # Load shape coordinates for this specific direction
        shape_coords = load_route_shape(line, direction)
        if not shape_coords:
            logger.error(f"No shape coordinates found for line {line} direction {direction}")
            return None

        # Validate stop coordinates exist and have the expected structure
        if (not from_stop.get('coordinates') or 
            not isinstance(from_stop['coordinates'], dict) or
            not to_stop.get('coordinates') or 
            not isinstance(to_stop['coordinates'], dict)):
            logger.error(f"Missing coordinates for stops: from={from_stop.get('name')}, to={to_stop.get('name')}")
            return None

        # Validate lat/lon values exist
        from_lat = from_stop['coordinates'].get('lat')
        from_lon = from_stop['coordinates'].get('lon')
        to_lat = to_stop['coordinates'].get('lat')
        to_lon = to_stop['coordinates'].get('lon')

        if any(coord is None for coord in [from_lat, from_lon, to_lat, to_lon]):
            logger.error(f"Line {line}: Missing lat/lon values for stops {from_stop['id']} -> {to_stop['id']}: from=({from_lat}, {from_lon}), to=({to_lat}, {to_lon})")
            return None

        # Create coordinate tuples only after validation
        from_coords = (from_lat, from_lon)
        to_coords = (to_lat, to_lon)
        
        # Find stops in shape
        from_idx = find_stop_in_shape(from_coords, shape_coords)
        to_idx = find_stop_in_shape(to_coords, shape_coords)
        
        if from_idx is None or to_idx is None:
            logger.error(f"Could not locate stops in shape: {from_stop['name']} or {to_stop['name']}")
            return None
        
        # Ensure correct order
        if from_idx > to_idx:
            from_idx, to_idx = to_idx, from_idx
        
        # Calculate total segment distance
        segment_length = calculate_segment_distance(shape_coords, from_idx, to_idx)
        
        # Extract shape segment
        shape_segment = shape_coords[from_idx:to_idx + 1]
        
        # Validate reported distance with 20% tolerance
        tolerance = 1.2  # Allow reported distance to be up to 20% longer
        is_valid = distance_to_next <= segment_length * tolerance
        
        if not is_valid:
            logger.warning(
                f"Reported distance ({distance_to_next:.0f}m) is significantly greater than "
                f"segment length ({segment_length:.0f}m) between "
                f"{from_stop['name']} and {to_stop['name']}"
            )
        
        return VehiclePosition(
            line=line,
            direction=direction,
            current_segment=(from_stop['id'], to_stop['id']),
            distance_to_next=min(distance_to_next, segment_length),  # Cap the distance
            segment_length=segment_length,
            shape_segment=shape_segment,
            raw_data=raw_data
        )
    except Exception as e:
        import traceback
        logger.error(f"Error validating segment: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        logger.error(f"Input data:")
        logger.error(f"  From stop: {from_stop['name']} (ID: {from_stop['id']}) at {from_stop['coordinates']}")
        logger.error(f"  To stop: {to_stop['name']} (ID: {to_stop['id']}) at {to_stop['coordinates']}")
        logger.error(f"  Distance to next: {distance_to_next}m")
        logger.error(f"  Line: {line}, Direction: {direction}")
        logger.error(f"  Shape coords length: {len(shape_coords)}")
        logger.error(f"  Found indices: from_idx={from_idx}, to_idx={to_idx}")
        logger.error(f"  Raw vehicle data: {raw_data}")
        return None


def find_vehicle_segment(vehicle_data: Dict, 
                        route_variant: RouteVariant,
                        shape_coords: List[List[float]],
                        line: str,
                        direction: str) -> Optional[VehiclePosition]:
    """
    Find which segment a vehicle is on and validate its position
    """
    next_stop_id = vehicle_data['next_stop']
    distance = vehicle_data['distance']
    
    try:
        next_stop_index = next(
            i for i, stop in enumerate(route_variant.stops)
            if stop.id == next_stop_id
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
                raw_data=vehicle_data
            )
        else:
            logger.warning(f"Vehicle reporting next stop {next_stop_id} which is first stop in route")
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
        terminus_map[terminus['id']] = Terminus(
            stop_id=terminus['id'],
            stop_name=terminus['name'],
            direction=variant.direction,
            destination=variant.destination
        )
        logger.debug(f"\nLine {line} {variant.direction}:")
        logger.debug(f"  Terminus: {terminus['name']} (ID: {terminus['id']})")
        logger.debug(f"  Heading to: {variant.destination['fr']}")
    
    return terminus_map


async def process_vehicle_positions(positions_data: Dict) -> List[VehiclePosition]:
    """Process raw vehicle positions data into Vehicle objects"""
    vehicles = []
    
    for line, directions in positions_data.items():
        try:
            # Get terminus data for this line
            terminus_data = await get_terminus_stops(line)
            logger.debug(f"\nLine {line}:")
            
            # Get route variants for this line
            route_variants = await validate_line_stops(line)
            if not route_variants:
                logger.error(f"No route variants found for line {line}")
                continue
                
            # Process each direction's vehicles
            for terminus_id, vehicles_list in directions.items():
                # Try to determine direction from terminus data
                terminus_info = terminus_data.get(terminus_id)
                direction = None
                
                if terminus_info:
                    logger.debug(f"  Terminus: {terminus_info.stop_name} (ID: {terminus_info.stop_id})")
                    logger.debug(f"  Heading to: {terminus_info.destination['fr']}")
                    direction = terminus_info.direction
                else:
                    # If terminus not found, try to determine direction from next stops
                    for vehicle_data in vehicles_list:
                        next_stop = vehicle_data['next_stop']
                        # First try with original stop ID
                        for variant in route_variants:
                            if any(stop['id'] == next_stop for stop in variant.stops):
                                direction = variant.direction
                                break
                                
                        # If not found, try with suffixes
                        if not direction:
                            for suffix in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
                                next_stop_with_suffix = f"{next_stop}{suffix}"
                                for variant in route_variants:
                                    if any(stop['id'] == next_stop_with_suffix for stop in variant.stops):
                                        direction = variant.direction
                                        break
                                if direction:
                                    break
                                    
                        if direction:
                            break
                    
                    if not direction:
                        logger.warning(f"Unknown direction for terminus. "
                                     f"Terminus ID: {terminus_id}. "
                                     f"Available terminus data: {terminus_data}. "
                                     f"Line {line} direction data: {directions}")
                        continue
                # Process vehicles for this direction
                for vehicle_data in vehicles_list:
                    next_stop_id = vehicle_data['next_stop']
                    
                    # Find the route variant containing this stop
                    route_variant = None
                    # Try finding route variant with original stop ID
                    for variant in route_variants:
                        if any(stop['id'] == next_stop_id for stop in variant.stops):
                            route_variant = variant
                            break
                            
                    # If not found, try with suffixes
                    if not route_variant:
                        suffixes = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
                        for suffix in suffixes:
                            stop_id_with_suffix = f"{next_stop_id}{suffix}"
                            for variant in route_variants:
                                if any(stop['id'] == stop_id_with_suffix for stop in variant.stops):
                                    route_variant = variant
                                    break
                            if route_variant:
                                break
                    
                    if not route_variant:
                        logger.error(f"No route variant found containing stop {next_stop_id} (or with suffixes) for line {line}")
                        continue
                        
                    try:
                        # Try original ID first
                        try:
                            next_stop_index = next(
                                i for i, stop in enumerate(route_variant.stops)
                                if stop['id'] == next_stop_id
                            )
                        except StopIteration:
                            # Try with suffixes
                            found = False
                            for suffix in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
                                try:
                                    next_stop_index = next(
                                        i for i, stop in enumerate(route_variant.stops)
                                        if stop['id'] == f"{next_stop_id}{suffix}"
                                    )
                                    found = True
                                    break
                                except StopIteration:
                                    continue
                            if not found:
                                raise StopIteration(f"Stop {next_stop_id} not found with any suffix")
                        
                        if next_stop_index > 0:
                            from_stop = route_variant.stops[next_stop_index - 1]
                            to_stop = route_variant.stops[next_stop_index]
                            
                            # Load shape coordinates
                            shape_coords = load_route_shape(line)
                            

                            # Create vehicle position
                            vehicle = validate_segment(
                                from_stop=from_stop,
                                to_stop=to_stop,
                                line=line,
                                direction=direction,
                                distance_to_next=vehicle_data['distance'],
                                route_variant=route_variant,
                                next_stop_coords=to_stop['coordinates'],
                                raw_data=vehicle_data
                            )
                            
                            if vehicle:
                                vehicles.append(vehicle)
                                
                    except StopIteration:
                        logger.error(f"Next stop {next_stop_id} not found in route stop list")
                        continue
                    except Exception as e:
                        logger.error(f"Error processing vehicle: {str(e)}")
                        continue
                    
        except Exception as e:
            logger.error(f"Error processing line {line}: {str(e)}")
            import traceback
            logger.error(f"Error processing line {line}: {traceback.format_exc()}")
            continue
            
    return vehicles


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
        point1 = (vehicle.shape_segment[i][1], vehicle.shape_segment[i][0])     # lat, lon
        point2 = (vehicle.shape_segment[i+1][1], vehicle.shape_segment[i+1][0]) # lat, lon
        
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


def calculate_bearing(lat1, lon1, lat2, lon2):
    """Calculate the bearing between two points."""
    # Convert to radians
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)
    
    # Calculate bearing
    d_lon = lon2 - lon1
    y = math.sin(d_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    bearing = math.degrees(math.atan2(y, x))
    
    # Normalize to 0-360
    return (bearing + 360) % 360

if __name__ == "__main__":
    # Example vehicle positions data
    example_positions = {"56": {"2378": [{"distance": 32, "next_stop": "6190"}, {"distance": 70, "next_stop": "1062"}], "6465": [{"distance": 0, "next_stop": "3080"}, {"distance": 0, "next_stop": "6461"}, {"distance": 0, "next_stop": "2379"}, {"distance": 0, "next_stop": "2379"}]}, "59": {"3125": [{"distance": 358, "next_stop": "3099"}, {"distance": 40, "next_stop": "6465"}], "3130": [{"distance": 0, "next_stop": "3172"}, {"distance": 359, "next_stop": "3155"}, {"distance": 52, "next_stop": "9296"}, {"distance": 0, "next_stop": "3125"}]}, "64": {"3134": [{"distance": 75, "next_stop": "3185"}, {"distance": 6, "next_stop": "5299"}, {"distance": 258, "next_stop": "1729"}], "4952": [{"distance": 50, "next_stop": "1162"}, {"distance": 49, "next_stop": "2915"}]}}
    
    vehicles = process_vehicle_positions(example_positions)
    
    logger.info("\n=== Vehicle Positions ===")
    for vehicle in vehicles:
        logger.info(f"\nLine {vehicle.line} ({vehicle.direction})")
        logger.info(f"  Between stops: {vehicle.current_segment[0]} → {vehicle.current_segment[1]}")
        logger.info(f"  Distance to next stop: {vehicle.distance_to_next}m")
        logger.info(f"  Segment length: {vehicle.segment_length:.0f}m")
        logger.info(f"  Valid position: {vehicle.is_valid}")
        
        if vehicle.is_valid:
            position = interpolate_position(vehicle)
            if position:
                logger.info(f"  Position: {position[0]:.6f}, {position[1]:.6f}")
