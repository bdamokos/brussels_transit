"""Le TEC Belgian Mobility APIM provider."""

import asyncio
import csv
import io
import json
import logging
import shutil
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union
from zoneinfo import ZoneInfo

import httpx
from google.protobuf import json_format

from transit_providers.be.mobility import mobility_subscription_headers
from google.transit import gtfs_realtime_pb2
from transit_providers.config import get_provider_config
from transit_providers.nearest_stop import (
    Stop,
    cache_stops,
    get_cached_stops,
    get_nearest_stops,
    get_stop_by_name as generic_get_stop_by_name,
    ingest_gtfs_stops,
)

logger = logging.getLogger("letec")

PROVIDER = "letec"
provider_config = get_provider_config(PROVIDER)

CACHE_DIR = Path(provider_config.get("CACHE_DIR"))
GTFS_STATIC_DIR = Path(provider_config.get("GTFS_STATIC_DIR"))
GTFS_STATIC_METADATA_FILE = Path(provider_config.get("GTFS_STATIC_METADATA_FILE"))
STOP_IDS = provider_config.get("STOP_IDS", [])
MONITORED_LINES = provider_config.get("MONITORED_LINES", [])
TRIP_UPDATES_URL = provider_config.get("TRIP_UPDATES_URL")
SERVICE_ALERTS_URL = provider_config.get("SERVICE_ALERTS_URL")

_stops_cache: Dict[str, Dict[str, Any]] = {}
_routes_cache: Dict[str, Dict[str, Any]] = {}
_trips_cache: Dict[str, Dict[str, Any]] = {}
_stop_times_cache: Dict[str, List[Dict[str, Any]]] = {}
_caches_initialized = False
_init_lock: Optional[asyncio.Lock] = None
_last_waiting_times_result: Optional[Dict[str, Any]] = None
_last_waiting_times_update: Optional[float] = None
_WAITING_TIMES_CACHE_DURATION = 2.0


def _cache_duration_seconds() -> int:
    duration = provider_config.get("GTFS_CACHE_DURATION", 86400)
    if isinstance(duration, timedelta):
        return int(duration.total_seconds())
    return int(duration)


def _required_gtfs_files() -> List[str]:
    return ["stops.txt", "routes.txt", "trips.txt", "stop_times.txt"]


def _gtfs_dir_has_required_files(path: Path) -> bool:
    return path.exists() and all(
        (path / filename).exists() for filename in _required_gtfs_files()
    )


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    dest_root = dest_dir.resolve()
    for member in zf.infolist():
        name = member.filename
        if not name or name.endswith("/"):
            continue
        target = (dest_root / name).resolve()
        try:
            target.relative_to(dest_root)
        except ValueError:
            logger.warning("Skipping ZIP entry outside GTFS dir: %s", name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member, "r") as src, open(target, "wb") as out_f:
            shutil.copyfileobj(src, out_f)


def _find_gtfs_root(path: Path) -> Path:
    if _gtfs_dir_has_required_files(path):
        return path
    for child in path.rglob("stops.txt"):
        candidate = child.parent
        if _gtfs_dir_has_required_files(candidate):
            return candidate
    return path


def _static_cache_is_valid() -> bool:
    if not _gtfs_dir_has_required_files(GTFS_STATIC_DIR):
        return False
    if not GTFS_STATIC_METADATA_FILE.exists():
        return False
    try:
        metadata = json.loads(GTFS_STATIC_METADATA_FILE.read_text(encoding="utf-8"))
        downloaded_at = datetime.fromisoformat(metadata["downloaded_at"])
        if downloaded_at.tzinfo is None:
            downloaded_at = downloaded_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Ignoring invalid Le TEC GTFS metadata: %s", exc)
        return False
    return (
        datetime.now(timezone.utc) - downloaded_at
    ).total_seconds() < _cache_duration_seconds()


async def _download_static_gtfs_from_url(
    client: httpx.AsyncClient,
    url: str,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Path]:
    tmp_dir = GTFS_STATIC_DIR.parent / f".{GTFS_STATIC_DIR.name}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        response = await client.get(url, headers=headers)
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content), "r") as zf:
            _safe_extract_zip(zf, tmp_dir)

        gtfs_root = _find_gtfs_root(tmp_dir)
        if not _gtfs_dir_has_required_files(gtfs_root):
            missing = [
                filename
                for filename in _required_gtfs_files()
                if not (gtfs_root / filename).exists()
            ]
            logger.error("Le TEC GTFS download missing files: %s", missing)
            shutil.rmtree(tmp_dir)
            return None

        if GTFS_STATIC_DIR.exists():
            shutil.rmtree(GTFS_STATIC_DIR)
        GTFS_STATIC_DIR.parent.mkdir(parents=True, exist_ok=True)
        if gtfs_root == tmp_dir:
            tmp_dir.rename(GTFS_STATIC_DIR)
        else:
            shutil.move(str(gtfs_root), str(GTFS_STATIC_DIR))
            shutil.rmtree(tmp_dir, ignore_errors=True)

        GTFS_STATIC_METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        GTFS_STATIC_METADATA_FILE.write_text(
            json.dumps(
                {
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    "source_url": url,
                    "last_modified": response.headers.get("last-modified"),
                    "etag": response.headers.get("etag"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return GTFS_STATIC_DIR
    except Exception as exc:
        logger.error("Error downloading Le TEC GTFS from %s: %s", url, exc)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None


async def ensure_gtfs_data() -> Optional[Path]:
    if _static_cache_is_valid():
        return GTFS_STATIC_DIR

    urls: List[tuple[str, Optional[Dict[str, str]]]] = []
    if str(provider_config.get("GTFS_STATIC_SOURCE", "belgian_mobility")).lower() == (
        "belgian_mobility"
    ):
        headers = mobility_subscription_headers(PROVIDER)
        if headers and provider_config.get("GTFS_STATIC_URL"):
            urls.append((provider_config["GTFS_STATIC_URL"], headers))
        else:
            logger.warning("Mobility APIM key not configured; using Le TEC static fallbacks")

    urls.extend(
        (url, None) for url in provider_config.get("GTFS_STATIC_FALLBACK_URLS", [])
    )

    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url, headers in urls:
            path = await _download_static_gtfs_from_url(client, url, headers=headers)
            if path:
                return path
    return None


def _load_stops_cache() -> None:
    global _stops_cache
    stops_file = GTFS_STATIC_DIR / "stops.txt"
    if not stops_file.exists():
        return
    new_cache: Dict[str, Dict[str, Any]] = {}
    with open(stops_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stop_id = (row.get("stop_id") or "").strip()
            if not stop_id:
                continue
            try:
                new_cache[stop_id] = {
                    "name": (row.get("stop_name") or stop_id).strip(),
                    "lat": float(row["stop_lat"]) if row.get("stop_lat") else None,
                    "lon": float(row["stop_lon"]) if row.get("stop_lon") else None,
                }
            except (KeyError, ValueError):
                new_cache[stop_id] = {"name": stop_id, "lat": None, "lon": None}
    _stops_cache = new_cache


def _load_routes_cache() -> None:
    global _routes_cache
    routes_file = GTFS_STATIC_DIR / "routes.txt"
    if not routes_file.exists():
        return
    new_cache: Dict[str, Dict[str, Any]] = {}
    with open(routes_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            route_id = (row.get("route_id") or "").strip()
            if not route_id:
                continue
            route_type = row.get("route_type")
            new_cache[route_id] = {
                "route_id": route_id,
                "route_short_name": (row.get("route_short_name") or route_id).strip(),
                "route_long_name": (row.get("route_long_name") or "").strip(),
                "route_desc": (row.get("route_desc") or "").strip(),
                "route_type": _parse_route_type(route_type),
                "route_color": (row.get("route_color") or "").strip(),
                "route_text_color": (row.get("route_text_color") or "").strip(),
            }
    _routes_cache = new_cache


def _parse_route_type(route_type: Optional[str]) -> Optional[int]:
    if not route_type or not route_type.strip():
        return None
    try:
        return int(route_type)
    except ValueError:
        logger.warning("Ignoring invalid Le TEC GTFS route_type: %s", route_type)
        return None


def _load_trips_cache() -> None:
    global _trips_cache
    trips_file = GTFS_STATIC_DIR / "trips.txt"
    if not trips_file.exists():
        return
    new_cache: Dict[str, Dict[str, Any]] = {}
    with open(trips_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = (row.get("trip_id") or "").strip()
            if not trip_id:
                continue
            new_cache[trip_id] = {
                "route_id": (row.get("route_id") or "").strip(),
                "headsign": (row.get("trip_headsign") or "").strip(),
            }
    _trips_cache = new_cache


def _load_stop_times_cache() -> None:
    global _stop_times_cache
    stop_times_file = GTFS_STATIC_DIR / "stop_times.txt"
    if not stop_times_file.exists():
        return
    new_cache: Dict[str, List[Dict[str, Any]]] = {}
    with open(stop_times_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = (row.get("trip_id") or "").strip()
            stop_id = (row.get("stop_id") or "").strip()
            if not trip_id or not stop_id:
                continue
            try:
                stop_sequence = int(row.get("stop_sequence") or 0)
            except ValueError:
                stop_sequence = 0
            new_cache.setdefault(trip_id, []).append(
                {
                    "stop_id": stop_id,
                    "stop_sequence": stop_sequence,
                    "arrival_time": (row.get("arrival_time") or "").strip(),
                    "departure_time": (row.get("departure_time") or "").strip(),
                }
            )
    for stops in new_cache.values():
        stops.sort(key=lambda stop: stop["stop_sequence"])
    _stop_times_cache = new_cache


async def _ensure_caches_initialized() -> None:
    global _caches_initialized, _init_lock
    if _caches_initialized:
        return
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    async with _init_lock:
        if _caches_initialized:
            return
        gtfs_path = await ensure_gtfs_data()
        if not gtfs_path:
            logger.error("Unable to initialize Le TEC caches without GTFS data")
            return
        _load_stops_cache()
        _load_routes_cache()
        _load_trips_cache()
        _load_stop_times_cache()
        _caches_initialized = True


def _parse_realtime_feed(response: httpx.Response) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type:
        json_format.ParseDict(
            _unwrap_gtfs_json_ints(response.json()),
            feed,
            ignore_unknown_fields=True,
        )
    else:
        feed.ParseFromString(response.content)
    return feed


def _normalize_gtfs_id(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = value.split(":", 2)
    if len(parts) == 3 and parts[1] == provider_config.get("APIM_FEED_SLUG", "tec"):
        return parts[2]
    return value


def _parse_gtfs_datetime(
    service_date: Optional[str], gtfs_time: Optional[str]
) -> Optional[datetime]:
    if not gtfs_time:
        return None
    try:
        hours, minutes, seconds = [int(part) for part in gtfs_time.split(":")]
    except (TypeError, ValueError):
        return None

    timezone_brussels = ZoneInfo("Europe/Brussels")
    if service_date:
        try:
            service_day = datetime.strptime(service_date, "%Y%m%d").date()
        except ValueError:
            service_day = datetime.now(timezone_brussels).date()
    else:
        service_day = datetime.now(timezone_brussels).date()

    base = datetime.combine(service_day, datetime.min.time(), tzinfo=timezone_brussels)
    return base + timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _scheduled_stop_time(
    trip_id: str,
    stop_id: str,
    stop_sequence: Optional[int],
    service_date: Optional[str],
    use_arrival: bool,
) -> Optional[datetime]:
    time_key = "arrival_time" if use_arrival else "departure_time"
    fallback_key = "departure_time" if use_arrival else "arrival_time"
    for stop in _trip_route_entries(trip_id):
        if stop["stop_id"] != stop_id:
            continue
        if stop_sequence is not None and stop["stop_sequence"] != stop_sequence:
            continue
        return _parse_gtfs_datetime(
            service_date, stop.get(time_key) or stop.get(fallback_key)
        )
    return None


def _unwrap_gtfs_json_ints(value: Any) -> Any:
    """Convert protobufjs-style Long JSON objects into Python integers."""
    if isinstance(value, dict):
        if "low" in value and "high" in value:
            low = int(value.get("low") or 0)
            high = int(value.get("high") or 0)
            return (high << 32) + (low & 0xFFFFFFFF)
        return {key: _unwrap_gtfs_json_ints(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_unwrap_gtfs_json_ints(item) for item in value]
    return value


async def _fetch_feed(url: str) -> gtfs_realtime_pb2.FeedMessage:
    headers = mobility_subscription_headers(PROVIDER)
    if not headers:
        raise RuntimeError(
            "MOBILITY_API_PRIMARY_KEY or MOBILITY_API_SECONDARY_KEY is required "
            "for Le TEC Belgian Mobility realtime"
        )
    timeout = httpx.Timeout(20.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return _parse_realtime_feed(response)


def _trip_candidates(trip_id: str) -> Iterable[str]:
    trip_id = _normalize_gtfs_id(trip_id)
    yield trip_id
    if "-" in trip_id:
        yield trip_id.split("-")[0]


def _get_trip_info(trip_id: str) -> Dict[str, Any]:
    for candidate in _trip_candidates(trip_id):
        if candidate in _trips_cache:
            return _trips_cache[candidate]
    return {}


def _get_stop_info(stop_id: str) -> Dict[str, Any]:
    stop_id = _normalize_gtfs_id(stop_id)
    return _stops_cache.get(stop_id, {"name": f"Unknown stop ({stop_id})"})


def _route_key(route_id: str) -> str:
    route_id = _normalize_gtfs_id(route_id)
    route_info = _routes_cache.get(route_id, {})
    return route_info.get("route_short_name") or route_id


def _route_metadata(route_id: str) -> Dict[str, Any]:
    route_id = _normalize_gtfs_id(route_id)
    route_info = _routes_cache.get(route_id, {})
    metadata = {
        "route_id": route_id,
        "route_short_name": route_info.get("route_short_name", route_id),
        "route_desc": route_info.get("route_desc", ""),
        "route_long_name": route_info.get("route_long_name", ""),
        "route_type": route_info.get("route_type"),
    }
    if route_info.get("route_color"):
        metadata["color"] = f"#{route_info['route_color']}"
    if route_info.get("route_text_color"):
        metadata["text_color"] = f"#{route_info['route_text_color']}"
    return metadata


def _trip_route(trip_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "stop_id": stop["stop_id"],
            "stop_name": _get_stop_info(stop["stop_id"]).get("name", stop["stop_id"]),
            "stop_sequence": stop["stop_sequence"],
        }
        for stop in _trip_route_entries(trip_id)
    ]


def _trip_route_entries(trip_id: str) -> List[Dict[str, Any]]:
    for candidate in _trip_candidates(trip_id):
        stops = _stop_times_cache.get(candidate)
        if stops:
            return stops
    return []


def _line_is_monitored(route_id: str, monitored_lines: List[str]) -> bool:
    route_id = _normalize_gtfs_id(route_id)
    if not monitored_lines:
        return True
    route_info = _routes_cache.get(route_id, {})
    candidates = {route_id, route_info.get("route_short_name")}
    return any(line in candidates for line in monitored_lines)


async def get_waiting_times(stop_id: Union[str, List[str]] = None) -> Dict[str, Any]:
    await _ensure_caches_initialized()
    global _last_waiting_times_result, _last_waiting_times_update

    if isinstance(stop_id, str):
        stop_ids = [
            _normalize_gtfs_id(s.strip()) for s in stop_id.split(",") if s.strip()
        ]
    elif stop_id:
        stop_ids = [_normalize_gtfs_id(str(s)) for s in stop_id]
    else:
        stop_ids = [
            _normalize_gtfs_id(str(s))
            for s in get_provider_config(PROVIDER).get("STOP_IDS", [])
        ]

    monitored_lines = get_provider_config(PROVIDER).get("MONITORED_LINES", [])
    formatted_data = {
        "stops_data": {
            sid: {
                "name": _get_stop_info(sid).get("name", f"Unknown stop ({sid})"),
                "coordinates": (
                    {
                        "lat": _get_stop_info(sid).get("lat"),
                        "lon": _get_stop_info(sid).get("lon"),
                    }
                    if _get_stop_info(sid).get("lat") and _get_stop_info(sid).get("lon")
                    else None
                ),
                "lines": {},
            }
            for sid in stop_ids
        },
        "_metadata": {"provider": PROVIDER, "realtime_source": "belgian_mobility"},
    }
    if not stop_ids:
        return formatted_data

    now = time.time()
    if (
        _last_waiting_times_result
        and _last_waiting_times_update
        and now - _last_waiting_times_update < _WAITING_TIMES_CACHE_DURATION
        and all(sid in _last_waiting_times_result["stops_data"] for sid in stop_ids)
    ):
        return _last_waiting_times_result

    try:
        if not TRIP_UPDATES_URL:
            raise RuntimeError("LETEC_GTFS_RT_TRIP_UPDATES_URL is not configured")
        feed = await _fetch_feed(TRIP_UPDATES_URL)
        now_local = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Brussels"))

        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue
            update = entity.trip_update
            trip_id = _normalize_gtfs_id(update.trip.trip_id)
            trip_info = _get_trip_info(trip_id)
            route_id = _normalize_gtfs_id(update.trip.route_id) or trip_info.get(
                "route_id"
            )
            if not route_id or not _line_is_monitored(route_id, monitored_lines):
                continue

            route_stops = _trip_route(trip_id)
            destination = (
                trip_info.get("headsign")
                or (route_stops[-1]["stop_name"] if route_stops else "")
                or route_id
            )
            line_key = _route_key(route_id)
            route_metadata = _route_metadata(route_id)

            for stop_time in update.stop_time_update:
                sid = _normalize_gtfs_id(stop_time.stop_id)
                if sid not in formatted_data["stops_data"]:
                    continue

                has_arrival = stop_time.HasField("arrival")
                event = (
                    stop_time.arrival
                    if has_arrival
                    else stop_time.departure
                    if stop_time.HasField("departure")
                    else None
                )
                if event is None:
                    continue
                delay = event.delay if event.HasField("delay") else None
                if event.HasField("time"):
                    event_timestamp = event.time
                else:
                    stop_sequence = (
                        int(stop_time.stop_sequence)
                        if stop_time.HasField("stop_sequence")
                        else None
                    )
                    scheduled_time = _scheduled_stop_time(
                        trip_id,
                        sid,
                        stop_sequence,
                        update.trip.start_date,
                        has_arrival,
                    )
                    if scheduled_time is None:
                        continue
                    event_timestamp = int(scheduled_time.timestamp()) + (delay or 0)

                line_data = formatted_data["stops_data"][sid]["lines"].setdefault(
                    line_key, {"_metadata": route_metadata}
                )
                times = line_data.setdefault(destination, [])
                arrival_time = datetime.fromtimestamp(
                    event_timestamp, timezone.utc
                ).astimezone(ZoneInfo("Europe/Brussels"))
                minutes = int((arrival_time - now_local).total_seconds() / 60)
                if minutes < -2:
                    continue

                current_sequence = next(
                    (
                        stop["stop_sequence"]
                        for stop in route_stops
                        if stop["stop_id"] == sid
                    ),
                    None,
                )
                remaining_stops = [
                    stop["stop_name"]
                    for stop in route_stops
                    if current_sequence is not None
                    and stop["stop_sequence"] > current_sequence
                ]
                times.append(
                    {
                        "delay": delay,
                        "is_realtime": delay is not None,
                        "message": None,
                        "realtime_minutes": f"{minutes}'",
                        "realtime_time": arrival_time.strftime("%H:%M"),
                        "timestamp": event_timestamp,
                        "provider": PROVIDER,
                        "remaining_stops": remaining_stops,
                    }
                )

        for stop_data in formatted_data["stops_data"].values():
            empty_lines = []
            for line_id, line_data in stop_data["lines"].items():
                for destination, times in list(line_data.items()):
                    if destination == "_metadata":
                        continue
                    times.sort(key=lambda item: item["timestamp"])
                    if not times:
                        del line_data[destination]
                if len(line_data) == 1 and "_metadata" in line_data:
                    empty_lines.append(line_id)
            for line_id in empty_lines:
                del stop_data["lines"][line_id]

        _last_waiting_times_result = formatted_data
        _last_waiting_times_update = time.time()
        return formatted_data
    except Exception as exc:
        logger.error("Error getting Le TEC waiting times: %s", exc)
        formatted_data["_metadata"]["error"] = str(exc)
        return formatted_data


def _translated_text(translated_string) -> Dict[str, str]:
    return {
        translation.language or "und": translation.text
        for translation in translated_string.translation
    }


def _enum_name(enum_type, value: int) -> str:
    try:
        return enum_type.Name(value)
    except ValueError:
        return str(value)


async def get_service_alerts() -> List[Dict[str, Any]]:
    if not SERVICE_ALERTS_URL:
        return []
    try:
        feed = await _fetch_feed(SERVICE_ALERTS_URL)
    except Exception as exc:
        logger.error("Error getting Le TEC service alerts: %s", exc)
        return []

    alerts: List[Dict[str, Any]] = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        alerts.append(
            {
                "id": entity.id,
                "provider": PROVIDER,
                "cause": _enum_name(gtfs_realtime_pb2.Alert.Cause, alert.cause),
                "effect": _enum_name(gtfs_realtime_pb2.Alert.Effect, alert.effect),
                "header": _translated_text(alert.header_text),
                "description": _translated_text(alert.description_text),
                "url": _translated_text(alert.url),
                "active_periods": [
                    {
                        "start": period.start if period.start else None,
                        "end": period.end if period.end else None,
                    }
                    for period in alert.active_period
                ],
                "informed_entities": [
                    {
                        "agency_id": entity_selector.agency_id or None,
                        "route_id": _normalize_gtfs_id(entity_selector.route_id)
                        or None,
                        "stop_id": _normalize_gtfs_id(entity_selector.stop_id) or None,
                    }
                    for entity_selector in alert.informed_entity
                ],
            }
        )
    return alerts


async def get_static_data() -> Dict[str, Any]:
    await _ensure_caches_initialized()
    return {"provider": PROVIDER, "line_info": await get_line_info()}


async def letec_config() -> Dict[str, Any]:
    return {
        "name": "Le TEC",
        "city": "Wallonia",
        "country": "Belgium",
        "monitored_lines": get_provider_config(PROVIDER).get("MONITORED_LINES", []),
        "stop_ids": get_provider_config(PROVIDER).get("STOP_IDS", []),
        "capabilities": {
            "has_vehicle_positions": False,
            "has_waiting_times": True,
            "has_service_alerts": True,
            "has_line_info": True,
            "has_route_shapes": False,
            "has_netex": False,
        },
    }


async def get_line_info() -> Dict[str, Dict[str, Any]]:
    await _ensure_caches_initialized()
    monitored_lines = get_provider_config(PROVIDER).get("MONITORED_LINES", [])
    result = {}
    for route_id, route_info in _routes_cache.items():
        if not _line_is_monitored(route_id, monitored_lines):
            continue
        line_key = _route_key(route_id)
        metadata = _route_metadata(route_id)
        result[line_key] = {
            "route_id": route_id,
            "display_name": line_key,
            "provider": PROVIDER,
            **metadata,
        }
    return result


async def get_stops() -> Dict[str, Stop]:
    await _ensure_caches_initialized()
    cache_path = CACHE_DIR / "stops.json"
    cached_stops = get_cached_stops(cache_path)
    if cached_stops:
        return cached_stops
    stops = ingest_gtfs_stops(GTFS_STATIC_DIR)
    if stops:
        cache_stops(stops, cache_path)
    return stops


async def find_nearest_stops(
    lat: float, lon: float, limit: int = 5, max_distance: float = 2.0
) -> List[Dict[str, Any]]:
    stops = await get_stops()
    nearest = get_nearest_stops(stops, lat, lon, limit, max_distance)
    return [stop.__dict__ for stop in nearest]


async def get_stop_by_name(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    stops = await get_stops()
    matches = generic_get_stop_by_name(stops, name, limit)
    return [stop.__dict__ for stop in matches] if matches else []
