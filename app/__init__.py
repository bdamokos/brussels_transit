"""Main application package"""

import os
import sys

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    # Import transit providers first - this will trigger automatic discovery
    import transit_providers
    try:
        from . import transit_providers  # noqa
    except ImportError:
        pass

    __all__ = ['transit_providers']
    # Export the Flask app instance
    from . import main
    app = main.app

except:
    pass