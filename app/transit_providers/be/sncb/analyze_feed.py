"""Script to analyze GTFS-RT feed and match with static GTFS data"""

"""Save the feed as /tmp/tripUpdates.pb in the project root and then run this script"""
import os
from pathlib import Path
from protos.gtfs_realtime_pb2 import FeedMessage
import csv
import re
from typing import Dict, List, Set

# Set up paths
PROJECT_ROOT = Path(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    )
)
GTFS_DIR = (
    PROJECT_ROOT
    / "downloads/mdb-1859_Societe_nationale_des_chemins_de_fer_belges_NMBS_SNCB/mdb-1859-202501020029"
)
FEED_PATH = Path("/tmp/tripUpdates.pb")

# Our monitored stop
MONITORED_STOP = "8812005"  # Bruxelles-Nord


def get_stop_name(stop_id: str) -> str:
    """Get stop name from GTFS stops.txt"""
    # Remove any suffix after underscore (e.g. 8814001_7 -> 8814001)
    base_stop_id = stop_id.split("_")[0]

    stops_file = GTFS_DIR / "stops.txt"
    with open(stops_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["stop_id"].split("_")[0] == base_stop_id:
                return row["stop_name"]
    return f"Unknown ({stop_id})"


def get_trip_pattern(trip_id: str) -> str:
    """Extract the base pattern from a trip ID.

    Examples:
    88____:007::8891702:8844503:51:2453:20251212 -> 88:007:8891702:8844503
    """
    parts = trip_id.split(":")
    if len(parts) >= 4:
        return f"{parts[0][:2]}:{parts[1]}:{parts[3]}:{parts[4]}"
    return trip_id


def get_trip_stops(trip_id: str) -> list:
    """Get all stops for a trip from GTFS stop_times.txt"""
    stops: Dict[str, dict] = {}  # Use dict for deduplication
    pattern = get_trip_pattern(trip_id)

    stop_times_file = GTFS_DIR / "stop_times.txt"
    with open(stop_times_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try to match trip patterns
            if get_trip_pattern(row["trip_id"]) == pattern:
                base_stop_id = row["stop_id"].split("_")[0]
                if base_stop_id not in stops:
                    stops[base_stop_id] = {
                        "stop_id": base_stop_id,
                        "stop_sequence": int(row["stop_sequence"]),
                        "stop_name": get_stop_name(base_stop_id),
                    }
    return sorted(list(stops.values()), key=lambda x: x["stop_sequence"])


def analyze_feed():
    """Analyze the GTFS-RT feed and match with static data"""
    # Read and parse feed
    feed = FeedMessage()
    with open(FEED_PATH, "rb") as f:
        feed.ParseFromString(f.read())

    print(f"Feed timestamp: {feed.header.timestamp}")
    print(f"Number of entities: {len(feed.entity)}\n")

    # Keep track of trips containing our monitored stop
    monitored_trips = []

    # First pass: find trips containing our monitored stop
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue

        trip = entity.trip_update
        stop_ids = [stop.stop_id for stop in trip.stop_time_update]

        if MONITORED_STOP in stop_ids:
            monitored_trips.append(entity)

    print(
        f"Found {len(monitored_trips)} trips containing stop {MONITORED_STOP} ({get_stop_name(MONITORED_STOP)})"
    )

    # Analyze monitored trips
    for entity in monitored_trips:
        trip = entity.trip_update
        trip_id = trip.trip.trip_id
        print(f"\nAnalyzing trip: {trip_id}")
        print(f"Trip pattern: {get_trip_pattern(trip_id)}")

        # Get realtime stop sequence
        rt_stops = []
        for stop_time in trip.stop_time_update:
            rt_stops.append(
                {
                    "stop_id": stop_time.stop_id,
                    "stop_name": get_stop_name(stop_time.stop_id),
                    "arrival_time": (
                        stop_time.arrival.time
                        if stop_time.HasField("arrival")
                        else None
                    ),
                    "delay": (
                        stop_time.arrival.delay
                        if stop_time.HasField("arrival")
                        and stop_time.arrival.HasField("delay")
                        else None
                    ),
                }
            )

        print("\nRealtime stops:")
        for stop in rt_stops:
            delay_str = (
                f" (delay: {stop['delay']}s)" if stop["delay"] is not None else ""
            )
            print(f"  {stop['stop_name']} ({stop['stop_id']}){delay_str}")

        # Get static GTFS stops
        static_stops = get_trip_stops(trip_id)
        if static_stops:
            print("\nStatic GTFS stops:")
            for stop in static_stops:
                print(
                    f"  {stop['stop_name']} ({stop['stop_id']}) - sequence {stop['stop_sequence']}"
                )
        else:
            print("\nNo matching trip found in static GTFS data!")

        print("\n" + "=" * 80)


if __name__ == "__main__":
    analyze_feed()
