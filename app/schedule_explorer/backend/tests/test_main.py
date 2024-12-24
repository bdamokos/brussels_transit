import pytest
from fastapi.testclient import TestClient
from ..main import app
import json
import os
from pathlib import Path
import shutil
from unidecode import unidecode
import re
import random
import csv

def get_providers_from_metadata():
    """Get a list of providers from the metadata file"""
    metadata_file = Path(__file__).parent.parent.parent.parent.parent / "downloads" / "datasets_metadata.json"
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    # Get unique providers (some might have multiple datasets)
    providers = {}
    latest_datasets = {}  # Keep track of the latest dataset for each provider_id

    # First pass: find the latest dataset for each provider
    for dataset_id, dataset_info in metadata.items():
        provider_id = dataset_info.get('provider_id')
        if provider_id:
            if provider_id not in latest_datasets or dataset_info['dataset_id'] > latest_datasets[provider_id]['dataset_id']:
                latest_datasets[provider_id] = dataset_info

    # Second pass: create provider entries for the latest datasets
    for provider_id, dataset_info in latest_datasets.items():
        dataset_dir = Path(dataset_info.get('download_path'))
        # Use the same provider ID construction as the main application
        sanitized_name = dataset_dir.parent.name.split('_', 1)[1] if '_' in dataset_dir.parent.name else dataset_dir.parent.name
        provider_key = f"{sanitized_name}_{provider_id}"

        providers[provider_id] = {
            'id': provider_key,
            'name': dataset_info.get('provider_name'),
            'raw_id': provider_id,
            'dataset_path': dataset_info.get('download_path')
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

@pytest.mark.parametrize("provider", get_providers_from_metadata(), ids=lambda p: p['raw_id'])
class TestProvider:
    """Test suite for provider functionality"""

    def test_load_provider(self, client, metadata_backup, provider):
        """Test loading the provider"""
        print(f"\nTesting provider: {provider['name']} ({provider['raw_id']})")
        print("  - Loading provider...")
        response = client.post(f"/provider/{provider['id']}")
        assert response.status_code == 200, f"Failed to load provider {provider['raw_id']}: {response.json()}"
        print("  ✓ Load successful")

    def test_provider_cache(self, client, metadata_backup, provider):
        """Test provider cache"""
        # First load the provider
        response = client.post(f"/provider/{provider['id']}")
        assert response.status_code == 200

        print("  - Testing cache...")
        response = client.post(f"/provider/{provider['id']}")
        assert response.status_code == 200
        assert "already loaded" in response.json().get("message", "").lower()
        print("  ✓ Cache test passed")

    def test_frontend_station_search(self, client, metadata_backup, provider):
        """Test station search with 'ab' query (used by frontend)"""
        # First load the provider
        response = client.post(f"/provider/{provider['id']}")
        assert response.status_code == 200

        print("  - Testing frontend station search (ab)...")
        response = client.get("/stations/search?query=ab")
        assert response.status_code == 200
        stations = response.json()
        if len(stations) == 0:
            print("  ⚠️ No stations found with 'ab' query - frontend dropdown might be empty")
        else:
            print(f"  ✓ Found {len(stations)} stations with 'ab' query")

    def test_random_station_search(self, client, metadata_backup, provider):
        """Test station search with random stops from the dataset"""
        # First load the provider
        response = client.post(f"/provider/{provider['id']}")
        assert response.status_code == 200

        print("  - Testing random station search...")
        # Get the provider's directory
        downloads_dir = Path(__file__).parent.parent.parent.parent.parent / "downloads"
        provider_dirs = list(downloads_dir.glob(f"*{provider['raw_id']}*"))
        assert len(provider_dirs) > 0, f"No data directory found for provider {provider['raw_id']}"

        # Get the most recent dataset directory
        dataset_dir = sorted(provider_dirs)[0]
        stops_file = dataset_dir / provider['dataset_path'] / "stops.txt"
        assert stops_file.exists(), f"No stops.txt found for provider {provider['raw_id']}"

        # Read stops from the file
        stops = []
        with open(stops_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            stops = list(reader)

        assert len(stops) > 0, f"No stops found in stops.txt for provider {provider['raw_id']}"
        print(f"  Found {len(stops)} stops in the dataset")

        # Select up to 5 random stops
        test_stops = random.sample(stops, min(5, len(stops)))
        successful_searches = 0

        for stop in test_stops:
            # Try different parts of the stop name
            stop_name = stop['stop_name']
            name_parts = stop_name.split()
            
            # Try with the full name first
            response = client.get(f"/stations/search?query={stop_name}")
            if response.status_code == 200 and len(response.json()) > 0:
                successful_searches += 1
                continue

            # Try with individual words from the name
            for part in name_parts:
                if len(part) >= 3:  # Only try parts that are at least 3 characters long
                    response = client.get(f"/stations/search?query={part}")
                    if response.status_code == 200 and len(response.json()) > 0:
                        successful_searches += 1
                        break

        assert successful_searches > 0, f"Could not find any stops by searching in provider {provider['raw_id']}"
        print(f"  ✓ Successfully found {successful_searches} out of {len(test_stops)} random stops")

    def test_station_endpoints(self, client, metadata_backup, provider):
        """Test various station-related endpoints"""
        # First load the provider
        response = client.post(f"/provider/{provider['id']}")
        assert response.status_code == 200

        print("  - Testing station endpoints...")
        # Get some stations first
        response = client.get("/stations/search?query=ab")
        assert response.status_code == 200
        stations = response.json()
        
        if len(stations) >= 2:
            # Test routes between stations
            response = client.get(f"/routes?from_station={stations[0]['id']}&to_station={stations[1]['id']}")
            assert response.status_code == 200
            routes = response.json()
            assert "routes" in routes
            assert "total_routes" in routes
            print("  ✓ Routes endpoint working")

            # Test destinations from a station
            response = client.get(f"/stations/destinations/{stations[0]['id']}")
            assert response.status_code == 200
            destinations = response.json()
            assert isinstance(destinations, list)
            print("  ✓ Destinations endpoint working")

            # Test origins for a station
            response = client.get(f"/stations/origins/{stations[0]['id']}")
            assert response.status_code == 200
            origins = response.json()
            assert isinstance(origins, list)
            print("  ✓ Origins endpoint working")

            # Test station routes
            response = client.get(f"/stations/{stations[0]['id']}/routes")
            assert response.status_code == 200
            routes = response.json()
            assert isinstance(routes, list)
            print("  ✓ Station routes endpoint working")

            # Verify that the routes contain valid data
            if len(routes) > 0:
                route = routes[0]
                assert "route_id" in route, "Route should have an ID"
                assert "route_name" in route, "Route should have a name"
                assert "stops" in route, "Route should have stops"
                assert len(route["stops"]) >= 2, "Route should have at least 2 stops"
                print("  ✓ Route data structure verified")

            # Verify that destinations and origins contain valid data
            if len(destinations) > 0:
                destination = destinations[0]
                assert "id" in destination, "Destination should have an ID"
                assert "name" in destination, "Destination should have a name"
                assert "location" in destination, "Destination should have a location"
                assert "lat" in destination["location"], "Location should have latitude"
                assert "lon" in destination["location"], "Location should have longitude"
                print("  ✓ Destination data structure verified")

            if len(origins) > 0:
                origin = origins[0]
                assert "id" in origin, "Origin should have an ID"
                assert "name" in origin, "Origin should have a name"
                assert "location" in origin, "Origin should have a location"
                assert "lat" in origin["location"], "Location should have latitude"
                assert "lon" in origin["location"], "Location should have longitude"
                print("  ✓ Origin data structure verified")
        else:
            print("  ⚠️ Not enough stations found to test endpoints")