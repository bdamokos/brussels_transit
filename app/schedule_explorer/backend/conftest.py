"""Shared fixtures for offline Schedule Explorer tests."""

from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from . import main
from .gtfs_loader import FlixbusFeed, Route, RouteStop, Stop, StopTime, Trip


@pytest.fixture(scope="session")
def native_converter(tmp_path_factory):
    build = tmp_path_factory.mktemp("native-converter")
    source = Path(__file__).parent
    for name in ("gtfs_precache.c", "gtfs_precache_version.h", "Makefile"):
        shutil.copyfile(source / name, build / name)
    subprocess.run(
        ["make", "-C", str(build)], check=True, capture_output=True, text=True
    )
    return build / "gtfs_precache"


@pytest.fixture
def synthetic_feed():
    origin = Stop(id="origin", name="Origin", lat=50.0, lon=4.0)
    terminus = Stop(id="terminus", name="Terminus", lat=50.1, lon=4.1)
    stop_times = [
        StopTime("trip", "origin", "14:30:00", "14:30:00", 1),
        StopTime("trip", "terminus", "14:45:00", "14:45:00", 2),
    ]
    trip = Trip(
        id="trip", route_id="route", service_id="daily", stop_times=stop_times
    )
    route = Route(
        route_id="route",
        route_name="Origin - Terminus",
        short_name="1",
        trip_id=trip.id,
        stops=[
            RouteStop(origin, "14:30:00", "14:30:00", 1),
            RouteStop(terminus, "14:45:00", "14:45:00", 2),
        ],
        service_days=["monday"],
        trips=[trip],
    )
    return FlixbusFeed(
        stops={origin.id: origin, terminus.id: terminus},
        routes=[route],
        trips={trip.id: trip},
    )


@pytest.fixture
def schedule_client(monkeypatch, synthetic_feed):
    monkeypatch.setattr(main, "feed", synthetic_feed)
    monkeypatch.setattr(
        main,
        "ensure_provider_loaded",
        AsyncMock(return_value=(True, "OK", SimpleNamespace(raw_id="test"))),
    )
    # Do not run startup discovery or load/download external datasets.
    client = TestClient(main.app)
    yield client
    client.close()
