from typing import Dict, Any, Callable
from dataclasses import dataclass

@dataclass
class TransitProvider:
    name: str
    endpoints: Dict[str, Callable]
    
# Dictionary to store all registered providers
PROVIDERS: Dict[str, TransitProvider] = {}

def register_provider(name: str, endpoints: Dict[str, Callable]) -> None:
    """Register a transit provider and its endpoints"""
    PROVIDERS[name] = TransitProvider(name=name, endpoints=endpoints)

def get_provider_docs() -> Dict[str, Any]:
    """Generate documentation for all registered providers and their endpoints"""
    docs = {}
    for provider_name, provider in PROVIDERS.items():
        docs[provider_name] = {
            "name": provider.name,
            "endpoints": {
                endpoint: {
                    "url": f"/api/{provider_name}/{endpoint}",
                    "doc": func.__doc__ or "No documentation available"
                }
                for endpoint, func in provider.endpoints.items()
            }
        }
    return docs
