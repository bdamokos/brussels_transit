import asyncio
import json
from app.transit_providers.hu.bkk.api import get_vehicle_positions

async def main():
    vehicles = await get_vehicle_positions()
    if not vehicles:
        print("No vehicles found")
        return
        
    # Print details of the first vehicle
    vehicle = vehicles[0]
    # Convert bytes to hex string for JSON serialization
    vehicle['raw_bytes'] = vehicle['raw_bytes'].hex()
    print("First vehicle details:")
    print(json.dumps(vehicle, indent=2))
    
    # Print BKK-specific fields if available
    if 'bkk_specific' in vehicle:
        print("\nBKK-specific fields:")
        print(json.dumps(vehicle['bkk_specific'], indent=2))

if __name__ == "__main__":
    asyncio.run(main()) 