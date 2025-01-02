from typing import Dict, List, Optional, Set
import csv
from pathlib import Path
import logging
from collections import defaultdict

logger = logging.getLogger("bkk")


def assign_variant_numbers(
    shapes: Dict[str, List[Dict]], monitored_stops: List[Dict[str, float]]
) -> Dict[str, int]:
    """
    Assigns variant numbers to shapes based on monitored stops and shape length.

    Args:
        shapes: Dictionary mapping shape_ids to list of coordinate points
        monitored_stops: List of dictionaries with 'lat' and 'lon' keys for monitored stops

    Returns:
        Dictionary mapping shape_ids to variant numbers (1-based)
    """

    def point_matches_stop(
        point: List[float], stop: Dict[str, float], threshold: float = 0.0001
    ) -> bool:
        """Check if a point matches a stop location within threshold"""
        return (
            abs(point[1] - stop["lat"]) < threshold
            and abs(point[0] - stop["lon"]) < threshold
        )

    # Calculate matches and length for each shape
    shape_metrics = {}
    for shape_id, points in shapes.items():
        # Count matches with monitored stops
        matches = 0
        for stop in monitored_stops:
            for point in points:
                if point_matches_stop(point, stop):
                    matches += 1
                    break  # Count each stop only once per shape

        shape_metrics[shape_id] = {
            "matches": matches,
            "length": len(points),
            "shape_id": shape_id,
        }

    # Sort shapes by:
    # 1. Number of monitored stop matches (descending)
    # 2. Shape length (descending)
    # 3. Shape ID (ascending) for stable sorting
    sorted_shapes = sorted(
        shape_metrics.values(),
        key=lambda x: (-x["matches"], -x["length"], x["shape_id"]),
    )

    # Assign variant numbers (1-based)
    return {shape["shape_id"]: idx + 1 for idx, shape in enumerate(sorted_shapes)}


def load_shapes_from_gtfs(
    gtfs_dir: Path, route_id: str
) -> Dict[str, List[List[float]]]:
    """
    Load shapes for a route from GTFS data.

    Args:
        gtfs_dir: Path to GTFS directory
        route_id: Route ID to load shapes for

    Returns:
        Dictionary mapping shape_ids to list of [lon, lat] coordinates
    """
    # First get shape IDs for this route from trips.txt
    shape_ids = get_shape_ids_for_route(gtfs_dir, route_id)
    if not shape_ids:
        logger.warning(f"No shape IDs found for route {route_id}")
        return {}

    # Then load the actual shapes from shapes.txt
    shapes_file = gtfs_dir / "shapes.txt"
    if not shapes_file.exists():
        logger.error(f"shapes.txt not found in {gtfs_dir}")
        return {}

    # Read all shape points and sort by sequence
    shape_points = defaultdict(list)
    try:
        with open(shapes_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                shape_id = row["shape_id"]
                if shape_id in shape_ids:
                    shape_points[shape_id].append(
                        {
                            "lat": float(row["shape_pt_lat"]),
                            "lon": float(row["shape_pt_lon"]),
                            "sequence": int(row["shape_pt_sequence"]),
                        }
                    )
    except Exception as e:
        logger.error(f"Error reading shapes.txt: {e}")
        return {}

    # Sort points by sequence and convert to coordinate list
    shapes = {}
    for shape_id, points in shape_points.items():
        sorted_points = sorted(points, key=lambda x: x["sequence"])
        shapes[shape_id] = [[p["lon"], p["lat"]] for p in sorted_points]

    return shapes


def get_shape_ids_for_route(gtfs_dir: Path, route_id: str) -> Set[str]:
    """
    Get all shape IDs used by a route from trips.txt

    Args:
        gtfs_dir: Path to GTFS directory
        route_id: Route ID to get shapes for

    Returns:
        Set of shape IDs used by the route
    """
    trips_file = gtfs_dir / "trips.txt"
    if not trips_file.exists():
        logger.error(f"trips.txt not found in {gtfs_dir}")
        return set()

    shape_ids = set()
    try:
        with open(trips_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["route_id"] == route_id:
                    shape_ids.add(row["shape_id"])
    except Exception as e:
        logger.error(f"Error reading trips.txt: {e}")
        return set()

    return shape_ids


def get_route_variants(
    route_id: str, monitored_stops: List[Dict[str, float]], gtfs_dir: Path
) -> Dict:
    """
    Get variants for a route with their assigned numbers.

    Args:
        route_id: The route ID to get variants for
        monitored_stops: List of dictionaries with 'lat' and 'lon' keys for monitored stops
        gtfs_dir: Path to GTFS directory

    Returns:
        Dictionary containing:
        - variants: Dictionary mapping variant numbers to shape points
        - shape_to_variant: Dictionary mapping shape_ids to variant numbers
    """
    # Load shapes from GTFS
    shapes = load_shapes_from_gtfs(gtfs_dir, route_id)
    if not shapes:
        logger.warning(f"No shapes found for route {route_id}")
        return {"variants": {}, "shape_to_variant": {}}

    # Assign variant numbers
    shape_to_variant = assign_variant_numbers(shapes, monitored_stops)

    # Create the variants dictionary
    variants = {
        variant_num: shapes[shape_id]
        for shape_id, variant_num in shape_to_variant.items()
    }

    return {"variants": variants, "shape_to_variant": shape_to_variant}
