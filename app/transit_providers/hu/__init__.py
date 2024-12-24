"""Hungarian transit providers"""

from transit_providers import register_provider
from . import bkk

# The BKK provider will register itself if enabled in configuration

__all__ = ['bkk']
