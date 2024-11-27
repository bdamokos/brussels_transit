import os
import json
import requests
from datetime import datetime
from deepdiff import DeepDiff
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BASE_URL = "http://localhost:5001"
API_KEY = os.getenv('STIB_API_KEY')

if not API_KEY:
    logger.warning("STIB_API_KEY environment variable not set")

def test_source_consistency():
    """Test that source information is consistently included in responses."""
    print("\n=== Testing Source Information Consistency ===")
    
    # Test single stop coordinates
    print("\n1. Testing /stop/{id}/coordinates endpoint")
    response = requests.get(f"{BASE_URL}/api/stib/stop/8122/coordinates")
    if response.ok:
        data = response.json()
        if '_metadata' in data:
            print("✓ Has _metadata")
            print(f"  Source: {data['_metadata'].get('source')}")
            if data['_metadata'].get('warning'):
                print(f"  Warning: {data['_metadata']['warning']}")
        else:
            print("✗ Missing _metadata")
    else:
        print(f"✗ Request failed: {response.status_code}")

    # Test multiple stops
    print("\n2. Testing /stops endpoint")
    response = requests.post(
        f"{BASE_URL}/api/stib/stops",
        json=["8122", "8032"]
    )
    if response.ok:
        data = response.json()
        if '_metadata' in data and 'sources' in data['_metadata']:
            print("✓ Has _metadata.sources")
            for stop_id, metadata in data['_metadata']['sources'].items():
                print(f"  Stop {stop_id}:")
                print(f"    Source: {metadata.get('source')}")
                if metadata.get('warning'):
                    print(f"    Warning: {metadata['warning']}")
        else:
            print("✗ Missing _metadata.sources")
    else:
        print(f"✗ Request failed: {response.status_code}")

    # Test single stop details
    print("\n3. Testing /stop/{id} endpoint")
    response = requests.get(f"{BASE_URL}/api/stib/stop/8122")
    if response.ok:
        data = response.json()
        if '_metadata' in data:
            print("✓ Has _metadata")
            print(f"  Source: {data['_metadata'].get('source')}")
            if data['_metadata'].get('warning'):
                print(f"  Warning: {data['_metadata']['warning']}")
        else:
            print("✗ Missing _metadata")
    else:
        print(f"✗ Request failed: {response.status_code}")

def test_all_endpoints():
    """Test all v2 endpoints."""
    print("\n=== Testing All v2 Endpoints ===")
    
    endpoints = {
        'config': {'method': 'GET', 'url': '/api/stib/config'},
        'data': {'method': 'GET', 'url': '/api/stib/data'},
        'stops': {'method': 'POST', 'url': '/api/stib/stops', 'data': ['8122', '8032']},
        'stop': {'method': 'GET', 'url': '/api/stib/stop/8122'},
        'route': {'method': 'GET', 'url': '/api/stib/route/1'},
        'colors': {'method': 'GET', 'url': '/api/stib/colors/1'},
        'vehicles': {'method': 'GET', 'url': '/api/stib/vehicles'},
        'messages': {'method': 'GET', 'url': '/api/stib/messages'},
        'waiting_times': {'method': 'GET', 'url': '/api/stib/waiting_times'},
        'get_stop_by_name': {'method': 'GET', 'url': '/api/stib/get_stop_by_name?name=roodebeek'},
        'get_nearest_stops': {'method': 'GET', 'url': '/api/stib/get_nearest_stops?lat=50.8466&lon=4.3528'},
        'search_stops': {'method': 'GET', 'url': '/api/stib/search_stops?query=roodebeek'},
        'static': {'method': 'GET', 'url': '/api/stib/static'},
        'realtime': {'method': 'GET', 'url': '/api/stib/realtime'}
    }
    
    results = {}
    for name, endpoint in endpoints.items():
        print(f"\nTesting {name} endpoint...")
        try:
            if endpoint['method'] == 'GET':
                response = requests.get(f"{BASE_URL}{endpoint['url']}")
            else:  # POST
                response = requests.post(f"{BASE_URL}{endpoint['url']}", json=endpoint.get('data'))
            
            if response.ok:
                print(f"✓ {name}: {response.status_code}")
                results[name] = True
            else:
                print(f"✗ {name}: {response.status_code}")
                print(f"  Error: {response.text}")
                results[name] = False
        except Exception as e:
            print(f"✗ {name}: Error - {str(e)}")
            results[name] = False
    
    # Print summary
    print("\n=== Endpoint Test Summary ===")
    working = [name for name, result in results.items() if result]
    not_working = [name for name, result in results.items() if not result]
    
    print(f"\nWorking endpoints ({len(working)}/{len(endpoints)}):")
    for name in working:
        print(f"✓ {name}")
    
    if not_working:
        print(f"\nNon-working endpoints ({len(not_working)}/{len(endpoints)}):")
        for name in not_working:
            print(f"✗ {name}")

def main():
    """Run all tests."""
    # First test source consistency
    test_source_consistency()
    
    # Then test all endpoints
    test_all_endpoints()

if __name__ == "__main__":
    main() 