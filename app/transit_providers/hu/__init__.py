"""Hungarian transit providers"""

from transit_providers import register_provider
from . import bkk

# Register providers
bkk.register_bkk_provider(register_provider)

__all__ = ['bkk']
