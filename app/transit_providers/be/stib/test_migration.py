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

def test_waiting_times():
    """Test the waiting times endpoints by comparing v2 endpoint with stops_data from v1."""
    print("\n=== Testing waiting times endpoints ===")
    
    # Get v1 data from /api/data endpoint
    print("\nGetting v1 data from /api/data:")
    v1_response = requests.get("http://localhost:5001/api/data")
    if v1_response.status_code != 200:
        print(f"❌ Failed to get v1 data: {v1_response.status_code}")
        return False
        
    try:
        v1_data = v1_response.json()
        v1_stops_data = v1_data.get('stops_data', {})
        print(f"✓ Got v1 data with {len(v1_stops_data)} stops")
        
        # Print monitored stops and lines
        v1_stop_ids = set(v1_stops_data.keys())
        v1_lines = set()
        for stop in v1_stops_data.values():
            v1_lines.update(stop.get('lines', {}).keys())
        print(f"\nv1 monitored stops: {sorted(v1_stop_ids)}")
        print(f"v1 monitored lines: {sorted(v1_lines)}")
        
        # Print sample of v1 data structure
        if v1_stops_data:
            sample_stop_id = next(iter(v1_stops_data))
            print("\nv1 data structure (one stop):")
            print(json.dumps({sample_stop_id: v1_stops_data[sample_stop_id]}, indent=2))
    except Exception as e:
        print(f"❌ Error parsing v1 data: {e}")
        return False
    
    # Get v2 data
    print("\nGetting v2 data from /api/stib/waiting_times:")
    v2_response = requests.get("http://localhost:5001/api/stib/waiting_times")
    if v2_response.status_code != 200:
        print(f"❌ Failed to get v2 data: {v2_response.status_code}")
        return False
        
    try:
        v2_data = v2_response.json()
        v2_stops = v2_data.get('stops', {})
        print(f"✓ Got v2 data with {len(v2_stops)} stops")
        
        # Print monitored stops and lines
        v2_stop_ids = set(v2_stops.keys())
        v2_lines = set()
        for stop in v2_stops.values():
            v2_lines.update(stop.get('lines', {}).keys())
        print(f"\nv2 monitored stops: {sorted(v2_stop_ids)}")
        print(f"v2 monitored lines: {sorted(v2_lines)}")
        
        # Print sample of v2 data structure
        if v2_stops:
            sample_stop_id = next(iter(v2_stops))
            print("\nv2 data structure (one stop):")
            print(json.dumps({sample_stop_id: v2_stops[sample_stop_id]}, indent=2))
    except Exception as e:
        print(f"❌ Error parsing v2 data: {e}")
        return False
    
    # Compare data structures
    print("\nComparing data structures:")
    
    # Check if we have data to compare
    if not v1_stops_data:
        print("⚠️ No stops in v1 data")
        return False
    if not v2_stops:
        print("⚠️ No stops in v2 data")
        return False
        
    # Compare stop IDs
    print("\n1. Stop Coverage:")
    v1_stop_ids = set(v1_stops_data.keys())
    v2_stop_ids = set(v2_stops.keys())
    print(f"Stop IDs in v1 but not in v2: {sorted(v1_stop_ids - v2_stop_ids)}")
    print(f"Stop IDs in v2 but not in v1: {sorted(v2_stop_ids - v1_stop_ids)}")
    
    # Compare structure for common stops
    common_stops = v1_stop_ids & v2_stop_ids
    print(f"\n2. Common Stops Analysis ({len(common_stops)} stops):")
    
    if common_stops:
        sample_stop = next(iter(common_stops))
        print(f"\nDetailed comparison for stop {sample_stop}:")
        
        v1_stop = v1_stops_data[sample_stop]
        v2_stop = v2_stops[sample_stop]
        
        # Compare fields
        print("\n3. Fields Comparison:")
        v1_fields = set(v1_stop.keys())
        v2_fields = set(v2_stop.keys())
        print(f"Fields in v1 but not in v2: {v1_fields - v2_fields}")
        print(f"Fields in v2 but not in v1: {v2_fields - v1_fields}")
        
        # Compare coordinates
        print("\n4. Coordinates Comparison:")
        print(f"v1: {v1_stop.get('coordinates')}")
        print(f"v2: {v2_stop.get('coordinates')}")
        
        # Compare lines structure
        if 'lines' in v1_stop and 'lines' in v2_stop:
            print("\n5. Lines Comparison:")
            v1_lines = set(v1_stop['lines'].keys())
            v2_lines = set(v2_stop['lines'].keys())
            print(f"Lines in v1 but not in v2: {v1_lines - v2_lines}")
            print(f"Lines in v2 but not in v1: {v2_lines - v1_lines}")
            
            # Compare waiting times format for a sample line
            if v1_lines & v2_lines:
                sample_line = next(iter(v1_lines & v2_lines))
                print(f"\n6. Waiting Times Format (line {sample_line}):")
                print("\nv1:", json.dumps(v1_stop['lines'][sample_line], indent=2))
                print("\nv2:", json.dumps(v2_stop['lines'][sample_line], indent=2))
                
                # Compare waiting time fields
                if v1_stop['lines'][sample_line]:
                    v1_fields = set(next(iter(next(iter(v1_stop['lines'][sample_line].values())))).keys())
                    if v2_stop['lines'][sample_line]:
                        v2_fields = set(next(iter(next(iter(v2_stop['lines'][sample_line].values())))).keys())
                        print("\n7. Waiting Time Fields:")
                        print(f"Fields in v1 but not in v2: {v1_fields - v2_fields}")
                        print(f"Fields in v2 but not in v1: {v2_fields - v1_fields}")
                        print(f"Field order in v1: {list(v1_fields)}")
                        print(f"Field order in v2: {list(v2_fields)}")
    
    return True

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
        ("Problematic Stop Coordinates", test_problematic_stop_coordinates),
        ("Waiting Times", test_waiting_times)
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