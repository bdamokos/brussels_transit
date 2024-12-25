"""Backward compatibility layer for provider configurations"""

from typing import Dict, Any, List
from pathlib import Path

def convert_to_stib_format(config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert new config format to STIB's expected format
    
    STIB expects:
    {
        'STIB_STOPS': [{'id': '...', 'name': '...', 'lines': {'1': ['A', 'B']}, 'direction': '...'}],
        'API_KEY': '...',
        ...other provider-specific fields
    }
    """
    result = {}
    
    # Convert stops to STIB_STOPS format
    if 'stops' in config:
        stib_stops = []
        for stop in config['stops']:
            stib_stop = {
                'id': stop['id'],
                'name': stop.get('name'),
                'direction': stop.get('direction')
            }
            
            if 'lines' in stop:
                converted_lines = {}
                for line_id, destinations in stop['lines'].items():
                    converted_destinations = []
                    for dest in destinations:
                        if isinstance(dest, dict):
                            # Convert LineDestination back to string
                            converted_destinations.append(dest['value'])
                        else:
                            converted_destinations.append(dest)
                    converted_lines[line_id] = converted_destinations
                stib_stop['lines'] = converted_lines
            
            stib_stops.append(stib_stop)
        result['STIB_STOPS'] = stib_stops
    
    # Add provider-specific fields
    if 'provider_specific' in config:
        result.update(config['provider_specific'])
    
    return result

def convert_to_delijn_format(config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert new config format to De Lijn's expected format
    
    De Lijn expects:
    {
        'STOP_IDS': ['...', '...'],
        'MONITORED_LINES': ['...', '...'],
        'API_KEY': '...',
        ...other provider-specific fields
    }
    """
    result = {}
    
    # Extract stop IDs from stops
    if 'stops' in config:
        result['STOP_IDS'] = [stop['id'] for stop in config['stops']]
    
    # Copy monitored lines
    if 'monitored_lines' in config:
        result['MONITORED_LINES'] = config['monitored_lines']
    
    # Add provider-specific fields
    if 'provider_specific' in config:
        result.update(config['provider_specific'])
    
    return result

def convert_to_bkk_format(config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert new config format to BKK's expected format
    
    BKK expects:
    {
        'STOP_IDS': ['...', '...'],
        'MONITORED_LINES': ['...', '...'],
        'PROVIDER_ID': '...',
        ...other provider-specific fields
    }
    """
    result = {}
    
    # Extract stop IDs from stops
    if 'stops' in config:
        result['STOP_IDS'] = [stop['id'] for stop in config['stops']]
    
    # Copy monitored lines
    if 'monitored_lines' in config:
        result['MONITORED_LINES'] = config['monitored_lines']
    
    # Add provider-specific fields
    if 'provider_specific' in config:
        result.update(config['provider_specific'])
    
    return result

def convert_to_provider_format(provider: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert new config format to provider-specific format"""
    converters = {
        'stib': convert_to_stib_format,
        'delijn': convert_to_delijn_format,
        'bkk': convert_to_bkk_format
    }
    
    converter = converters.get(provider.lower())
    if not converter:
        raise ValueError(f"No converter found for provider: {provider}")
    
    return converter(config) 