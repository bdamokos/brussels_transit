"""GTFS-realtime providers share descriptors and retain RealCity extensions."""

import itertools
import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

BINDINGS = (
    "google.transit.gtfs_realtime_pb2",
    "transit_providers.hu.bkk.protos.gtfs_realtime_pb2",
    "transit_providers.be.sncb.protos.gtfs_realtime_pb2",
)


def run_isolated(tmp_path, code, implementation, enabled="none"):
    (tmp_path / "logs").mkdir()
    root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(root / "app"), str(root))),
        "PROJECT_ROOT": str(tmp_path),
        "ENABLED_PROVIDERS": enabled,
        "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": implementation,
    }
    # The child process has its own descriptor pool and no live network access.
    prelude = f"""
import socket
def no_network(*args, **kwargs):
    raise AssertionError("This test must not use the network")
socket.socket.connect = no_network
socket.create_connection = no_network
import config
config.local_config = None
config.default_config.ENABLED_PROVIDERS = {enabled.split(',')!r}
"""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(prelude) + textwrap.dedent(code)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("order", list(itertools.permutations(BINDINGS)))
@pytest.mark.parametrize("implementation", ["upb", "python"])
def test_import_order_and_extension_roundtrip(tmp_path, order, implementation):
    code = f"""
import importlib
modules = [importlib.import_module(name) for name in {order!r}]
from google.transit import gtfs_realtime_pb2 as gtfs
from transit_providers.hu.bkk.protos import gtfs_realtime_realcity_pb2 as realcity
from transit_providers.hu.bkk.api import parse_realcity_extension
for module in modules:
    assert module.DESCRIPTOR is gtfs.DESCRIPTOR
    assert module.FeedMessage is gtfs.FeedMessage

feed = gtfs.FeedMessage()
feed.header.gtfs_realtime_version = "2.0"
vehicle = feed.entity.add(id="vehicle").vehicle
vehicle.trip.trip_id = "t1"
vehicle.position.latitude = 47.5
vehicle.position.longitude = 19.0
vehicle.vehicle.id = "v1"
vehicle.vehicle.wheelchair_accessible = gtfs.VehicleDescriptor.WHEELCHAIR_ACCESSIBLE
vehicle.vehicle.Extensions[realcity.vehicle].vehicle_model = "Example bus"
update = feed.entity.add(id="trip").trip_update
update.trip.trip_id = "t1"
stop = update.stop_time_update.add(stop_id="s1", stop_sequence=1)
stop.arrival.time = 1700000060
stop.arrival.delay = 60
stop.Extensions[realcity.stop_time_update].scheduled_arrival.time = 1700000000
alert = feed.entity.add(id="alert").alert
alert.header_text.translation.add(text="Service change", language="en")
extension = alert.Extensions[realcity.alert]
extension.modifiedTime = 1700000000
extension.startText.translation.add(text="Today", language="en")
extension.endText.translation.add(text="Tomorrow", language="en")
extension.route.add(route_id="r1").header_text.translation.add(text="Detour", language="en")

wire = feed.SerializeToString()
for module in modules:
    parsed = module.FeedMessage.FromString(wire)
    assert parsed == feed
    assert parsed.entity[0].vehicle.vehicle.Extensions[realcity.vehicle].vehicle_model == "Example bus"
    assert parsed.entity[1].trip_update.stop_time_update[0].arrival.delay == 60
    assert parsed.entity[1].trip_update.stop_time_update[0].Extensions[realcity.stop_time_update].scheduled_arrival.time == 1700000000
    data = parse_realcity_extension(parsed.entity[2].alert.SerializeToString())
    assert data["modified_time"] == 1700000000
    assert data["start_text"] == {{"en": "Today"}}
    assert data["end_text"] == {{"en": "Tomorrow"}}
    assert data["route_details"][0]["route_id"] == "r1"
"""
    run_isolated(tmp_path, code, implementation)


@pytest.mark.parametrize("implementation", ["upb", "python"])
def test_legacy_startup_registers_all_providers(tmp_path, implementation):
    run_isolated(
        tmp_path,
        """
from google.transit import gtfs_realtime_pb2
from app.main import app
from transit_providers import PROVIDERS
expected = {"bkk", "sncb", "stib", "delijn", "letec"}
assert expected <= PROVIDERS.keys(), set(PROVIDERS)
response = app.test_client().get("/api/providers")
assert response.status_code == 200
assert expected <= response.json.keys()
assert {"waiting_times", "messages", "vehicles", "line_info", "route", "colors"} <= set(response.json["bkk"]["endpoints"])
""",
        implementation,
        enabled="bkk,sncb,stib,delijn,letec",
    )


def test_bkk_realtime_decoding_and_concurrent_waiting_times(monkeypatch):
    from google.transit import gtfs_realtime_pb2 as gtfs
    import httpx
    from transit_providers.hu.bkk import api

    now = datetime.now(timezone.utc).replace(microsecond=0)
    feed = gtfs.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    trip = feed.entity.add(id="trip").trip_update
    trip.trip.trip_id = "t1"
    trip.trip.route_id = "r1"
    stop = trip.stop_time_update.add(stop_id="s1", stop_sequence=1)
    stop.arrival.time = int((now + timedelta(minutes=5)).timestamp())
    vehicle = feed.entity.add(id="vehicle").vehicle
    vehicle.trip.trip_id = "t1"
    vehicle.trip.route_id = "r1"
    vehicle.vehicle.id = "v1"
    vehicle.vehicle.label = "Destination"
    vehicle.vehicle.license_plate = "TEST-001"
    vehicle.position.latitude = 47.5
    vehicle.position.longitude = 19.0
    vehicle.position.speed = 10
    vehicle.timestamp = int(now.timestamp())
    payload = feed.SerializeToString()
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            calls.append(url)
            await asyncio.sleep(
                0
            )  # Let the other waiting-time requests acquire their locks.
            return httpx.Response(
                200,
                content=payload,
                request=httpx.Request("GET", "https://example.test/feed"),
            )

    async def initialized():
        pass

    monkeypatch.setattr(api, "_ensure_caches_initialized", initialized)
    monkeypatch.setattr(api.httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        api,
        "get_provider_config",
        lambda _: {"MONITORED_LINES": [], "STOP_IDS": ["s1"]},
    )
    monkeypatch.setattr(
        api, "_get_stop_info", lambda _: {"name": "Origin", "lat": 47.5, "lon": 19.0}
    )
    monkeypatch.setattr(
        api,
        "_get_route_info",
        lambda _: {"route_short_name": "14", "route_desc": "Destination"},
    )
    monkeypatch.setattr(api, "_get_line_id_from_trip", lambda route_id: route_id)
    monkeypatch.setattr(api, "_get_destination_from_trip", lambda *args: "Destination")
    monkeypatch.setattr(
        api, "_get_scheduled_time", lambda *args: now + timedelta(minutes=4)
    )
    monkeypatch.setattr(api, "_last_waiting_times_result", None)
    monkeypatch.setattr(api, "_last_waiting_times_update", None)
    monkeypatch.setattr(api, "_waiting_times_locks", {})

    async def check():
        results = await asyncio.gather(*(api.get_waiting_times("s1") for _ in range(8)))
        assert len(calls) == 1
        for result in results:
            arrival = result["stops_data"]["s1"]["lines"]["r1"]["Destination"][0]
            assert arrival["delay"] == 60
            assert arrival["is_realtime"] is True
            assert arrival["provider"] == "bkk"
        vehicles = await api.get_vehicle_positions(line="r1")
        assert len(vehicles) == 1
        assert vehicles[0]["id"] == "v1"
        assert vehicles[0]["speed"] == 36
        assert vehicles[0]["license_plate"] == "TEST-001"

    asyncio.run(check())
