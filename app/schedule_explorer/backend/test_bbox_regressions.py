"""HTTP regressions for bounding-box stop responses."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from . import main
from .gtfs_loader import FlixbusFeed, Route, RouteStop, Stop


BBOX = {"min_lat": 50.0, "min_lon": 4.0, "max_lat": 50.2, "max_lon": 4.2}


@pytest.fixture
def bbox_client(monkeypatch):
    child = Stop("child", "Platform", 50.0, 4.0, parent_station="parent")
    parent = Stop("parent", "Station", 50.1, 4.1, location_type=1)
    unparented = Stop("unparented", "Standalone", 50.2, 4.2)
    terminus = Stop("terminus", "Terminus", 51.0, 5.0, parent_station="other")
    stops = [child, parent, unparented, terminus]
    route = Route(
        route_id="R",
        route_name="Test route",
        trip_id="T",
        stops=[
            RouteStop(stop, "12:00:00", "12:00:00", sequence)
            for sequence, stop in enumerate(stops, start=1)
        ],
        service_days=["monday"],
        short_name="1",
        color="123456",
        text_color="FFFFFF",
    )
    # Feed insertion order differs from the endpoint's sorted pagination order.
    feed = FlixbusFeed(stops={stop.id: stop for stop in reversed(stops)}, routes=[route])
    monkeypatch.setattr(main, "feed", feed)
    monkeypatch.setattr(
        main,
        "ensure_provider_loaded",
        AsyncMock(return_value=(True, "OK", SimpleNamespace(raw_id="test"))),
    )
    # Avoid startup provider discovery; all endpoint data is in memory.
    client = TestClient(main.app)
    yield client
    client.close()


@pytest.mark.parametrize(
    "offset,stop_id,parent_station_id",
    [(0, "child", "parent"), (1, "parent", None), (2, "unparented", None)],
)
def test_bbox_route_parent_station(bbox_client, offset, stop_id, parent_station_id):
    response = bbox_client.get(
        "/api/test/stops/bbox", params={**BBOX, "offset": offset, "limit": 1}
    )

    assert response.status_code == 200
    stations = response.json()
    assert [station["id"] for station in stations] == [stop_id]
    assert len(stations[0]["routes"]) == 1
    route = stations[0]["routes"][0]
    assert route["parent_station_id"] == parent_station_id
    assert route["route_id"] == "R"
    assert route["route_name"] == "Test route"
    assert route["short_name"] == "1"
    assert route["color"] == "123456"
    assert route["text_color"] == "FFFFFF"
    assert route["stops"] == ["Platform", "Station", "Standalone", "Terminus"]
    assert route["service_days"] == ["Monday"]
    assert route["terminus_stop_id"] == "terminus"


def test_bbox_unpaginated_count_and_empty_results(bbox_client):
    response = bbox_client.get("/api/test/stops/bbox", params=BBOX)
    assert response.status_code == 200
    assert [station["id"] for station in response.json()] == [
        "child", "parent", "unparented"
    ]
    assert [station["routes"][0]["parent_station_id"] for station in response.json()] == [
        "parent", None, None
    ]

    count = bbox_client.get(
        "/api/test/stops/bbox", params={**BBOX, "count_only": True, "limit": 1}
    )
    assert count.status_code == 200
    assert count.json() == {"count": 3}

    empty = bbox_client.get("/api/test/stops/bbox", params={**BBOX, "offset": 3})
    assert empty.status_code == 200
    assert empty.json() == []
