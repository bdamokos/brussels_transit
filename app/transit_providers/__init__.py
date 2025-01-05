from typing import Dict, Any, Callable, Union
from dataclasses import dataclass
import os
import importlib
import logging
from pathlib import Path
import inspect

# Get logger
logger = logging.getLogger(__name__)

@dataclass
class TransitProvider:
    name: str
    endpoints: Dict[str, Callable]
    
# Dictionary to store all registered providers
PROVIDERS: Dict[str, Union[TransitProvider, Dict[str, Callable]]] = {}

def get_provider_path(provider_name: str) -> str:
    """Get the path for a provider based on its module location"""
    if provider_name not in PROVIDERS:
        logger.debug(f"Provider {provider_name} not found in PROVIDERS")
        return ""
        
    provider = PROVIDERS[provider_name]
    logger.debug(f"Found provider {provider_name}: {type(provider)}")
    
    # Get the module where this provider was defined
    if isinstance(provider, TransitProvider):
        module = inspect.getmodule(provider.__class__)
        logger.debug(f"Provider is TransitProvider instance, module: {module}")
    else:
        # For dict providers, we need to get the module where register_provider was called
        frame = inspect.currentframe()
        while frame:
            if frame.f_code.co_name == 'register_provider':
                module = inspect.getmodule(frame.f_code)
                break
            frame = frame.f_back
        else:
            logger.debug("Could not find register_provider frame")
            return ""
            
    if not module:
        logger.debug("Could not determine module")
        return ""
        
    # Get module path relative to transit_providers
    # e.g. transit_providers.be.stib -> be/stib
    parts = module.__name__.split('.')
    logger.debug(f"Module name parts: {parts}")
    if len(parts) > 1:  # Skip 'transit_providers' part
        path = '/'.join(parts[1:])
        logger.debug(f"Extracted path: {path}")
        return path
    logger.debug("No path components found")
    return ""

def register_provider(name: str, provider: Union[Dict[str, Callable], TransitProvider]) -> None:
    """Register a transit provider and its endpoints"""
    logger.debug(f"Registering provider: {name}")
    
    # If it's already a TransitProvider instance, store it directly
    if isinstance(provider, TransitProvider):
        PROVIDERS[name] = provider
    else:
        # For dict providers, create a new TransitProvider instance
        PROVIDERS[name] = TransitProvider(name=name, endpoints=provider)
        
    logger.debug(f"Provider {name} registered with endpoints: {list(PROVIDERS[name].endpoints.keys())}")

def get_provider_docs() -> Dict[str, Any]:
    """Generate documentation for all registered providers and their endpoints"""
    docs = {}
    for provider_name, provider in PROVIDERS.items():
        endpoints = provider.endpoints if isinstance(provider, TransitProvider) else provider
        docs[provider_name] = {
            "name": provider_name,
            "endpoints": {
                endpoint: {
                    "url": f"/api/{provider_name}/{endpoint}",
                    "doc": func.__doc__ or "No documentation available"
                }
                for endpoint, func in endpoints.items()
            }
        }
    return docs

def import_providers():
    """Dynamically import all provider modules"""
    logger.debug("Starting provider discovery")
    # Get the directory containing this file
    providers_dir = Path(__file__).parent
    
    # Walk through all subdirectories
    for root, dirs, files in os.walk(providers_dir):
        # Convert root path to module path
        module_path = Path(root).relative_to(providers_dir.parent)
        module_parts = list(module_path.parts)
        
        # Skip __pycache__ directories
        if '__pycache__' in module_parts:
            continue
            
        # Look for __init__.py files
        if '__init__.py' in files:
            # Convert path to module notation
            module_name = '.'.join(module_parts)
            try:
                logger.debug(f"Attempting to import module: {module_name}")
                importlib.import_module(module_name)
                logger.debug(f"Successfully imported module: {module_name}")
            except Exception as e:
                logger.error(f"Error importing module {module_name}: {e}", exc_info=True)

def get_provider_from_path(provider_path: str) -> str:
    """Convert a provider path (e.g. 'be/stib') back to a provider ID (e.g. 'stib')
    
    Args:
        provider_path: The path of the provider (e.g. 'be/stib')
        
    Returns:
        str: The provider ID if found, empty string if not found
    """
    logger.debug(f"Looking up provider from path: {provider_path}")
    
    # Check each provider's path
    for provider_name, provider in PROVIDERS.items():
        path = get_provider_path(provider_name)
        if path == provider_path:
            logger.debug(f"Found provider {provider_name} for path {provider_path}")
            return provider_name
            
    logger.debug(f"No provider found for path {provider_path}")
    return ""

# Import all providers when this module is imported
import_providers()
