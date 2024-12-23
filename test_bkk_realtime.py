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
    print("Waiting times for stop F00583 (Raktár utca):\n")
    
    if 'F00583' in waiting_times:
        stop_data = waiting_times['F00583']
        for line_id, line_data in stop_data['lines'].items():
            print(f"Line {line_id}:")
            for destination, arrivals in line_data.items():
                print(f"  To {destination}:")
                for arrival in arrivals:
                    print(f"    Arriving in {arrival['minutes']}' (scheduled: {arrival['scheduled']})")
    else:
        print("No waiting times found for stop F00583")

    # Test vehicle positions
    print("\nGetting vehicle positions...")
    vehicles = await get_vehicle_positions()
    print(f"Found {len(vehicles)} vehicles for monitored lines\n")
    
    # Display first 5 vehicles
    for i, vehicle in enumerate(vehicles[:5]):
        print(f"Vehicle {vehicle['vehicle_id']}:")
        print(f"  Line: {vehicle['line']}")
        print(f"  To: {vehicle['destination']}")
        print(f"  Position: {vehicle['position']}")
        print(f"  Last update: {vehicle['timestamp']}\n")

    # Test service alerts
    print("Getting service alerts...")
    alerts = await get_service_alerts()
    print(f"Found {len(alerts)} relevant service alerts\n")
    
    # Display first 10 alerts
    for alert in alerts[:10]:
        print(f"Alert: {alert['title']}")
        print(f"Description: {alert['description']}")
        print(f"Affects: {alert['affected_entities']}")
        print(f"Active period: {alert['active_period']}\n")

if __name__ == "__main__":
    asyncio.run(main()) 