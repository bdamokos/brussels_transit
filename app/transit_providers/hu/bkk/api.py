''' Script to handle data from BKK (Budapest public transport)'''

import requests
import json
import os
from config import get_config
import logging
from logging.config import dictConfig

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)  # Create logs directory
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('bkk')

def bkk_waiting_times():
    pass

def bkk_vehicle_positions():
    pass

def bkk_service_alerts():
    pass

def bkk_static_data():
    pass

def bkk_config():
    pass