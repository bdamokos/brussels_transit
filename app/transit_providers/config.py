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
    for key, value in update_dict.items():
        if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
            base_dict[key] = deep_update(base_dict[key], value)
        else:
            base_dict[key] = value
    return base_dict

def register_provider_config(provider_name: str, default_config: Dict[str, Any]) -> None:
    """Register a provider's default configuration"""
    PROVIDER_DEFAULTS[provider_name] = default_config
    logger.debug(f"Registered default config for {provider_name}")

def get_provider_config(provider_name: str) -> Dict[str, Any]:
    """Get merged configuration for a provider (following precedence: default.py → provider config → local.py)"""
    # Start with global defaults from default.py
    config = {}
    
    # Get relevant config from default.py
    # Look for provider-specific keys in default.py (e.g., STIB_STOPS for STIB)
    provider_upper = provider_name.upper()
    for key in PROVIDER_DEFAULTS.get(provider_name, {}):
        default_key = f"{provider_upper}_{key}" if not key.startswith(provider_upper) else key
        default_value = get_config(default_key)
        if default_value is not None:
            config[key] = deepcopy(default_value)
    logger.debug(f"Config from default.py for {provider_name}: {config}")
    
    # Merge provider-specific defaults
    provider_defaults = deepcopy(PROVIDER_DEFAULTS.get(provider_name, {}))
    config = deep_update(config, provider_defaults)
    logger.debug(f"After provider defaults for {provider_name}: {config}")
    
    # Get user config from local.py and merge it
    provider_config = get_config('PROVIDER_CONFIG', {})
    user_config = deepcopy(provider_config.get(provider_name, {}))
    config = deep_update(config, user_config)
    logger.debug(f"Final merged config for {provider_name}: {config}")
    
    return config