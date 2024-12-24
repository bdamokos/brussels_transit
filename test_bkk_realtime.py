"""Test BKK real-time data retrieval"""

import asyncio
import logging
from datetime import datetime, timezone
from app.transit_providers.hu.bkk.api import (
    get_static_data,
    get_waiting_times,
    get_vehicle_positions,
    get_service_alerts
)

# Configure logging
logging.basicConfig(level=logging.INFO)

async def main():
    print("\nTesting BKK real-time data retrieval...\n")

    # Test static data
    print("Getting static data...")
    try:
        static_data = await get_static_data()
        print(f"Static data: {static_data}")
    except Exception as e:
        print(f"Error getting static data: {e}")
        print("Static data: {'error': 'Could not access GTFS data'}")

    # Test waiting times
    print("\nGetting waiting times...")
    waiting_times = await get_waiting_times()
    print("Waiting times for stop F01111 (Wesselényi utca / Erzsébet körút):\n")
    
    if 'stops_data' in waiting_times:
        if 'F01111' in waiting_times['stops_data']:
            stop_data = waiting_times['stops_data']['F01111']
            print(f"Stop name: {stop_data['name']}")
            if stop_data.get('lines', {}):
                for line_id, line_data in stop_data['lines'].items():
                    if line_id != '_metadata':
                        print(f"\nLine {line_data.get('_metadata', {}).get('route_short_name', line_id)}:")
                        for destination, times in line_data.items():
                            if destination != '_metadata':
                                print(f"  To {destination}:")
                                for time in times:
                                    print(f"    {time.get('realtime_time', 'N/A')} ({time.get('realtime_minutes', 'N/A')})")
            else:
                print("No waiting times available")
        else:
            print("Stop F01111 not found in response")
    else:
        print("No stops data available")

    # Test vehicle positions
    print("\nGetting vehicle positions...")
    vehicles = await get_vehicle_positions()
    print(f"Found {len(vehicles)} vehicles for monitored lines\n")
    
    # Display first 5 vehicles
    for vehicle in vehicles[:5]:
        print(f"Vehicle {vehicle.get('id', 'N/A')}:")
        print(f"  Line: {vehicle.get('line', 'N/A')}")
        print(f"  To: {vehicle.get('destination', 'N/A')}")
        if 'bkk_specific' in vehicle:
            print(f"  Model: {vehicle['bkk_specific'].get('vehicle_model', 'N/A')}")
            print(f"  Door open: {vehicle['bkk_specific'].get('door_open', 'N/A')}")
            print(f"  Stop distance: {vehicle['bkk_specific'].get('stop_distance', 'N/A')}")
        print()

    # Test service alerts
    print("Getting service alerts...")
    alerts = await get_service_alerts()
    print(f"Found {len(alerts)} relevant service alerts\n")
    
    # Display first 10 alerts
    for alert in alerts[:10]:
        print(f"Alert: {alert['title']}")
        print(f"Description: {alert['description']}")
        print(f"Affects lines: {alert['lines']}")
        if alert['start']:
            print(f"Start: {alert['start']}")
        if alert['end']:
            print(f"End: {alert['end']}")
        print()

if __name__ == "__main__":
    asyncio.run(main()) 