"""Test timezone handling through both waiting-time HTTP endpoints."""

from datetime import datetime, timezone
import time

import pytest

from . import main
from .gtfs_loader import Agency


pytestmark = pytest.mark.filterwarnings("error:.*Pydantic serializer warnings:UserWarning")


@pytest.fixture
def utc_server(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setenv("TZ", "UTC")
        time.tzset()
        yield
    time.tzset()


@pytest.mark.parametrize("month", [1, 7])
@pytest.mark.parametrize("agency_timezone", ["Europe/Budapest", None])
@pytest.mark.parametrize(
    "path", ["/api/test/stops/origin/waiting_times", "/api/test/waiting_times"]
)
def test_waiting_time_timezone_response(
    schedule_client, synthetic_feed, monkeypatch, utc_server, month, agency_timezone, path
):
    fixed_now = datetime(2026, month, 15, 12, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(main, "datetime", FixedDateTime)
    if agency_timezone:
        synthetic_feed.agencies = {
            "agency": Agency(
                "agency", "Test Agency", "https://example.com", agency_timezone
            )
        }

    response = schedule_client.get(path, params={"stop_id": "origin", "limit": 2})

    assert response.status_code == 200
    stop = response.json()["stops_data"]["origin"]
    assert stop["name"] == "Origin"
    assert stop["coordinates"] == {"lat": 50.0, "lon": 4.0}
    line = stop["lines"]["route"]
    assert line["_metadata"] == [
        {"route_desc": "Origin - Terminus", "route_short_name": "1"}
    ]
    expected_minutes = (90 if month == 1 else 30) if agency_timezone else 150
    assert line["Terminus"] == [
        {
            "is_realtime": False,
            "provider": "test",
            "scheduled_time": "14:30:00",
            "scheduled_minutes": f"{expected_minutes}'",
        }
    ]
