import os
import requests
from pathlib import Path
from datetime import timedelta
import json
import logging
from logging.config import dictConfig
from transit_providers.config import get_provider_config
from config import get_config

# Get configuration
provider_config = get_provider_config('stib')
STOPS_API_URL = provider_config.get('STIB_STOPS_API_URL')
API_KEY = provider_config.get('API_KEY')
CACHE_DIR = provider_config.get('CACHE_DIR')
STOPS_CACHE_FILE = CACHE_DIR / "stops.json"
CACHE_DURATION = provider_config.get('CACHE_DURATION')

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)
dictConfig(logging_config)

# Get logger
logger = logging.getLogger('stib.get_stop_names')

# Create cache directory if it doesn't exist
CACHE_DIR.mkdir(exist_ok=True)

def load_cached_stops():
    """Load stop names from cache file"""
    if STOPS_CACHE_FILE.exists():
        try:
            with open(STOPS_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading stops cache: {e}", exc_info=True)
    return {}

# Load cached stops at startup
cached_stops = load_cached_stops()

def save_cached_stops(stops_data):
    """Save stop names to cache file"""
    try:
        with open(STOPS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(stops_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving stops cache: {e}", exc_info=True)

def get_stop_names(stop_ids):
    """Fetch stop names and coordinates for a list of stop IDs, using cache when possible"""
    global cached_stops

    # Filter out stops we already have in cache with valid coordinates
    stops_to_fetch = [
        stop_id for stop_id in stop_ids 
        if stop_id not in cached_stops or 
        not cached_stops[stop_id].get('coordinates', {}).get('lat') or 
        not cached_stops[stop_id].get('coordinates', {}).get('lon')
    ]

    if stops_to_fetch:
        logger.info(f"Fetching {len(stops_to_fetch)} new stop details")
        for stop_id in stops_to_fetch:
            params = {
                'where': f'id="{stop_id}"',
                'limit': 1,
                'apikey': API_KEY
            }

            try:
                response = requests.get(STOPS_API_URL, params=params)
                logger.debug(f"Stop details API Response status for {stop_id}: {response.status_code}")
                
                if response.status_code != 200:
                    logger.warning(f"Stop details API Response text: {response.text}")

                response.raise_for_status()
                data = response.json()

                if data['results']:
                    stop_data = data['results'][0]
                    name_data = json.loads(stop_data['name'])

                    # Extract coordinates from the response
                    gps_coords = json.loads(stop_data.get('gpscoordinates', '{}'))
                    coordinates = {
                        'lat': float(gps_coords.get('latitude')) if gps_coords.get('latitude') else None,
                        'lon': float(gps_coords.get('longitude')) if gps_coords.get('longitude') else None
                    }

                    # Only update cache if we got valid coordinates
                    if coordinates['lat'] is not None and coordinates['lon'] is not None:
                        cached_stops[stop_id] = {
                            'name': name_data['fr'],
                            'coordinates': coordinates
                        }
                        logger.debug(f"Added stop {stop_id} to cache with coordinates: {coordinates}")
                    else:
                        logger.warning(f"No valid coordinates found for stop {stop_id}")
                        if stop_id not in cached_stops:
                            cached_stops[stop_id] = {
                                'name': name_data['fr'],
                                'coordinates': {'lat': None, 'lon': None}
                            }
                else:
                    logger.warning(f"No data found for stop ID: {stop_id}")
                    if stop_id not in cached_stops:
                        cached_stops[stop_id] = {
                            'name': stop_id,
                            'coordinates': {'lat': None, 'lon': None}
                        }

            except Exception as e:
                logger.error(f"Error fetching stop details for {stop_id}: {e}", exc_info=True)
                if stop_id not in cached_stops:
                    cached_stops[stop_id] = {
                        'name': stop_id,
                        'coordinates': {'lat': None, 'lon': None}
                    }

        # Save updated cache
        save_cached_stops(cached_stops)
        logger.info("Saved updated stops cache")

    # Return requested stop details from cache
    return {stop_id: cached_stops.get(stop_id, {'name': stop_id, 'coordinates': {'lat': None, 'lon': None}})
            for stop_id in stop_ids}


