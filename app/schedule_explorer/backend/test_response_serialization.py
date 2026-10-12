"""Regression tests for optional route fields in model and HTTP responses."""

import json

import pytest

from .models import RouteInfo


pytestmark = pytest.mark.filterwarnings("error:.*Pydantic serializer warnings:UserWarning")


@pytest.mark.parametrize(
    "parent", [{}, {"parent_station_id": None}, {"parent_station_id": "parent"}]
)
def test_route_info_parent_station_serialization(parent):
    route = RouteInfo(
        route_id="route",
        route_name="Origin - Terminus",
        short_name=None,
        color=None,
        text_color=None,
        first_stop="Origin",
        last_stop="Terminus",
        stops=["Origin", "Terminus"],
        headsign=None,
        service_days=["friday", "monday"],
        **parent,
    )

    payload = route.model_dump(mode="json", warnings="error")
    assert payload["parent_station_id"] == parent.get("parent_station_id")
    assert json.loads(route.model_dump_json(warnings="error")) == payload
    assert payload["service_days"] == ["Monday", "Friday"]
    assert ("parent_station_id" in route.model_dump(exclude_unset=True)) == bool(parent)
    assert ("parent_station_id" in route.model_dump(exclude_none=True)) == (
        parent.get("parent_station_id") is not None
    )


@pytest.mark.parametrize("params", [{"route_name": "Origin"}, {"short_name": "1"}])
def test_route_name_search_serializes_missing_parent_as_null(schedule_client, params):
    response = schedule_client.get("/api/test/routes/find", params=params)

    assert response.status_code == 200
    route, = response.json()
    assert route["parent_station_id"] is None
    assert route["route_id"] == "route"
    assert route["stops"] == ["Origin", "Terminus"]
    assert route["terminus_stop_id"] == "terminus"
    assert route["service_days"] == ["Monday"]
    assert route["color"] is None


@pytest.mark.parametrize("parent_id", [None, "parent"])
@pytest.mark.parametrize(
    "path",
    ["/stations/origin/routes", "/api/test/stations/origin/routes"],
)
def test_station_routes_preserve_explicit_parent(
    schedule_client, synthetic_feed, parent_id, path
):
    synthetic_feed.stops["origin"].parent_station = parent_id
    response = schedule_client.get(path)

    assert response.status_code == 200
    route, = response.json()
    assert route["parent_station_id"] == parent_id
    assert route["route_id"] == "route"
    assert route["terminus_stop_id"] == "terminus"


def test_bbox_route_serializes_absent_parent_as_null(schedule_client):
    response = schedule_client.get(
        "/api/test/stops/bbox",
        params={"min_lat": 49.99, "max_lat": 50.01, "min_lon": 3.99, "max_lon": 4.01},
    )
    assert response.status_code == 200
    station, = response.json()
    route, = station["routes"]
    assert station["id"] == "origin"
    assert route["route_id"] == "route"
    assert route["parent_station_id"] is None


def test_station_search_and_timetable_responses(schedule_client):
    response = schedule_client.get("/stations/search", params={"query": "Origin"})
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "origin",
            "name": "Origin",
            "location": {"lat": 50.0, "lon": 4.0},
            "translations": {},
            "routes": None,
        }
    ]

    params = {"from_station": "origin", "to_station": "terminus"}
    response = schedule_client.get("/api/test/routes", params=params)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_routes"] == 1
    route, = payload["routes"]
    assert route["route_id"] == "route"
    assert route["duration_minutes"] == 15
    assert [(stop["id"], stop["arrival_time"]) for stop in route["stops"]] == [
        ("origin", "14:30:00"), ("terminus", "14:45:00")
    ]
    assert route["shape"] is None
    legacy_response = schedule_client.get("/routes", params=params)
    assert legacy_response.status_code == 200
    assert legacy_response.json() == payload
