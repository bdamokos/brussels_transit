# app/transit_providers/config.py

from typing import Dict, Any
from config import get_config
from logging.config import dictConfig
import logging
from copy import deepcopy

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('transit_providers.config')

# Registry for provider default configurations
PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {}

def deep_update(base_dict: Dict, update_dict: Dict) -> Dict:
    """Recursively update a dictionary, preserving nested structures"""
    result = deepcopy(base_dict)
    for key, value in update_dict.items():
        if isinstance(value, dict) and key in result and isinstance(result[key], dict):
            result[key] = deep_update(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result

def register_provider_config(provider_name: str, default_config: Dict[str, Any]) -> None:
    """Register a provider's default configuration"""
    PROVIDER_DEFAULTS[provider_name] = default_config
    logger.debug(f"Registered default config for {provider_name}")

def get_provider_config(provider_name: str) -> Dict[str, Any]:
    """Get merged configuration for a provider (following precedence order from least to most important:
    1. Provider defaults (least important)
    2. default.py (overrides provider defaults)
    3. local.py (most important, overrides both)
    )"""
    # Start with provider-specific defaults (least important)
    config = deepcopy(PROVIDER_DEFAULTS.get(provider_name, {}))
    logger.debug(f"Starting with provider defaults for {provider_name}: {config}")
    
    # Get all possible keys for this provider
    possible_keys = set(config.keys())  # Start with keys from provider defaults
    possible_keys.update(get_config('PROVIDER_KEYS', {}).get(provider_name, []))  # Add keys from PROVIDER_KEYS
    logger.debug(f"Possible keys for {provider_name}: {possible_keys}")
    
    # Merge values from default.py (overrides provider defaults)
    provider_upper = provider_name.upper()
    
    # First, check for keys with provider prefix
    for key in possible_keys:
        default_key = f"{provider_upper}_{key}" if not key.startswith(provider_upper) else key
        default_value = get_config(default_key)
        logger.debug(f"Looking for default value for {default_key}: {default_value}")
        if default_value is not None:
            if key in config and isinstance(config[key], dict) and isinstance(default_value, dict):
                config[key] = deep_update(config[key], deepcopy(default_value))
            else:
                config[key] = deepcopy(default_value)
    
    # Then, check PROVIDER_CONFIG in default.py
    default_provider_config = get_config('PROVIDER_CONFIG', {}).get(provider_name, {})
    logger.debug(f"Provider config from default.py for {provider_name}: {default_provider_config}")
    if default_provider_config:
        config = deep_update(config, deepcopy(default_provider_config))
    logger.debug(f"After default.py for {provider_name}: {config}")
    
    # Get user config from local.py and merge it (most important)
    provider_config = get_config('PROVIDER_CONFIG', {})
    user_config = deepcopy(provider_config.get(provider_name, {}))
    logger.debug(f"User config from local.py for {provider_name}: {user_config}")
    if user_config:
        config = deep_update(config, user_config)
    logger.debug(f"Final merged config for {provider_name}: {config}")
    
    return config