"""Load synthetic feeds through the line-info API, including a cache reload."""

import csv
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from . import gtfs_loader, main


@pytest.fixture
def synthetic_feed(tmp_path):
    files = {
        "agency": "agency_id,agency_name,agency_url,agency_timezone\na1,Example,https://example.test,Europe/Brussels\n",
        "stops": "stop_id,stop_name,stop_lat,stop_lon\ns1,Origin,50.0,4.0\ns2,Destination,50.1,4.1\n",
        "trips": "route_id,service_id,trip_id,trip_headsign,direction_id\n8140,daily,t1,Destination,0\n",
        "stop_times": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,s1,1\nt1,08:10:00,08:10:00,s2,2\n",
        "calendar": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\ndaily,1,1,1,1,1,1,1,20200101,20991231\n",
    }
    for name, data in files.items():
        (tmp_path / f"{name}.txt").write_text(data)
    return tmp_path


@pytest.mark.parametrize(
    "short_name,long_name",
    [
        ("14", ""),
        ("14", None),
        ("", "Origin - Destination"),
        (None, "Origin - Destination"),
        ("14", "Origin - Destination"),
    ],
)
@pytest.mark.parametrize("native", [False, True])
def test_optional_route_names(
    synthetic_feed, monkeypatch, short_name, long_name, native, native_converter
):
    loader_dir = native_converter.parent if native else synthetic_feed
    monkeypatch.setattr(gtfs_loader, "__file__", str(loader_dir / "gtfs_loader.py"))
    row = {
        "route_id": "8140",
        "route_type": 3,
        "route_color": "",
        "route_text_color": "",
    }
    if short_name is not None:
        row["route_short_name"] = short_name
    if long_name is not None:
        row["route_long_name"] = long_name
    with (synthetic_feed / "routes.txt").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)

    async def provider_request(*args, **kwargs):
        return True, "OK", SimpleNamespace(raw_id="test-provider")

    monkeypatch.setattr(main, "handle_provider_request", provider_request)
    monkeypatch.setattr(main, "ensure_provider_loaded", provider_request)
    client = TestClient(main.app)
    for _ in range(2):  # Fresh CSV loading, then the persisted cache.
        feed = gtfs_loader.load_feed(synthetic_feed)
        monkeypatch.setattr(main, "feed", feed)
        route = feed.routes[0]
        assert route.route_name == (long_name or "Route 8140")
        assert route.long_name == (long_name or "")
        assert route.short_name == (short_name or "")
        assert [stop.stop.id for stop in route.stops] == ["s1", "s2"]

        response = client.get("/api/test-provider/line_info/8140")
        assert response.status_code == 200, response.text
        assert "NaN" not in response.text
        info = response.json()["8140"]
        assert info["long_name"] == (long_name or "")
        assert info["display_name"] == (short_name or "8140")
        assert info["color"] is None
        assert info["text_color"] is None
        assert info["route_type"] == 3

        stations = client.get(
            "/api/test-provider/stations/search", params={"query": "Origin"}
        )
        assert stations.status_code == 200, stations.text
        assert stations.json()[0]["id"] == "s1"
        routes = client.get(
            "/api/test-provider/routes",
            params={
                "from_station": "s1",
                "to_station": "s2",
                "date": "2026-10-11",
            },
        )
        assert routes.status_code == 200, routes.text
        assert routes.json()["total_routes"] == 1
        assert routes.json()["routes"][0]["duration_minutes"] == 10
        assert routes.json()["routes"][0]["stops"][0]["arrival_time"] == "08:00:00"
        matches = client.get(
            "/api/test-provider/routes/find",
            params={
                "route_name": long_name or "Route 8140",
            },
        )
        assert matches.status_code == 200, matches.text
        assert matches.json()[0]["route_id"] == "8140"
        waiting = client.get(
            "/api/test-provider/stops/s1/waiting_times",
            params={"time_local": "07:55:00"},
        )
        assert waiting.status_code == 200, waiting.text
        arrival = waiting.json()["stops_data"]["s1"]["lines"]["8140"]["Destination"][0]
        assert arrival["scheduled_time"] == "08:00:00"
        assert arrival["is_realtime"] is False
