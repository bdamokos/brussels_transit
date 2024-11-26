"""Main application package initialization"""

# Import transit providers first - this will trigger automatic discovery
import transit_providers

# Then import the main application
from . import main

# Export the Flask app instance
app = main.app
