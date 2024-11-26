from typing import Dict, Any, Callable, Union
from dataclasses import dataclass
import os
import importlib
import logging
from pathlib import Path

# Get logger
logger = logging.getLogger(__name__)

@dataclass
class TransitProvider:
    name: str
    endpoints: Dict[str, Callable]
    
# Dictionary to store all registered providers
PROVIDERS: Dict[str, Union[TransitProvider, Dict[str, Callable]]] = {}

def register_provider(name: str, provider: Union[Dict[str, Callable], TransitProvider]) -> None:
    """Register a transit provider and its endpoints"""
    logger.debug(f"Registering provider: {name}")
    endpoints = provider if isinstance(provider, dict) else provider.endpoints
    PROVIDERS[name] = TransitProvider(name=name, endpoints=endpoints)

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
                logger.error(f"Error importing module {module_name}: {e}")

# Import all providers when this module is imported
import_providers()
