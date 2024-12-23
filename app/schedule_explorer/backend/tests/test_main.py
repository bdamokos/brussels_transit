import pytest
from fastapi.testclient import TestClient
from ..main import app
import json
import os
from pathlib import Path
import shutil

def get_providers_from_metadata():
    """Get unique providers from metadata file"""
    metadata_file = Path(__file__).parent.parent.parent.parent.parent / "downloads" / "datasets_metadata.json"
    with open(metadata_file) as f:
        metadata = json.load(f)
    
    # Get unique providers (some might have multiple datasets)
    providers = {}
    for dataset in metadata.values():
        provider_id = dataset['provider_id']
        if provider_id not in providers:
            # Create URL-safe name for the provider
            safe_name = dataset['provider_name'].replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '')
            providers[provider_id] = {
                'id': f"{safe_name}_{provider_id}",  # This is the format expected by the API
                'raw_id': provider_id,
                'name': dataset['provider_name']
            }
    
    return list(providers.values())

@pytest.fixture
def client():
    """Create a test client"""
    return TestClient(app)

@pytest.fixture
def metadata_backup():
    """Backup and restore the real metadata file during tests"""
    # Get the real downloads directory and metadata file
    real_downloads_dir = Path(__file__).parent.parent.parent.parent.parent / "downloads"
    metadata_file = real_downloads_dir / "datasets_metadata.json"
    backup_file = metadata_file.parent / "datasets_metadata.json.backup"
    
    # Backup the original metadata if it exists
    if metadata_file.exists():
        shutil.copy2(metadata_file, backup_file)
    
    yield
    
    # Restore the original metadata if backup exists
    if backup_file.exists():
        shutil.move(backup_file, metadata_file)

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

@pytest.mark.parametrize("provider", get_providers_from_metadata(), ids=lambda p: p['raw_id'])
def test_provider(client, metadata_backup, provider):
    """Test a specific provider's functionality"""
    provider_id = provider['id']  # This is now in the correct format for the API
    provider_name = provider['name']
    print(f"\nTesting provider: {provider_name} ({provider['raw_id']})")
    
    # Try to load the provider
    print("  - Loading provider...")
    response = client.post(f"/provider/{provider_id}")
    if response.status_code != 200:
        pytest.skip(f"Could not load provider {provider['raw_id']}: {response.json()}")
    print("  ✓ Load successful")
    
    # Test cache (second load)
    print("  - Testing cache...")
    response = client.post(f"/provider/{provider_id}")
    assert response.status_code == 200
    assert "already loaded" in response.json().get("message", "").lower()
    print("  ✓ Cache test passed")
    
    # Search for stations
    print("  - Testing station search...")
    response = client.get("/stations/search?query=ab")
    assert response.status_code == 200
    stations = response.json()
    
    if not stations:
        pytest.skip(f"No stations found for provider {provider['raw_id']}")
    print(f"  ✓ Found {len(stations)} stations")
    
    # Test first station's data
    test_station = stations[0]['id']
    
    # Test origins
    print("  - Testing origins...")
    response = client.get(f"/stations/origins/{test_station}")
    assert response.status_code == 200
    origins = response.json()
    print(f"  ✓ Found {len(origins)} origins")
    
    # Test destinations
    print("  - Testing destinations...")
    response = client.get(f"/stations/destinations/{test_station}")
    assert response.status_code == 200
    destinations = response.json()
    print(f"  ✓ Found {len(destinations)} destinations")
    
    # Test routes
    print("  - Testing routes...")
    response = client.get(f"/stations/{test_station}/routes")
    assert response.status_code == 200
    routes = response.json()
    print(f"  ✓ Found {len(routes)} routes")

def test_provider_download(client, metadata_backup):
    """Test provider download functionality"""
    print("\nTesting provider download functionality...")
    
    # Get providers info
    response = client.get("/providers_info")
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) > 0
    
    # Test downloading an already downloaded provider
    existing_provider = providers[0]['raw_id']
    print(f"  - Testing re-download of existing provider {existing_provider}...")
    response = client.post(f"/api/download/{existing_provider}")
    assert response.status_code == 200
    response_data = response.json()
    assert "success" in str(response_data).lower()
    print("  ✓ Re-download successful")
    
    # Test downloading a new small provider
    test_provider = "mdb-859"  # Small test provider
    print(f"  - Testing download of new provider {test_provider}...")
    response = client.post(f"/api/download/{test_provider}")
    assert response.status_code == 200
    response_data = response.json()
    assert "success" in str(response_data).lower()
    print("  ✓ New download successful")