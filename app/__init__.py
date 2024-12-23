"""Main application package"""

import os
import sys

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from . import transit_providers  # noqa

__all__ = ['transit_providers']
