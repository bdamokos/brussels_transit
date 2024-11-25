import asyncio
import httpx
import json
from pprint import pprint

DELIJN_STOP_ID = "307250"

async def test_endpoints():
    async with httpx.AsyncClient() as client:
        # Test all endpoints and save responses
        endpoints = {
            # STIB endpoints
            'static_data': {'url': 'http://localhost:5001/api/static_data', 'method': 'GET'},
            'data': {'url': 'http://localhost:5001/api/data', 'method': 'GET'},
            'stop_coordinates': {'url': 'http://localhost:5001/api/stop_coordinates/2100', 'method': 'GET'},
            'stop_names': {
                'url': 'http://localhost:5001/api/stop_names',
                'method': 'POST',
                'json': ['2100', '6464']
            },
            
            # De Lijn endpoints
            'delijn_config': {'url': 'http://localhost:5001/api/delijn/config', 'method': 'GET'},
            'delijn_data': {'url': 'http://localhost:5001/api/delijn/data', 'method': 'GET'},
            'delijn_stop_details': {'url': f'http://localhost:5001/api/delijn/stops/{DELIJN_STOP_ID}', 'method': 'GET'},
            'delijn_line_route': {'url': 'http://localhost:5001/api/delijn/lines/272/route', 'method': 'GET'},
            'delijn_line_colors': {'url': 'http://localhost:5001/api/delijn/lines/272/colors', 'method': 'GET'},
            'delijn_messages': {'url': 'http://localhost:5001/api/delijn/messages', 'method': 'GET'},
            'delijn_vehicles': {'url': 'http://localhost:5001/api/delijn/vehicles/272', 'method': 'GET'}
        }

        results = {}
        for name, endpoint in endpoints.items():
            try:
                if endpoint['method'] == 'GET':
                    response = await client.get(endpoint['url'])
                else:  # POST
                    response = await client.post(endpoint['url'], json=endpoint.get('json'))
                
                results[name] = {
                    'status': response.status_code,
                    'data': response.json() if response.status_code == 200 else response.text
                }
            except Exception as e:
                results[name] = {
                    'status': 'error',
                    'data': str(e)
                }

        # Save results to a file
        with open('api_test_results.json', 'w') as f:
            json.dump(results, f, indent=2)

        # Print results
        print("\nAPI Test Results:")
        for name, result in results.items():
            print(f"\n=== {name} ===")
            print(f"Status: {result['status']}")
            if result['status'] == 200:
                pprint(result['data'])
            else:
                print(f"Error: {result['data']}")

if __name__ == "__main__":
    asyncio.run(test_endpoints()) 