import asyncio
import json
import httpx
from google.transit import gtfs_realtime_pb2
from google.protobuf import json_format
from app.transit_providers.hu.bkk.api import get_vehicle_positions, VEHICLE_POSITIONS_URL

async def main():
    # First get raw protobuf data
    async with httpx.AsyncClient() as client:
        response = await client.get(VEHICLE_POSITIONS_URL)
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        
        # Print raw data of first vehicle
        if feed.entity:
            print("\nRaw protobuf data of first vehicle:")
            print("=================================")
            raw_msg = json_format.MessageToDict(
                feed.entity[0].vehicle,
                preserving_proto_field_name=True,
                use_integers_for_enums=True
            )
            print(json.dumps(raw_msg, indent=2))
            
            # Also print the raw bytes
            print("\nRaw bytes of vehicle descriptor:")
            print("==============================")
            raw_bytes = feed.entity[0].vehicle.vehicle.SerializeToString()
            print(raw_bytes.hex())
            
            # Print the raw message of the vehicle descriptor
            print("\nRaw protobuf data of vehicle descriptor:")
            print("=====================================")
            raw_vehicle = json_format.MessageToDict(
                feed.entity[0].vehicle.vehicle,
                preserving_proto_field_name=True,
                use_integers_for_enums=True
            )
            print(json.dumps(raw_vehicle, indent=2))
            
            # Try to parse the raw bytes to find extension fields
            print("\nParsing raw bytes for extension fields:")
            print("=====================================")
            # Split the hex string into bytes
            hex_bytes = bytes.fromhex(raw_bytes.hex())
            # Print each byte with its position
            for i, b in enumerate(hex_bytes):
                print(f"Position {i:3d}: {b:02x} ({b:3d})")
    
    # Get vehicles from our parser
    vehicles = await get_vehicle_positions()
    
    if not vehicles:
        print("\nNo vehicles found")
        return
        
    # Print details of the first vehicle
    vehicle = vehicles[0]
    print("\nParsed vehicle details:")
    print("=====================")
    # Convert raw bytes to hex before serializing
    if 'raw_bytes' in vehicle:
        vehicle['raw_bytes'] = vehicle['raw_bytes'].hex()
    print(json.dumps(vehicle, indent=2))
    
    # Print BKK-specific fields if available
    if 'bkk_specific' in vehicle:
        print("\nBKK-specific fields:")
        print("===================")
        print(json.dumps(vehicle['bkk_specific'], indent=2))

if __name__ == "__main__":
    asyncio.run(main()) 