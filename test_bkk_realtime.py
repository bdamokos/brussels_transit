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
    
    if 'F01111' in waiting_times:
        for arrival in waiting_times['F01111']:
            print(f"Line {arrival['line']} to {arrival['destination']}: {arrival['minutes_until']} (at {arrival['timestamp']})")
    else:
        print("No waiting times found for stop F01111")

    # Test vehicle positions
    print("\nGetting vehicle positions...")
    vehicles = await get_vehicle_positions()
    print(f"Found {len(vehicles)} vehicles for monitored lines\n")
    
    # Display first 5 vehicles
    for vehicle in vehicles[:5]:
        print(f"Vehicle {vehicle['id']}:")
        print(f"  Line: {vehicle['line']}")
        print(f"  To: {vehicle['destination']}")
        print(f"  Position: {vehicle['lat']}, {vehicle['lon']}")
        print(f"  Last update: {vehicle['timestamp']}\n")

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