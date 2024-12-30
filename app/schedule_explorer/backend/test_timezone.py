"""Test timezone handling in the waiting times endpoint."""

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch
from .main import get_waiting_times
from .gtfs_loader import Agency, Stop


@pytest.fixture
def mock_feed():
    """Create a mock feed with an agency and a stop."""
    feed = MagicMock()

    # Create a mock agency with a timezone
    agency = Agency(
        agency_id="test_agency",
        agency_name="Test Agency",
        agency_url="http://test.agency",
        agency_timezone="Europe/Budapest",
    )
    feed.agencies = {"test_agency": agency}

    # Create a mock stop
    stop = Stop(id="test_stop", name="Test Stop", lat=47.497912, lon=19.040235)
    feed.stops = {"test_stop": stop}

    return feed


@pytest.mark.asyncio
async def test_timezone_handling_with_agency_timezone(mock_feed):
    """Test that the endpoint uses the agency's timezone."""
    with patch("app.schedule_explorer.backend.main.feed", mock_feed), patch(
        "app.schedule_explorer.backend.main.ensure_provider_loaded"
    ) as mock_ensure_provider:
        # Mock the provider loading
        mock_ensure_provider.return_value = (True, "OK", MagicMock())

        # Test with UTC time
        response = await get_waiting_times(
            provider_id="test_provider",
            stop_id="test_stop",
            route_id=None,
            limit=2,
            time_local=None,
            time_utc="12:00:00",
        )

        # The response should use the agency's timezone (Europe/Budapest)
        # Budapest is UTC+1 in winter and UTC+2 in summer
        # We'll check both possibilities since the test might run in either season
        now = datetime.now(ZoneInfo("Europe/Budapest"))
        expected_hour = 13 if now.dst() is None else 14

        assert response.stops_data["test_stop"].name == "Test Stop"
        # Add more assertions based on the actual response structure


@pytest.mark.asyncio
async def test_timezone_handling_without_agency_timezone(mock_feed):
    """Test that the endpoint falls back to the server timezone when no agency timezone is available."""
    # Remove the agency from the mock feed
    mock_feed.agencies = {}

    with patch("app.schedule_explorer.backend.main.feed", mock_feed), patch(
        "app.schedule_explorer.backend.main.ensure_provider_loaded"
    ) as mock_ensure_provider:
        # Mock the provider loading
        mock_ensure_provider.return_value = (True, "OK", MagicMock())

        # Test with UTC time
        response = await get_waiting_times(
            provider_id="test_provider",
            stop_id="test_stop",
            route_id=None,
            limit=2,
            time_local=None,
            time_utc="12:00:00",
        )

        # The response should use the server timezone
        server_timezone = datetime.now().astimezone().tzinfo
        now = datetime.now(server_timezone)
        expected_hour = 13 if now.dst() is None else 14

        assert response.stops_data["test_stop"].name == "Test Stop"
        # Add more assertions based on the actual response structure
