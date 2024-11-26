from typing import Dict, Any, Callable, Union
from dataclasses import dataclass

@dataclass
class TransitProvider:
    name: str
    endpoints: Dict[str, Callable]
    
# Dictionary to store all registered providers
PROVIDERS: Dict[str, Union[TransitProvider, Dict[str, Callable]]] = {}

def register_provider(name: str, provider: Union[Dict[str, Callable], TransitProvider]) -> None:
    """Register a transit provider and its endpoints"""
    if isinstance(provider, dict):
        PROVIDERS[name] = TransitProvider(name=name, endpoints=provider)
    else:
        PROVIDERS[name] = provider

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
