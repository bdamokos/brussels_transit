# app/transit_providers/be/stib/get_stop_names.py

import os
import requests
from pathlib import Path
from datetime import timedelta
import json
import logging
from logging.config import dictConfig
from transit_providers.config import get_provider_config
from config import get_config
from utils import select_language
from gtfs import ensure_gtfs_data
import csv

# Get configuration
provider_config = get_provider_config('stib')
STOPS_API_URL = provider_config.get('STIB_STOPS_API_URL')
API_KEY = provider_config.get('API_KEY')
CACHE_DIR = provider_config.get('CACHE_DIR')
STOPS_CACHE_FILE = CACHE_DIR / "stops.json"
CACHE_DURATION = provider_config.get('CACHE_DURATION')
GTFS_DIR = provider_config.get('GTFS_DIR')
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

def resolve_stop_name(stop_id, name_data=None):
    """Resolve stop name using multiple sources in order:
    1. API name data if provided
    2. GTFS translations
    3. GTFS stops.txt
    4. Stop ID as fallback
    """
    result = {
        'fr': None,
        'nl': None,
        '_metadata': {
            'source': None,
            'trans_id': None
        }
    }

    # 1. Try API name data first
    if name_data:
        result['fr'] = name_data.get('fr')
        result['nl'] = name_data.get('nl')
        result['_metadata']['source'] = 'api'
        
        # If we have both languages, we're done
        if result['fr'] and result['nl']:
            return result

    # 2. Try GTFS translations
    try:
        # First get trans_id from stops.txt
        stops_file = GTFS_DIR / 'stops.txt'
        if stops_file.exists():
            with open(stops_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                trans_id = None
                for row in reader:
                    if row.get('stop_id') == stop_id:
                        trans_id = row.get('stop_name')  # In STIB GTFS, stop_name contains trans_id
                        break
                
                if trans_id:
                    translations = load_translations(trans_id)
                    if translations:
                        # Only update missing languages
                        if not result['fr'] and 'fr' in translations:
                            result['fr'] = translations['fr']
                        if not result['nl'] and 'nl' in translations:
                            result['nl'] = translations['nl']
                        result['_metadata']['source'] = 'gtfs_translations'
                        result['_metadata']['trans_id'] = trans_id
    except Exception as e:
        logger.error(f"Error loading GTFS translations for stop {stop_id}: {e}", exc_info=True)

    # 3. Use stop ID as fallback for any missing language
    if not result['fr']:
        result['fr'] = stop_id
    if not result['nl']:
        result['nl'] = stop_id

    return result

def get_stop_names(stop_ids, preferred_language=None):
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

                    # Resolve names with fallback chain
                    resolved_names = resolve_stop_name(stop_id, name_data)

                    # Only update cache if we got valid coordinates
                    if coordinates['lat'] is not None and coordinates['lon'] is not None:
                        cached_stops[stop_id] = {
                            'name': resolved_names['fr'],  # For v1 API backward compatibility
                            'names': {
                                'fr': resolved_names['fr'],
                                'nl': resolved_names['nl']
                            },
                            'coordinates': coordinates,
                            '_metadata': resolved_names['_metadata']
                        }
                        logger.debug(f"Added stop {stop_id} to cache with coordinates: {coordinates}")
                    else:
                        logger.warning(f"No valid coordinates found for stop {stop_id}")
                        if stop_id not in cached_stops:
                            cached_stops[stop_id] = {
                                'name': resolved_names['fr'],  # For v1 API backward compatibility
                                'names': {
                                    'fr': resolved_names['fr'],
                                    'nl': resolved_names['nl']
                                },
                                'coordinates': {'lat': None, 'lon': None},
                                '_metadata': resolved_names['_metadata']
                            }
                else:
                    logger.warning(f"No data found for stop ID: {stop_id}")
                    resolved_names = resolve_stop_name(stop_id)  # Try GTFS without API data
                    if stop_id not in cached_stops:
                        cached_stops[stop_id] = {
                            'name': resolved_names['fr'],  # For v1 API backward compatibility
                            'names': {
                                'fr': resolved_names['fr'],
                                'nl': resolved_names['nl']
                            },
                            'coordinates': {'lat': None, 'lon': None},
                            '_metadata': resolved_names['_metadata']
                        }

            except Exception as e:
                logger.error(f"Error fetching stop details for {stop_id}: {e}", exc_info=True)
                resolved_names = resolve_stop_name(stop_id)  # Try GTFS without API data
                if stop_id not in cached_stops:
                    cached_stops[stop_id] = {
                        'name': resolved_names['fr'],  # For v1 API backward compatibility
                        'names': {
                            'fr': resolved_names['fr'],
                            'nl': resolved_names['nl']
                        },
                        'coordinates': {'lat': None, 'lon': None},
                        '_metadata': resolved_names['_metadata']
                    }

        # Save updated cache
        save_cached_stops(cached_stops)
        logger.info("Saved updated stops cache")

    # Return requested stop details from cache with language selection
    result = {}
    for stop_id in stop_ids:
        stop_data = cached_stops.get(stop_id, {
            'name': stop_id,  # For v1 API backward compatibility
            'names': {'fr': stop_id, 'nl': stop_id},
            'coordinates': {'lat': None, 'lon': None},
            '_metadata': {'source': 'fallback'}
        })
        
        # Apply language selection
        name_with_metadata = select_language(
            stop_data['names'],
            preferred_language=preferred_language
        )
        
        result[stop_id] = {
            'name': name_with_metadata['content'],
            'coordinates': stop_data['coordinates'],
            '_metadata': {
                'language': name_with_metadata['_metadata']['language'],
                'source': stop_data.get('_metadata', {}).get('source', 'fallback'),
                'trans_id': stop_data.get('_metadata', {}).get('trans_id')
            }
        }
    
    return result

def load_translations(trans_id_to_return=None):
    """Load stop name translations from GTFS translations.txt"""
    translations = {}
    try:
        if not (GTFS_DIR / 'translations.txt').exists():
            logger.warning("translations.txt not found, need to trigger GTFS download")
            ensure_gtfs_data()

        with open(GTFS_DIR / 'translations.txt', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trans_id = row.get('trans_id')
                translation = row.get('translation')
                lang = row.get('lang')
                
                if all([trans_id, translation, lang]):
                    if trans_id not in translations:
                        translations[trans_id] = {}
                    translations[trans_id][lang] = translation

    except Exception as e:
        logger.error(f"Error loading translations: {e}", exc_info=True)
    if not trans_id_to_return:
        return translations
    else:
        return translations.get(trans_id_to_return, {})
