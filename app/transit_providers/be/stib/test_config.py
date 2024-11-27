#!/usr/bin/env python3
"""Test configuration precedence for STIB provider."""

import json
from pathlib import Path
from datetime import timedelta
import os

def print_config(name: str, config: dict) -> None:
    """Print a configuration in a readable format."""
    print(f"\n=== {name} ===")
    
    if 'STIB_STOPS' in config:
        stops = config['STIB_STOPS']
        print(f"\nFound {len(stops)} stops:")
        for stop in stops:
            print(f"- {stop['id']} ({stop['name']})")
            print(f"  Lines: {list(stop['lines'].keys())}")
            print(f"  Direction: {stop['direction']}")

def main():
    """Test configuration precedence."""
    print("Testing STIB configuration precedence...")
    
    # Get provider defaults (from stib/config.py)
    from . import config as stib_config
    print_config("Provider Defaults (stib/config.py)", stib_config.DEFAULT_CONFIG)
    
    # Get global defaults (from config/default.py)
    from config import default as default_config
    print_config("Global Defaults (config/default.py)", {'STIB_STOPS': default_config.STIB_STOPS})
    
    # Get local config if it exists
    try:
        from config import local as local_config
        if hasattr(local_config, 'STIB_STOPS'):
            print_config("Local Config (config/local.py)", {'STIB_STOPS': local_config.STIB_STOPS})
            local_stops = {stop['id'] for stop in local_config.STIB_STOPS}
        else:
            print("\n=== Local Config (config/local.py) ===\nNo STIB_STOPS defined")
            local_stops = set()
    except ImportError:
        print("\n=== Local Config (config/local.py) ===\nFile not found")
        local_stops = set()
    
    # Get merged config
    from transit_providers.config import get_provider_config
    merged_config = get_provider_config('stib')
    print_config("Merged Config (get_provider_config)", merged_config)
    
    # Compare stops
    provider_stops = {stop['id'] for stop in stib_config.DEFAULT_CONFIG['STIB_STOPS']}
    global_stops = {stop['id'] for stop in default_config.STIB_STOPS}
    merged_stops = {stop['id'] for stop in merged_config['STIB_STOPS']}
    
    print("\n=== Stop ID Analysis ===")
    print(f"Provider default stops: {provider_stops}")
    print(f"Global default stops: {global_stops}")
    print(f"Local config stops: {local_stops}")
    print(f"Merged config stops: {merged_stops}")
    
    if provider_stops == global_stops:
        print("\n⚠️ Provider and global defaults use the same stop IDs!")
    else:
        print("\n✓ Provider and global defaults use different stop IDs")
        
    if merged_stops == provider_stops:
        print("Final config uses provider defaults")
    elif merged_stops == global_stops:
        print("Final config uses global defaults")
    elif merged_stops == local_stops:
        print("Final config uses local config")
    else:
        print("Final config uses a different set of stops")
        if local_stops:
            print("(local.py is present but merged config doesn't match any single source)")
        else:
            print("(unexpected - doesn't match any config source)")

if __name__ == "__main__":
    main() 