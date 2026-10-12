"""Waiting-time reference clocks exercised through both HTTP URL forms."""

import os
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from . import gtfs_loader as loader
from . import main


@pytest.fixture(params=["path", "query"])
def waiting_url(request):
    if request.param == "path":
        return "/api/test/stops/start/waiting_times"
    return "/api/test/waiting_times"


@pytest.fixture
def reference_client(monkeypatch):
    client = TestClient(main.app)
    client.params = {"stop_id": "start"}

    def configure(departures, now="2025-01-15T09:00:00+00:00", timezone="Europe/Brussels"):
        instant = datetime.fromisoformat(now)

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is not None:
                    return instant.astimezone(tz)
                return instant.astimezone().replace(tzinfo=None)

        stops = {
            key: loader.Stop(key, name, 50.0, 4.0)
            for key, name in [("start", "Start"), ("end", "End"), ("other", "Other")]
        }
        feed = loader.FlixbusFeed(stops=stops, routes=[])
        feed.calendar_dates = [loader.CalendarDate("S", datetime(2025, 1, 15), 1)]
        feed.agencies["A"] = loader.Agency("A", "Agency", "https://example.test", timezone)
        for route_id, end, times in [("R", "end", departures), ("Q", "other", ["13:07:00"])]:
            for index, departure in enumerate(times):
                trip_id = f"{route_id}-{index}"
                hours, minutes, seconds = map(int, departure.split(":"))
                # Each trip ends one hour later, retaining GTFS hours above 23.
                arrival = f"{hours + 1:02}:{minutes:02}:{seconds:02}"
                route_stops = [
                    loader.RouteStop(stops[stop_id], clock, clock, sequence)
                    for sequence, (stop_id, clock) in enumerate(
                        [("start", departure), (end, arrival)], start=1
                    )
                ]
                feed.trips[trip_id] = loader.Trip(trip_id, route_id, "S")
                feed.stop_times_dict[trip_id] = [
                    loader.StopTime(trip_id, s.stop.id, s.arrival_time, s.departure_time, s.stop_sequence)
                    for s in route_stops
                ]
                if index == 0:
                    feed.routes.append(loader.Route(route_id, route_id, trip_id, route_stops, []))

        async def ready(provider_id, auto_download=False):
            assert provider_id == "test"
            assert not auto_download
            return True, "OK", SimpleNamespace(raw_id="test")

        monkeypatch.setattr(main, "feed", feed)
        monkeypatch.setattr(main, "ensure_provider_loaded", ready)
        monkeypatch.setattr(main, "datetime", FrozenDatetime)
        return client

    yield configure
    client.close()


def arrivals(client, url, **params):
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    lines = response.json()["stops_data"]["start"]["lines"]
    values = lines["R"]["End"]
    assert all(value["is_realtime"] is False and value["provider"] == "test" for value in values)
    return [(value["scheduled_time"], value["scheduled_minutes"]) for value in values]


def test_local_reference_changes_minutes_and_arrival_order(reference_client, waiting_url):
    client = reference_client(["13:05:00", "13:15:00", "13:25:00", "13:15:00"])
    assert arrivals(client, waiting_url, time_local="13:00:00") == [
        ("13:05:00", "5'"), ("13:15:00", "15'")
    ]
    assert arrivals(client, waiting_url, time_local="13:10:00", route_id="R", limit=3) == [
        ("13:15:00", "5'"), ("13:25:00", "15'"), ("13:05:00", "1435'")
    ]
    response = client.get(waiting_url, params={"time_local": "13:00:00", "route_id": "R", "limit": 1})
    assert response.status_code == 200
    assert set(response.json()["stops_data"]["start"]["lines"]) == {"R"}
    assert arrivals(client, waiting_url, time_local="13:00:00", limit=1) == [("13:05:00", "5'")]


@pytest.mark.parametrize("server_timezone", ["UTC", "America/Los_Angeles"])
@pytest.mark.parametrize(
    "now,utc,departure",
    [
        ("2025-01-15T09:00:00+00:00", "12:00:00", "13:05:00"),
        ("2025-07-15T09:00:00+00:00", "11:00:00", "13:05:00"),
        ("2025-03-30T12:00:00+00:00", "00:50:00", "01:55:00"),
        ("2025-03-30T12:00:00+00:00", "01:50:00", "03:55:00"),
        ("2025-10-26T12:00:00+00:00", "00:50:00", "02:55:00"),
        ("2025-10-26T12:00:00+00:00", "01:50:00", "02:55:00"),
        # The agency's date is already March 30; the UTC date is still March 29.
        ("2025-03-29T23:30:00+00:00", "01:55:00", "03:00:00"),
        ("2025-01-15T12:00:00+00:00", "23:55:00", "01:00:00"),
    ],
)
def test_utc_reference_uses_todays_utc_date_and_agency_offset(
    reference_client, waiting_url, monkeypatch, server_timezone, now, utc, departure
):
    original_timezone = os.environ.get("TZ")
    monkeypatch.setenv("TZ", server_timezone)
    time.tzset()
    try:
        client = reference_client([departure], now=now)
        assert arrivals(client, waiting_url, time_utc=utc) == [(departure, "5'")]
    finally:
        if original_timezone is None:
            monkeypatch.delenv("TZ")
        else:
            monkeypatch.setenv("TZ", original_timezone)
        time.tzset()


@pytest.mark.parametrize(
    "params,expected",
    [
        ({}, [("13:05:00", "185'")]),
        ({"time_local": "", "time_utc": ""}, [("13:05:00", "185'")]),
        ({"time_local": "13:00:00", "time_utc": "invalid"}, [("13:05:00", "5'")]),
        ({"time_local": "13:04:30"}, [("13:05:00", "0'")]),
    ],
)
def test_default_clock_precedence_and_seconds(reference_client, waiting_url, params, expected):
    client = reference_client(["13:05:00"])
    assert arrivals(client, waiting_url, **params) == expected


def test_reference_preserves_overnight_gtfs_times(reference_client, waiting_url):
    client = reference_client(["23:55:00", "24:05:00", "25:10:00"])
    assert arrivals(client, waiting_url, time_local="23:50:00", limit=3) == [
        ("23:55:00", "5'"), ("24:05:00", "15'"), ("25:10:00", "80'")
    ]


@pytest.mark.parametrize("parameter", ["time_local", "time_utc"])
@pytest.mark.parametrize("value", ["invalid", "24:00:00", "12:60:00", "12:30"])
def test_invalid_reference_returns_http_400(reference_client, waiting_url, parameter, value):
    client = reference_client(["13:05:00"])
    response = client.get(waiting_url, params={parameter: value})
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid time format. Use HH:MM:SS"}
