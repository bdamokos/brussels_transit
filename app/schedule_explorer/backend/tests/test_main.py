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

def test_comprehensive_provider_flow(client):
    """Test the complete flow for all providers:
    1. Get all providers and test double loading (cache)
    2. Test station search for each loaded provider
    3. Test origins/destinations for found stations
    4. Test route searching between connected stations
    5. Test provider download functionality
    """
    # First get all providers
    response = client.get("/providers_info")
    assert response.status_code == 200
    providers = response.json()
    assert isinstance(providers, list)
    assert len(providers) > 0

    # Store successful providers for later cache testing
    successful_providers = []

    # For each provider
    for provider in providers:
        provider_id = provider['id']
        
        # Try to load the provider first time
        response = client.post(f"/provider/{provider_id}")
        if response.status_code != 200:
            print(f"Warning: Could not load provider {provider_id}: {response.json()}")
            continue
            
        # Try to load the provider second time - should indicate it's already loaded
        response = client.post(f"/provider/{provider_id}")
        assert response.status_code == 200
        assert "already loaded" in response.json().get("message", "").lower(), f"Expected 'already loaded' message for {provider_id}"
        
        successful_providers.append(provider_id)
            
        # Search for stations with a simple query
        response = client.get("/stations/search?query=ab")
        assert response.status_code == 200
        stations = response.json()
        
        if not stations:
            print(f"Warning: No stations found for provider {provider_id} with query 'ab'")
            continue
            
        # Test origins/destinations for the first station
        test_station = stations[0]['id']
        
        # Test origins
        response = client.get(f"/stations/origins/{test_station}")
        assert response.status_code == 200
        origins = response.json()
        print(f"Provider {provider_id} station {test_station} has {len(origins)} origins")
        
        # Test destinations
        response = client.get(f"/stations/destinations/{test_station}")
        assert response.status_code == 200
        destinations = response.json()
        print(f"Provider {provider_id} station {test_station} has {len(destinations)} destinations")
        
        # Test routes for the station
        response = client.get(f"/stations/{test_station}/routes")
        assert response.status_code == 200
        routes = response.json()
        print(f"Provider {provider_id} station {test_station} has {len(routes)} routes")
        
        # If we have both origins and destinations, test route searching between them
        if origins and destinations:
            origin_id = origins[0]['id']
            destination_id = destinations[0]['id']
            response = client.get(f"/routes?from_station={origin_id}&to_station={destination_id}")
            assert response.status_code == 200
            route_results = response.json()
            assert "routes" in route_results
            assert "total_routes" in route_results
            print(f"Provider {provider_id} has {route_results['total_routes']} routes between {origin_id} and {destination_id}")

    print("\nTesting cache loading...")
    # Now test loading from cache for each successful provider
    for provider_id in successful_providers:
        response = client.post(f"/provider/{provider_id}")
        assert response.status_code == 200
        print(f"Successfully loaded {provider_id} from cache")

    print("\nTesting provider download functionality...")
    # Test downloading an already downloaded provider
    existing_provider = providers[0]['raw_id']  # Use the first provider's raw_id
    response = client.post(f"/api/download/{existing_provider}")
    assert response.status_code == 200
    response_data = response.json()
    assert "success" in str(response_data).lower(), f"Expected success message for {existing_provider}"
    
    # Test downloading a new small provider
    test_provider = "mdb-859"  # Small test provider
    response = client.post(f"/api/download/{test_provider}")
    assert response.status_code == 200
    response_data = response.json()
    assert "success" in str(response_data).lower(), f"Expected successful download message for {test_provider}"