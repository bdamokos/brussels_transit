import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from transit_providers.be.letec import api
from google.transit import gtfs_realtime_pb2


def _binary_response(feed):
    return httpx.Response(
        200,
        headers={"content-type": "application/x-protobuf"},
        content=feed.SerializeToString(),
        request=httpx.Request("GET", "https://example.test"),
    )


def test_parse_realtime_feed_accepts_binary_protobuf():
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.entity.add(id="trip-1").trip_update.trip.trip_id = "t1"

    parsed = api._parse_realtime_feed(_binary_response(feed))

    assert parsed.header.gtfs_realtime_version == "2.0"
    assert parsed.entity[0].id == "trip-1"
    assert parsed.entity[0].trip_update.trip.trip_id == "t1"


def test_parse_route_type_handles_invalid_values():
    assert api._parse_route_type("3") == 3
    assert api._parse_route_type(" 3 ") == 3
    assert api._parse_route_type("") is None
    assert api._parse_route_type("not-a-number") is None


def test_normalize_gtfs_id_strips_belgian_mobility_prefixes():
    assert api._normalize_gtfs_id("gs:tec:stop-1") == "stop-1"
    assert api._normalize_gtfs_id("gr:tec:route-1") == "route-1"
    assert api._normalize_gtfs_id("gt:tec:trip-1") == "trip-1"
    assert api._normalize_gtfs_id("stop-1") == "stop-1"
    assert api._normalize_gtfs_id(None) == ""


def test_get_waiting_times_formats_trip_updates(monkeypatch):
    now = datetime.now(timezone.utc)
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    entity = feed.entity.add(id="e1")
    entity.trip_update.trip.trip_id = "gt:tec:trip-1"
    entity.trip_update.trip.route_id = "gr:tec:route-1"
    stop_update = entity.trip_update.stop_time_update.add()
    stop_update.stop_id = "gs:tec:stop-1"
    stop_update.arrival.time = int((now + timedelta(minutes=5)).timestamp())
    stop_update.arrival.delay = 60

    async def fake_ensure_caches_initialized():
        return None

    async def fake_fetch_feed(url):
        return feed

    monkeypatch.setattr(api, "_ensure_caches_initialized", fake_ensure_caches_initialized)
    monkeypatch.setattr(api, "_fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(api, "TRIP_UPDATES_URL", "https://example.test/trips")
    monkeypatch.setattr(api, "_last_waiting_times_result", None)
    monkeypatch.setattr(api, "_last_waiting_times_update", None)
    monkeypatch.setattr(
        api,
        "_stops_cache",
        {"stop-1": {"name": "Namur Gare", "lat": 50.466, "lon": 4.866}},
    )
    monkeypatch.setattr(
        api,
        "_routes_cache",
        {
            "route-1": {
                "route_short_name": "12",
                "route_long_name": "Namur - Jambes",
                "route_desc": "",
                "route_type": 3,
            }
        },
    )
    monkeypatch.setattr(
        api,
        "_trips_cache",
        {"trip-1": {"route_id": "route-1", "headsign": "Jambes"}},
    )
    monkeypatch.setattr(
        api,
        "_stop_times_cache",
        {
            "trip-1": [
                {"stop_id": "stop-1", "stop_sequence": 1},
                {"stop_id": "stop-2", "stop_sequence": 2},
            ]
        },
    )

    result = asyncio.run(api.get_waiting_times("gs:tec:stop-1"))

    line = result["stops_data"]["stop-1"]["lines"]["12"]
    assert line["_metadata"]["route_id"] == "route-1"
    assert line["Jambes"][0]["provider"] == "letec"
    assert line["Jambes"][0]["delay"] == 60
    assert line["Jambes"][0]["is_realtime"] is True
    assert line["Jambes"][0]["timestamp"] == stop_update.arrival.time


def test_get_waiting_times_sorts_by_timestamp_across_midnight(monkeypatch):
    local_now = datetime.now(ZoneInfo("Europe/Brussels"))
    first_arrival = local_now.replace(hour=23, minute=55, second=0, microsecond=0)
    if first_arrival <= local_now + timedelta(minutes=3):
        first_arrival += timedelta(days=1)
    second_arrival = first_arrival + timedelta(minutes=10)

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    entity = feed.entity.add(id="e1")
    entity.trip_update.trip.trip_id = "trip-1"
    entity.trip_update.trip.route_id = "route-1"

    later_update = entity.trip_update.stop_time_update.add()
    later_update.stop_id = "stop-1"
    later_update.arrival.time = int(second_arrival.timestamp())

    earlier_update = entity.trip_update.stop_time_update.add()
    earlier_update.stop_id = "stop-1"
    earlier_update.arrival.time = int(first_arrival.timestamp())

    async def fake_ensure_caches_initialized():
        return None

    async def fake_fetch_feed(url):
        return feed

    monkeypatch.setattr(api, "_ensure_caches_initialized", fake_ensure_caches_initialized)
    monkeypatch.setattr(api, "_fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(api, "TRIP_UPDATES_URL", "https://example.test/trips")
    monkeypatch.setattr(api, "_last_waiting_times_result", None)
    monkeypatch.setattr(api, "_last_waiting_times_update", None)
    monkeypatch.setattr(
        api,
        "_stops_cache",
        {"stop-1": {"name": "Namur Gare", "lat": 50.466, "lon": 4.866}},
    )
    monkeypatch.setattr(
        api,
        "_routes_cache",
        {"route-1": {"route_short_name": "12", "route_type": 3}},
    )
    monkeypatch.setattr(
        api,
        "_trips_cache",
        {"trip-1": {"route_id": "route-1", "headsign": "Jambes"}},
    )
    monkeypatch.setattr(
        api,
        "_stop_times_cache",
        {"trip-1": [{"stop_id": "stop-1", "stop_sequence": 1}]},
    )

    result = asyncio.run(api.get_waiting_times("stop-1"))

    times = result["stops_data"]["stop-1"]["lines"]["12"]["Jambes"]
    assert [time["timestamp"] for time in times] == [
        earlier_update.arrival.time,
        later_update.arrival.time,
    ]


def test_get_waiting_times_uses_static_schedule_for_delay_only_updates(monkeypatch):
    scheduled_time = datetime.now(ZoneInfo("Europe/Brussels")) + timedelta(minutes=15)

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    entity = feed.entity.add(id="e1")
    entity.trip_update.trip.trip_id = "gt:tec:trip-1"
    entity.trip_update.trip.route_id = "gr:tec:route-1"
    entity.trip_update.trip.start_date = scheduled_time.strftime("%Y%m%d")
    stop_update = entity.trip_update.stop_time_update.add()
    stop_update.stop_id = "gs:tec:stop-1"
    stop_update.stop_sequence = 1
    stop_update.arrival.delay = 120

    async def fake_ensure_caches_initialized():
        return None

    async def fake_fetch_feed(url):
        return feed

    monkeypatch.setattr(api, "_ensure_caches_initialized", fake_ensure_caches_initialized)
    monkeypatch.setattr(api, "_fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(api, "TRIP_UPDATES_URL", "https://example.test/trips")
    monkeypatch.setattr(api, "_last_waiting_times_result", None)
    monkeypatch.setattr(api, "_last_waiting_times_update", None)
    monkeypatch.setattr(
        api,
        "_stops_cache",
        {"stop-1": {"name": "Namur Gare", "lat": 50.466, "lon": 4.866}},
    )
    monkeypatch.setattr(
        api,
        "_routes_cache",
        {"route-1": {"route_short_name": "12", "route_type": 3}},
    )
    monkeypatch.setattr(
        api,
        "_trips_cache",
        {"trip-1": {"route_id": "route-1", "headsign": "Jambes"}},
    )
    monkeypatch.setattr(
        api,
        "_stop_times_cache",
        {
            "trip-1": [
                {
                    "stop_id": "stop-1",
                    "stop_sequence": 1,
                    "arrival_time": scheduled_time.strftime("%H:%M:%S"),
                    "departure_time": scheduled_time.strftime("%H:%M:%S"),
                }
            ]
        },
    )

    result = asyncio.run(api.get_waiting_times("stop-1"))

    departure = result["stops_data"]["stop-1"]["lines"]["12"]["Jambes"][0]
    expected_timestamp = int(
        scheduled_time.replace(microsecond=0).timestamp()
    ) + 120
    assert departure["delay"] == 120
    assert departure["timestamp"] == expected_timestamp
    assert departure["is_realtime"] is True


def test_get_service_alerts_formats_gtfs_rt_alert(monkeypatch):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    entity = feed.entity.add(id="alert-1")
    alert = entity.alert
    alert.cause = gtfs_realtime_pb2.Alert.CONSTRUCTION
    alert.effect = gtfs_realtime_pb2.Alert.DETOUR
    header = alert.header_text.translation.add()
    header.language = "en"
    header.text = "Works"
    description = alert.description_text.translation.add()
    description.language = "en"
    description.text = "Line diverted"
    informed = alert.informed_entity.add()
    informed.route_id = "route-1"

    async def fake_fetch_feed(url):
        return feed

    monkeypatch.setattr(api, "_fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(api, "SERVICE_ALERTS_URL", "https://example.test/alerts")

    result = asyncio.run(api.get_service_alerts())

    assert result == [
        {
            "id": "alert-1",
            "provider": "letec",
            "cause": "CONSTRUCTION",
            "effect": "DETOUR",
            "header": {"en": "Works"},
            "description": {"en": "Line diverted"},
            "url": {},
            "active_periods": [],
            "informed_entities": [
                {"agency_id": None, "route_id": "route-1", "stop_id": None}
            ],
        }
    ]
