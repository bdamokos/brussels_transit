"""Hungarian transit providers"""

from config import get_config

if "bkk" in get_config("ENABLED_PROVIDERS", []):
    from . import bkk
else:
    bkk = None

__all__ = ['bkk']
