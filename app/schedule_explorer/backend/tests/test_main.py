import pytest
from fastapi.testclient import TestClient
from ..main import app
import json
import os
from pathlib import Path

@pytest.fixture
def client():
    """Create a test client"""
    return TestClient(app)

@pytest.fixture
def stib_provider(client):
    """Load the STIB provider"""
    response = client.post("/provider/Societe_des_Transports_Intercommunaux_de_Bruxelles_Maatschappij_voor_het_Intercommunaal_Vervoer_te_Brussel_STIB_MIVB_mdb-1088")
    assert response.status_code == 200
    return response

def test_get_providers_empty(client):
    """Test getting providers list when no providers are loaded"""
    response = client.get("/providers")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_search_stations_no_feed(client):
    """Test searching stations when no feed is loaded"""
    response = client.get("/stations/search?query=test")
    assert response.status_code == 503

def test_get_routes_no_feed(client):
    """Test getting routes when no feed is loaded"""
    response = client.get("/routes?from_station=123&to_station=456")
    assert response.status_code == 503

def test_get_destinations_no_feed(client):
    """Test getting destinations when no feed is loaded"""
    response = client.get("/stations/destinations/123")
    assert response.status_code == 503

def test_get_origins_no_feed(client):
    """Test getting origins when no feed is loaded"""
    response = client.get("/stations/origins/123")
    assert response.status_code == 503

def test_get_station_routes_no_feed(client):
    """Test getting station routes when no feed is loaded"""
    response = client.get("/stations/123/routes")
    assert response.status_code == 503

def test_get_providers_info(client):
    """Test getting providers info"""
    response = client.get("/providers_info")
    assert response.status_code == 200
    providers = response.json()
    print("Providers info:", json.dumps(providers, indent=2))  # Debug output
    assert isinstance(providers, list)
    # Check if our STIB provider is in the list
    assert any(p.get("raw_id") == "mdb-1088" for p in providers)
    assert any(p.get("raw_id") == "mdb-1857" for p in providers)

def test_get_providers_by_country(client):
    """Test getting providers by country"""
    response = client.get("/api/providers/BE")
    assert response.status_code == 200
    providers = response.json()
    assert isinstance(providers, list)
    assert len(providers) > 0

def test_load_stib_provider(client):
    """Test loading the STIB provider"""
    response = client.post("/provider/Societe_des_Transports_Intercommunaux_de_Bruxelles_Maatschappij_voor_het_Intercommunaal_Vervoer_te_Brussel_STIB_MIVB_mdb-1088")
    assert response.status_code == 200

def test_search_stations_with_stib(client, stib_provider):
    """Test searching stations with STIB data"""
    response = client.get("/stations/search?query=gare")
    assert response.status_code == 200
    stations = response.json()
    assert isinstance(stations, list)
    assert len(stations) > 0
    for station in stations:
        assert "id" in station
        assert "name" in station
        assert "location" in station
        assert "lat" in station["location"]
        assert "lon" in station["location"]

def test_get_routes_with_stib(client, stib_provider):
    """Test getting routes between two stations with STIB data"""
    # First, search for some stations
    response = client.get("/stations/search?query=gare")
    assert response.status_code == 200
    stations = response.json()
    assert len(stations) >= 2
    
    # Get routes between the first two stations
    response = client.get(f"/routes?from_station={stations[0]['id']}&to_station={stations[1]['id']}")
    assert response.status_code == 200
    routes = response.json()
    assert "routes" in routes
    assert "total_routes" in routes
    for route in routes["routes"]:
        assert "route_id" in route
        assert "route_name" in route
        assert "stops" in route
        assert len(route["stops"]) >= 2

def test_get_destinations_with_stib(client, stib_provider):
    """Test getting destinations from a station with STIB data"""
    # First, search for a station
    response = client.get("/stations/search?query=gare")
    assert response.status_code == 200
    stations = response.json()
    assert len(stations) > 0
    
    # Get destinations from the first station
    response = client.get(f"/stations/destinations/{stations[0]['id']}")
    assert response.status_code == 200
    destinations = response.json()
    assert isinstance(destinations, list)
    for destination in destinations:
        assert "id" in destination
        assert "name" in destination
        assert "location" in destination

def test_get_station_routes_with_stib(client, stib_provider):
    """Test getting routes serving a station with STIB data"""
    # First, search for a station
    response = client.get("/stations/search?query=gare")
    assert response.status_code == 200
    stations = response.json()
    assert len(stations) > 0
    
    # Get routes serving the first station
    response = client.get(f"/stations/{stations[0]['id']}/routes")
    assert response.status_code == 200
    routes = response.json()
    assert isinstance(routes, list)
    for route in routes:
        assert "route_id" in route
        assert "route_name" in route
        assert "stops" in route
        assert len(route["stops"]) >= 2