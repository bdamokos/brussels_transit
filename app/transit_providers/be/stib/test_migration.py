import requests
import json
from deepdiff import DeepDiff
import sys

def print_response_details(response, endpoint_name, max_length=500):
    """Print detailed information about a response"""
    print(f"\n{endpoint_name} Response Details:")
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    print("Content (truncated):")
    content = response.text[:max_length] + "..." if len(response.text) > max_length else response.text
    print(content)

def test_endpoint(endpoint, method="GET", data=None, expected_status=200):
    """Test a single endpoint with detailed output"""
    print(f"\nTesting endpoint: {endpoint}")
    print(f"Method: {method}")
    if data:
        print(f"Request data: {data}")
        
    try:
        if method == "GET":
            response = requests.get(f"http://localhost:5001{endpoint}")
        else:
            response = requests.post(f"http://localhost:5001{endpoint}", json=data)
            
        print_response_details(response, endpoint)
        
        if response.status_code != expected_status:
            print(f"❌ Unexpected status code: {response.status_code} (expected {expected_status})")
            return False
            
        try:
            response.json()
            print("✓ Response is valid JSON")
            return True
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON response: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False

def test_static_data():
    """Test the /api/static_data endpoint"""
    print("\n=== Testing /api/static_data ===")
    return test_endpoint("/api/static_data")

def test_stop_names():
    """Test the /api/stop_names endpoint"""
    print("\n=== Testing /api/stop_names ===")
    test_data = ["8122", "8032"]  # Test with ROODEBEEK and another stop
    return test_endpoint("/api/stop_names", method="POST", data=test_data)

def test_stop_coordinates():
    """Test the /api/stop_coordinates/{id} endpoint"""
    print("\n=== Testing /api/stop_coordinates/{id} ===")
    success = True
    test_stops = {
        "8122": "ROODEBEEK",
        "8032": "Another known stop",
        "1": "Edge case - low number",
        "999999": "Edge case - invalid stop"
    }
    
    for stop_id, description in test_stops.items():
        print(f"\nTesting stop {stop_id} ({description})")
        if not test_endpoint(f"/api/stop_coordinates/{stop_id}"):
            success = False
            
    return success

def test_stib_config():
    """Test the /api/stib/config endpoint"""
    print("\n=== Testing /api/stib/config ===")
    return test_endpoint("/api/stib/config")

def test_stib_route():
    """Test the /api/stib/route/{id} endpoint"""
    print("\n=== Testing /api/stib/route/{id} ===")
    success = True
    test_routes = {
        "1": "Metro line 1",
        "92": "Tram line 92",
        "999": "Edge case - invalid line"
    }
    
    for route_id, description in test_routes.items():
        print(f"\nTesting route {route_id} ({description})")
        if not test_endpoint(f"/api/stib/route/{route_id}"):
            success = False
            
    return success

def test_stib_stops():
    """Test the /api/stib/stops endpoint"""
    print("\n=== Testing /api/stib/stops ===")
    test_data = ["8122", "8032"]  # Test with ROODEBEEK and another stop
    return test_endpoint("/api/stib/stops", method="POST", data=test_data)

def test_stib_stop_coordinates():
    """Test the /api/stib/stop/{id}/coordinates endpoint"""
    print("\n=== Testing /api/stib/stop/{id}/coordinates ===")
    success = True
    test_stops = {
        "8122": "ROODEBEEK",
        "8032": "Another known stop",
        "1": "Edge case - low number",
        "999999": "Edge case - invalid stop"
    }
    
    for stop_id, description in test_stops.items():
        print(f"\nTesting stop {stop_id} ({description})")
        if not test_endpoint(f"/api/stib/stop/{stop_id}/coordinates"):
            success = False
            
    return success

def test_problematic_stop_coordinates():
    """Test stop coordinates for stops that were previously returning null."""
    print("\n=== Testing problematic stop coordinates ===")
    
    # Test stops from line 92 that had null coordinates
    test_stops = {
        "6934F": "Line 92 stop with null coordinates",
        "5053G": "Another line 92 stop with null coordinates",
        "8122": "ROODEBEEK (known working stop, for comparison)"
    }
    
    success = True
    for stop_id, description in test_stops.items():
        print(f"\nTesting stop {stop_id} ({description})")
        
        # Test v2 endpoint
        print("\nTesting v2 endpoint:")
        if not test_endpoint(f"/api/stib/stop/{stop_id}/coordinates"):
            success = False
            
        # Test v1 endpoint for comparison
        print("\nTesting v1 endpoint:")
        if not test_endpoint(f"/api/stop_coordinates/{stop_id}"):
            success = False
            
    return success

def main():
    """Test endpoints one by one"""
    tests = [
        ("Static Data", test_static_data),
        ("Stop Names", test_stop_names),
        ("Stop Coordinates", test_stop_coordinates),
        ("STIB Config", test_stib_config),
        ("STIB Route", test_stib_route),
        ("STIB Stops", test_stib_stops),
        ("STIB Stop Coordinates", test_stib_stop_coordinates),
        ("Problematic Stop Coordinates", test_problematic_stop_coordinates)
    ]
    
    if len(sys.argv) > 1:
        # Test specific endpoint if provided as argument
        test_name = sys.argv[1].lower().replace(" ", "_")
        for name, func in tests:
            if name.lower().replace(" ", "_") == test_name:
                success = func()
                sys.exit(0 if success else 1)
        print(f"Unknown test: {sys.argv[1]}")
        print("Available tests:")
        for name, _ in tests:
            print(f"  {name}")
        sys.exit(1)
    
    # Test all endpoints in sequence
    for name, func in tests:
        print(f"\n{'='*50}")
        print(f"Testing {name}")
        print('='*50)
        success = func()
        if not success:
            print(f"\n❌ {name} test failed")
            print("Stopping tests here to fix this endpoint first")
            sys.exit(1)
        print(f"\n✓ {name} test passed")
    
    print("\n✓ All tests passed!")

if __name__ == "__main__":
    main() 