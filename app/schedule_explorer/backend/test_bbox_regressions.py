"""HTTP regressions for bounding-box stop responses."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from . import gtfs_loader, main
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


@pytest.mark.parametrize("warm_cache", [False, True], ids=["cold", "warm"])
@pytest.mark.parametrize(
    "parent_station", ["0007", "", None], ids=["child", "blank", "absent"]
)
def test_bbox_loaded_parent_station(
    bbox_client, tmp_path, monkeypatch, warm_cache, parent_station
):
    parent_column = ",parent_station" if parent_station is not None else ""
    child_parent = f",{parent_station}" if parent_station is not None else ""
    empty_parent = "," if parent_station is not None else ""
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n"
        "A,Agency,https://example.test,Europe/Brussels\n",
        "stops.txt": f"stop_id,stop_name,stop_lat,stop_lon,location_type{parent_column}\n"
        f"001,First,50.0,4.0,0{child_parent}\n"
        f"0007,Parent,50.1,4.1,1{empty_parent}\n"
        f"002,Last,50.2,4.2,0{empty_parent}\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R,A,1,Test route,3\n",
        "trips.txt": "route_id,service_id,trip_id,direction_id\nR,S,T,0\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T,12:00:00,12:00:00,001,1\nT,12:10:00,12:10:00,002,2\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "S,1,1,1,1,1,1,1,20250101,20251231\n",
    }
    for name, contents in files.items():
        (tmp_path / name).write_text(contents)

    if warm_cache:
        gtfs_loader.load_feed(tmp_path)
        assert (tmp_path / ".gtfs_cache").exists()
        monkeypatch.setattr(
            gtfs_loader.pd,
            "read_csv",
            Mock(side_effect=AssertionError("Warm load must reuse the cache")),
        )
    monkeypatch.setattr(main, "feed", gtfs_loader.load_feed(tmp_path))

    response = bbox_client.get("/api/test/stops/bbox", params=BBOX)
    assert response.status_code == 200
    stations = {station["id"]: station for station in response.json()}
    assert set(stations) == {"0007", "001", "002"}
    assert len(stations["001"]["routes"]) == 1
    assert stations["001"]["routes"][0]["parent_station_id"] == (parent_station or None)
    assert stations["002"]["routes"][0]["parent_station_id"] is None
    assert stations["0007"]["routes"] == []
