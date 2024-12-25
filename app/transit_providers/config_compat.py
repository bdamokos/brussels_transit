"""Backward compatibility layer for provider configuration"""

from pathlib import Path
from typing import Dict, Any, List, Union
import logging

logger = logging.getLogger(__name__)

def convert_path(path_value: Union[str, Path], app_dir: Path) -> Path:
    """Convert a path value to an absolute Path object relative to app_dir"""
    if isinstance(path_value, (str, Path)):
        # If it's already an absolute path, return it
        if isinstance(path_value, Path) and path_value.is_absolute():
            return path_value
        # Otherwise, make it relative to app_dir
        return app_dir / str(path_value)
    return path_value

def resolve_paths(config: Dict[str, Any], app_dir: Path) -> None:
    """Recursively resolve all path values in a config dictionary"""
    for key, value in config.items():
        if isinstance(value, dict):
            resolve_paths(value, app_dir)
        elif isinstance(value, (str, Path)) and ('DIR' in key or 'FILE' in key):
            config[key] = convert_path(value, app_dir)

def convert_to_provider_format(provider_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert new configuration format to provider-specific format"""
    app_dir = Path(__file__).parent.parent  # Get the app directory
    
    # First resolve any paths in the config
    resolve_paths(config, app_dir)
    
    # Convert based on provider
    if provider_name == 'stib':
        return convert_to_stib_format(config)
    elif provider_name == 'delijn':
        return convert_to_delijn_format(config)
    elif provider_name == 'bkk':
        return convert_to_bkk_format(config)
    else:
        logger.warning(f"No specific conversion for provider {provider_name}, using as-is")
        return config

def convert_to_stib_format(config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert configuration to STIB format"""
    result = {
        'STIB_STOPS': [],
        'provider_specific': config.get('provider_specific', {})
    }
    
    # Convert stops to legacy format
    for stop in config.get('stops', []):
        legacy_stop = {
            'id': stop['id'],
            'name': stop['name'],
            'lines': {},
            'direction': stop.get('direction', 'City')  # Default to 'City' if not specified
        }
        
        # Convert lines to legacy format
        for line_id, destinations in stop.get('lines', {}).items():
            legacy_stop['lines'][line_id] = []
            for dest in destinations:
                if isinstance(dest, dict):
                    legacy_stop['lines'][line_id].append(dest['value'])
                else:
                    legacy_stop['lines'][line_id].append(dest)
        
        result['STIB_STOPS'].append(legacy_stop)
    
    return result

def convert_to_delijn_format(config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert configuration to De Lijn format"""
    result = {
        'STOP_IDS': [],
        'MONITORED_LINES': config.get('monitored_lines', [])
    }
    
    # Add provider-specific config
    result.update(config.get('provider_specific', {}))
    
    # Extract stop IDs
    for stop in config.get('stops', []):
        result['STOP_IDS'].append(stop['id'])
    
    return result

def convert_to_bkk_format(config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert configuration to BKK format
    
    Convert from new format:
    {
        'provider_specific': {
            'PROVIDER_ID': '...',
            'API_KEY': '...',
            'CACHE_DIR': Path('...'),
            'GTFS_DIR': Path('...')
        },
        'stops': [{'id': '...', 'name': '...', 'lines': {...}}],
        'monitored_lines': ['...']
    }
    
    To old format:
    {
        'STOP_IDS': ['...'],
        'MONITORED_LINES': ['...'],
        'PROVIDER_ID': '...',
        'API_KEY': '...',
        'CACHE_DIR': Path('...'),
        'GTFS_DIR': Path('...'),
        'RATE_LIMIT_DELAY': float,
        'GTFS_CACHE_DURATION': int
    }
    """
    # Define exactly what fields we want in the output
    result = {
        'STOP_IDS': [],
        'MONITORED_LINES': [],
        'PROVIDER_ID': None,
        'API_KEY': None,
        'CACHE_DIR': None,
        'GTFS_DIR': None,
        'RATE_LIMIT_DELAY': None,
        'GTFS_CACHE_DURATION': None
    }
    
    # Copy only the fields we want from provider_specific
    if 'provider_specific' in config:
        for key in result.keys():
            if key in config['provider_specific']:
                result[key] = config['provider_specific'][key]
    
    # Extract stop IDs from stops
    if 'stops' in config:
        result['STOP_IDS'] = [stop['id'] for stop in config['stops']]
    
    # Copy monitored lines
    if 'monitored_lines' in config:
        result['MONITORED_LINES'] = config['monitored_lines']
    
    return result 