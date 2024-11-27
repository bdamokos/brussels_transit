import sys
import os
import asyncio
import json
import httpx
from deepdiff import DeepDiff

# Add the app directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from config import get_required_config

# Get configuration values
API_KEY = get_required_config('STIB_API_KEY')
API_CONFIG = get_required_config('API_CONFIG')
WAITING_TIMES_API_URL = f"{API_CONFIG['STIB_API_URL']}/waiting-time-rt-production/records"

async def get_client():
    """Get an HTTP client with proper configuration."""
    return httpx.AsyncClient(
        timeout=30.0,
        verify=False  # For testing only
    )

def print_response_details(response, endpoint_name, max_length=500):
    """Print details about an HTTP response."""
    print(f"\n{endpoint_name} Response Details:")
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {response.headers}")
    
    if hasattr(response, 'text'):
        content = response.text
        if len(content) > max_length:
            content = content[:max_length] + "..."
        print(f"Content (truncated):\n{content}")

def normalize_stop_id(stop_id: str) -> str:
    """Remove any suffix (letters) from a stop ID.
    
    Args:
        stop_id: The stop ID to normalize (e.g., "5710F")
        
    Returns:
        The normalized stop ID (e.g., "5710")
    """
    # Remove any non-digit characters from the end of the stop ID
    return ''.join(c for c in stop_id if c.isdigit())

async def test_raw_waiting_times():
    """Test raw waiting times response from STIB API."""
    print("\n=== Testing raw waiting times response ===\n")
    
    # Test stops from GTFS data with their original IDs
    test_stops = [
        "5611",  # MUSEE D'IXELLES
        "5700G", # DE WAND
        "5710F", # VERBOEKHOVEN
        "5735",  # GILLON
        "5740",  # VERBOEKHOVEN (without suffix)
    ]
    
    # Build API query with normalized stop IDs
    params = {
        'apikey': API_KEY,
        'limit': 100,
        'select': 'pointid,lineid,passingtimes',
        'where': ' or '.join(f'pointid="{normalize_stop_id(stop_id)}"' for stop_id in test_stops)
    }
    
    print("Testing stops:", test_stops)
    print("\nAPI Query parameters:")
    print(json.dumps(params, indent=2))
    
    async with await get_client() as client:
        response = await client.get(WAITING_TIMES_API_URL, params=params)
        print(f"\nResponse status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("\nRaw response data:")
            print(json.dumps(data, indent=2))
            
            if 'results' in data:
                print(f"\nFound {len(data['results'])} records")
                for record in data.get('results', []):
                    stop_id = record.get('pointid')
                    line_id = record.get('lineid')
                    print(f"\nStop {stop_id}, Line {line_id}:")
                    passing_times = record.get('passingtimes')
                    if isinstance(passing_times, str):
                        passing_times = json.loads(passing_times)
                    if passing_times:
                        for pt in passing_times:
                            dest = pt.get('destination', {})
                            if isinstance(dest, dict):
                                dest = dest.get('fr', 'Unknown')
                            print(f"  -> {dest} at {pt.get('expectedArrivalTime')}")
        else:
            print("Error response:", response.text)
            return False
    
    return True

async def main():
    """Run all tests."""
    await test_raw_waiting_times()

if __name__ == "__main__":
    asyncio.run(main()) 