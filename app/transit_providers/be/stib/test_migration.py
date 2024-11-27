import requests
import json
from deepdiff import DeepDiff

def test_endpoint_equivalence(old_endpoint, new_endpoint, params=None):
    """
    Test if two endpoints return equivalent data
    """
    old_response = requests.get(f"http://localhost:5000{old_endpoint}", params=params)
    new_response = requests.get(f"http://localhost:5000/api/stib{new_endpoint}", params=params)
    
    try:
        old_data = old_response.json()
        new_data = new_response.json()
        
        # Compare the responses
        diff = DeepDiff(old_data, new_data, ignore_order=True)
        
        if diff:
            print(f"\nDifferences found for {old_endpoint} vs {new_endpoint}:")
            print(json.dumps(diff, indent=2))
            return False
        else:
            print(f"\nEndpoints {old_endpoint} and {new_endpoint} return equivalent data")
            return True
            
    except json.JSONDecodeError:
        print(f"Error: One of the responses is not valid JSON")
        print(f"Old response: {old_response.text[:200]}...")
        print(f"New response: {new_response.text[:200]}...")
        return False

def run_tests():
    """
    Run all endpoint comparison tests
    """
    tests = [
        ("/api/data", "/realtime"),
        ("/api/static_data", "/static"),
        ("/api/stop_names", "/stops"),
        ("/api/stop_coordinates/1", "/stop/1/coordinates"),
        ("/api/waiting_times", "/waiting_times"),
        ("/api/messages", "/messages"),
        ("/api/vehicles", "/vehicles"),
    ]
    
    # Test specific stop coordinates
    test_stop_ids = ["1", "2", "3", "8122"]  # Added ROODEBEEK (8122)
    for stop_id in test_stop_ids:
        tests.append((f"/api/stop_coordinates/{stop_id}", f"/stop/{stop_id}/coordinates"))
    
    success = True
    for old_endpoint, new_endpoint in tests:
        if not test_endpoint_equivalence(old_endpoint, new_endpoint):
            success = False
    
    return success

if __name__ == "__main__":
    print("Starting migration tests...")
    success = run_tests()
    if success:
        print("\nAll tests passed! The new endpoints match the old ones.")
    else:
        print("\nSome tests failed. Please check the differences above.") 