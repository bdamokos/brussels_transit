#!/usr/bin/env python3

import os
from typing import Dict, List, Optional

# Configuration
API_KEY = os.getenv('STIB_API_KEY')
BASE_URL = "http://localhost:5001"

def generate_curl_command(
    endpoint: str,
    method: str = "GET",
    data: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None
) -> str:
    """Generate a curl command for the given endpoint."""
    cmd_parts = ["curl"]
    
    # Add method if not GET
    if method != "GET":
        cmd_parts.append(f"-X {method}")
    
    # Add headers
    if headers:
        for key, value in headers.items():
            cmd_parts.append(f'-H "{key}: {value}"')
    
    # Add data if present
    if data:
        cmd_parts.append(f"-d '{data}'")
    
    # Add URL
    cmd_parts.append(f'"{BASE_URL}{endpoint}"')
    
    return " \\\n  ".join(cmd_parts)

def print_section(title: str):
    """Print a section title."""
    print(f"\n{'='*80}")
    print(f"# {title}")
    print(f"{'='*80}\n")

def main():
    if not API_KEY:
        print("Warning: STIB_API_KEY environment variable not set")
        print("Set it with: export STIB_API_KEY='your_api_key_here'\n")
    
    # Core Endpoints
    print_section("Core Endpoints")
    
    # Configuration
    print("# Configuration")
    print(generate_curl_command("/api/stib/config"))
    print()
    
    # Stop Data
    print("# Stop Names")
    print("## v1")
    print(generate_curl_command(
        "/api/stop_names",
        method="POST",
        headers={"Content-Type": "application/json"},
        data='["8122", "8032"]'
    ))
    print("\n## v2")
    print(generate_curl_command(
        "/api/stib/stops",
        method="POST",
        headers={"Content-Type": "application/json"},
        data='["8122", "8032"]'
    ))
    print()
    
    # Stop Coordinates
    print("# Stop Coordinates")
    print("## v1")
    print(generate_curl_command("/api/stop_coordinates/8122"))
    print("\n## v2")
    print(generate_curl_command("/api/stib/stop/8122/coordinates"))
    print()
    
    # Real-time Data
    print_section("Real-time Data")
    
    # Waiting Times
    print("# Waiting Times")
    print("## v1")
    print(generate_curl_command("/api/waiting_times"))
    print("\n## v2")
    print(generate_curl_command("/api/stib/waiting_times"))
    print()
    
    # Vehicle Positions
    print("# Vehicle Positions")
    print("## v1")
    print(generate_curl_command("/api/vehicles"))
    print("\n## v2")
    print(generate_curl_command("/api/stib/vehicles"))
    print()
    
    # Service Messages
    print("# Service Messages")
    print("## v1")
    print(generate_curl_command("/api/messages"))
    print("\n## v2")
    print(generate_curl_command("/api/stib/messages"))
    print()
    
    # Aggregated Data
    print_section("Aggregated Data")
    
    # All Real-time Data
    print("# All Real-time Data")
    print("## v1")
    print(generate_curl_command("/api/data"))
    print("\n## v2")
    print(generate_curl_command("/api/stib/realtime"))
    print()
    
    # Static Data
    print("# Static Data")
    print("## v1")
    print(generate_curl_command("/api/static_data"))
    print("\n## v2")
    print(generate_curl_command("/api/stib/static"))
    print()
    
    # Search Endpoints
    print_section("Search Endpoints")
    
    # Find Stop by Name
    print("# Find Stop by Name (v2 only)")
    print(generate_curl_command("/api/stib/get_stop_by_name?name=roodebeek&limit=5"))
    print()
    
    # Find Nearest Stops
    print("# Find Nearest Stops (v2 only)")
    print(generate_curl_command("/api/stib/get_nearest_stops?lat=50.8466&lon=4.3528&limit=5"))
    print()
    
    # Route Data
    print_section("Route Data")
    
    # Route Colors
    print("# Route Colors")
    print("## v2")
    print(generate_curl_command("/api/stib/colors/1")) # 1 is the route number
    print()
    
    # Route Data
    print("# Route Data")
    print("## v2")
    print(generate_curl_command("/api/stib/route/1"))
    print()

if __name__ == "__main__":
    main()
