"""
Configuration management for the Brussels Public Transport Display application.
Handles loading and accessing configuration values from local.py (if present) 
with fallback to default.py.
"""

import importlib.util
import logging
from logging.config import dictConfig
from pathlib import Path
from typing import Any, Optional


# Import configuration modules first
def _import_config(module_name: str) -> Optional[Any]:
    """
    Dynamically import a configuration module.

    Args:
        module_name: Name of the module to import (e.g., 'local' or 'default')

    Returns:
        Module object if successful, None otherwise
    """
    try:
        spec = importlib.util.find_spec(f"config.{module_name}")
        if spec is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    except Exception as e:
        print(
            f"Could not import config.{module_name}: {str(e)}"
        )  # Use print since logging is not set up yet
        return None


# Import configuration modules
local_config = _import_config("local")
default_config = _import_config("default")

# Initialize logging configuration once
logging_config = None
if hasattr(local_config, "LOGGING_CONFIG"):
    logging_config = getattr(local_config, "LOGGING_CONFIG")
elif hasattr(default_config, "LOGGING_CONFIG"):
    logging_config = getattr(default_config, "LOGGING_CONFIG")

if logging_config:
    dictConfig(logging_config)

# Initialize logger after logging is configured
logger = logging.getLogger(__name__)


def get_config(key: str, default_value: Any = None) -> Any:
    """
    Get a configuration value, checking local.py first, then default.py.

    Args:
        key: The configuration key to look up
        default_value: Value to return if key is not found in either config

    Returns:
        The configuration value, or default_value if not found

    Example:
        >>> map_config = get_config('MAP_CONFIG')
        >>> stib_stops = get_config('STIB_STOPS', [])
    """
    # Try local config first
    if local_config and hasattr(local_config, key):
        return getattr(local_config, key)

    # Fall back to default config
    if default_config and hasattr(default_config, key):
        return getattr(default_config, key)

    # Return default value if key not found
    return default_value


def get_required_config(key: str) -> Any:
    """
    Get a required configuration value. Raises an error if not found.

    Args:
        key: The configuration key to look up

    Returns:
        The configuration value

    Raises:
        ValueError: If the configuration key is not found

    Example:
        >>> api_key = get_required_config('API_KEY')
    """
    value = get_config(key)
    if value is None:
        raise ValueError(
            f"Required configuration key '{key}' not found in either local.py or default.py"
        )
    return value


def list_config_keys() -> set:
    """
    Get a set of all available configuration keys.

    Returns:
        Set of configuration key names

    Example:
        >>> keys = list_config_keys()
        >>> print("Available config keys:", keys)
    """
    keys = set()

    # Add keys from default config
    if default_config:
        keys.update(k for k in dir(default_config) if not k.startswith("_"))

    # Add keys from local config
    if local_config:
        keys.update(k for k in dir(local_config) if not k.startswith("_"))

    return keys


# Export commonly used functions
__all__ = ["get_config", "get_required_config", "list_config_keys"]
