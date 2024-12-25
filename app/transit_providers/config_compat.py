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
    
    logger.debug(f"Converting config for {provider_name}")
    logger.debug(f"Input config keys: {list(config.keys())}")
    logger.debug(f"Input config monitored_lines: {config.get('monitored_lines')}")
    logger.debug(f"Input config MONITORED_LINES: {config.get('MONITORED_LINES')}")
    logger.debug(f"Input config provider_specific: {config.get('provider_specific', {})}")
    
    # First resolve any paths in the config
    resolve_paths(config, app_dir)
    
    # Convert based on provider
    result = None
    if provider_name == 'stib':
        result = convert_to_stib_format(config)
    elif provider_name == 'delijn':
        result = convert_to_delijn_format(config)
    elif provider_name == 'bkk':
        result = convert_to_bkk_format(config)
    else:
        logger.warning(f"No specific conversion for provider {provider_name}, using as-is")
        result = config
    
    logger.debug(f"Converted config keys: {list(result.keys())}")
    logger.debug(f"Converted config MONITORED_LINES: {result.get('MONITORED_LINES')}")
    logger.debug(f"Converted config STOP_IDS: {result.get('STOP_IDS')}")
    return result

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
    
    This function implements a single source of truth approach:
    1. All input config uses lowercase keys
    2. Convert to uppercase only at the final step
    3. Clear separation between reading values and creating result
    """
    logger.debug(f"Converting BKK config with keys: {list(config.keys())}")
    
    # Step 1: Extract all values using lowercase keys only
    values = {
        'stop_ids': [],
        'monitored_lines': [],
        'provider_id': None,
        'api_key': None,
        'cache_dir': None,
        'gtfs_dir': None,
        'rate_limit_delay': None,
        'gtfs_cache_duration': None
    }
    
    # Get values from provider_specific first
    if 'provider_specific' in config:
        logger.debug("Reading from provider_specific")
        for key in values.keys():
            if key in config['provider_specific']:
                values[key] = config['provider_specific'][key]
    
    # Then get values from top-level config (overrides provider_specific)
    for key in values.keys():
        if key in config:
            values[key] = config[key]
    
    # Extract monitored lines from stops if not set
    if not values['monitored_lines'] and 'stops' in config:
        logger.debug("Extracting monitored lines from stops")
        lines_from_stops = set()
        for stop in config['stops']:
            if 'lines' in stop:
                lines_from_stops.update(stop['lines'].keys())
        if lines_from_stops:
            values['monitored_lines'] = sorted(lines_from_stops)
    
    # Extract stop IDs from stops if not set
    if not values['stop_ids'] and 'stops' in config:
        logger.debug("Extracting stop IDs from stops")
        values['stop_ids'] = [stop['id'] for stop in config['stops']]
    
    logger.debug(f"Extracted values: {values}")
    
    # Step 2: Convert to final format with uppercase keys
    result = {
        'STOP_IDS': values['stop_ids'],
        'MONITORED_LINES': values['monitored_lines'],
        'PROVIDER_ID': values['provider_id'],
        'API_KEY': values['api_key'],
        'CACHE_DIR': values['cache_dir'],
        'GTFS_DIR': values['gtfs_dir'],
        'RATE_LIMIT_DELAY': values['rate_limit_delay'],
        'GTFS_CACHE_DURATION': values['gtfs_cache_duration']
    }
    
    logger.debug(f"Final BKK config - MONITORED_LINES: {result['MONITORED_LINES']}, STOP_IDS: {result['STOP_IDS']}")
    return result 