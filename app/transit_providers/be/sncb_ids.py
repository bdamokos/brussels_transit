"""SNCB/NMBS identifier normalization helpers."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

SNCB_ID_PREFIXES = (
    "gt:nmbssncb:",
    "gs:nmbssncb:",
    "gr:nmbssncb:",
    "gc:nmbssncb:",
    "nmbssncb:",
)

GTFS_ID_COLUMNS = {
    "agency.txt": {"agency_id"},
    "calendar.txt": {"service_id"},
    "calendar_dates.txt": {"service_id"},
    "routes.txt": {"agency_id", "route_id"},
    "stop_times.txt": {"stop_id", "trip_id"},
    "stops.txt": {"parent_station", "stop_id"},
    "transfers.txt": {
        "from_route_id",
        "from_stop_id",
        "from_trip_id",
        "to_route_id",
        "to_stop_id",
        "to_trip_id",
    },
    "trips.txt": {"block_id", "route_id", "service_id", "shape_id", "trip_id"},
}


def strip_sncb_id_prefix(value: str) -> str:
    """Strip Belgian Mobility SNCB prefixes while leaving legacy IDs unchanged."""
    for prefix in SNCB_ID_PREFIXES:
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def normalize_sncb_stop_id(value: str, collapse_platform: bool = False) -> str:
    """Normalize an SNCB stop ID, optionally collapsing platform IDs to station IDs."""
    out = strip_sncb_id_prefix(value)
    if collapse_platform and "_" in out:
        return out.split("_", 1)[0]
    return out


def unwrap_gtfs_json_ints(value: Any) -> Any:
    """Convert protobufjs-style Long JSON objects into Python integers."""
    if isinstance(value, dict):
        if "low" in value and "high" in value:
            low = int(value.get("low") or 0)
            high = int(value.get("high") or 0)
            return (high << 32) + (low & 0xFFFFFFFF)
        return {key: unwrap_gtfs_json_ints(val) for key, val in value.items()}
    if isinstance(value, list):
        return [unwrap_gtfs_json_ints(item) for item in value]
    return value


def normalize_static_gtfs_dir(gtfs_dir: Path) -> None:
    """Normalize Belgian Mobility GTFS IDs in-place to this provider's legacy ID shape."""
    for filename, columns in GTFS_ID_COLUMNS.items():
        path = gtfs_dir / filename
        if path.exists():
            _normalize_static_gtfs_file(path, columns)


def _normalize_static_gtfs_file(path: Path, columns: set[str]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with path.open("r", encoding="utf-8", newline="") as in_file:
        reader = csv.DictReader(in_file)
        if not reader.fieldnames:
            return

        try:
            with tmp_path.open("w", encoding="utf-8", newline="") as out_file:
                writer = csv.DictWriter(out_file, fieldnames=reader.fieldnames)
                writer.writeheader()
                for row in reader:
                    for column in columns:
                        if row.get(column):
                            row[column] = strip_sncb_id_prefix(row[column])
                    writer.writerow(row)
            tmp_path.replace(path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
