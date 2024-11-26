# app/transit_providers/config.py

from typing import Dict, Any
from config import get_config
from logging.config import dictConfig
import logging

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('transit_providers.config')


# Registry for provider default configurations
PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {}

def register_provider_config(provider_name: str, default_config: Dict[str, Any]) -> None:
    """Register a provider's default configuration"""
    PROVIDER_DEFAULTS[provider_name] = default_config
    logger.debug(f"Registered default config for {provider_name}")

def get_provider_config(provider_name: str) -> Dict[str, Any]:
    """Get merged configuration for a provider (user config overrides defaults)"""
    # Get default config for this provider
    config = PROVIDER_DEFAULTS.get(provider_name, {}).copy()
    logger.debug(f"Default config for {provider_name}: {config}")
    # Get user config and merge it
    user_config = get_config(provider_name.upper(), {})
    logger.debug(f"User config for {provider_name}: {user_config}")
    config.update(user_config)
    logger.debug(f"Merged config for {provider_name}: {config}")
    return config