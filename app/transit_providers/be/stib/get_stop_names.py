# app/transit_providers/be/stib/get_stop_names.py

import os
import requests
from pathlib import Path
from datetime import timedelta, datetime
import json
import logging
from logging.config import dictConfig
from transit_providers.config import get_provider_config
from config import get_config
from utils import select_language
from .gtfs import ensure_gtfs_data
import csv
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List, Any
from .stop_coordinates import (
    StopCoordinates, get_coordinates_from_gtfs,
    get_cached_coordinates as get_cached_gtfs_coordinates,
    cache_coordinates as cache_gtfs_coordinates
)

# Get configuration
provider_config = get_provider_config('stib')
STOPS_API_URL = provider_config.get('STIB_STOPS_API_URL')
API_KEY = provider_config.get('API_KEY')
CACHE_DIR = provider_config.get('CACHE_DIR')
STOPS_CACHE_FILE = CACHE_DIR / "stops.json"
CACHE_DURATION = provider_config.get('CACHE_DURATION')
GTFS_DIR = provider_config.get('GTFS_DIR')

# Failure tracking configuration
MAX_FAILURES = 5  # Maximum number of failures before we stop retrying
FAILURE_TIMEOUT = timedelta(hours=1)  # How long to wait before retrying after a failure
BATCH_SIZE = 10  # Number of stops to fetch in a single API call

# Setup logging using configuration
logging_config = get_config('LOGGING_CONFIG')
logging_config['log_dir'].mkdir(exist_ok=True)
dictConfig(logging_config)
language_precedence = get_config('LANGUAGE_PRECEDENCE')
# Get logger
logger = logging.getLogger('stib.get_stop_names')

# Create cache directory if it doesn't exist
CACHE_DIR.mkdir(exist_ok=True)

# Add GTFS translation cache
_translations_cache = None
_stops_trans_id_cache = None

@dataclass
class StopInfo:
    """Complete stop information including names and coordinates."""
    names: Dict[str, str]  # Language code to name mapping
    coordinates: Optional[StopCoordinates]
    metadata: Dict[str, Any]
    failures: Optional[Dict[str, Any]] = None

def load_stops_trans_ids():
    """Load stop_id to trans_id mapping from GTFS stops.txt"""
    global _stops_trans_id_cache
    
    if _stops_trans_id_cache is not None:
        return _stops_trans_id_cache
        
    _stops_trans_id_cache = {}
    try:
        stops_file = GTFS_DIR / 'stops.txt'
        if not stops_file.exists():
            logger.warning("stops.txt not found, triggering GTFS download")
            ensure_gtfs_data()
            
        with open(stops_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                stop_id = row.get('stop_id')
                trans_id = row.get('stop_name')  # In STIB GTFS, stop_name contains trans_id
                if stop_id and trans_id:
                    _stops_trans_id_cache[stop_id] = trans_id
                    
        logger.debug(f"Loaded {len(_stops_trans_id_cache)} stop_id to trans_id mappings from GTFS")
    except Exception as e:
        logger.error(f"Error loading stops.txt: {e}", exc_info=True)
        _stops_trans_id_cache = {}
    
    return _stops_trans_id_cache

def load_translations(trans_id_to_return=None):
    """Load stop name translations from GTFS translations.txt"""
    global _translations_cache
    
    # Return from cache if available
    if _translations_cache is not None:
        if not trans_id_to_return:
            return _translations_cache
        return _translations_cache.get(trans_id_to_return, {})
    
    _translations_cache = {}
    try:
        translations_file = GTFS_DIR / 'translations.txt'
        if not translations_file.exists():
            logger.warning("translations.txt not found, triggering GTFS download")
            ensure_gtfs_data()
            
        with open(translations_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trans_id = row.get('trans_id')
                translation = row.get('translation')
                lang = row.get('lang')
                
                if all([trans_id, translation, lang]):
                    if trans_id not in _translations_cache:
                        _translations_cache[trans_id] = {}
                    _translations_cache[trans_id][lang] = translation
                else:
                    logger.warning(f"Incomplete translation row: trans_id={trans_id}, lang={lang}")
                    
        logger.debug(f"Loaded {len(_translations_cache)} translations from GTFS")
    except Exception as e:
        logger.error(f"Error loading translations.txt: {e}", exc_info=True)
        _translations_cache = {}
    
    if not trans_id_to_return:
        return _translations_cache
    return _translations_cache.get(trans_id_to_return, {})

def normalize_stop_id(stop_id: str) -> str:
    """Remove any suffix (letters) from a stop ID."""
    return ''.join(c for c in stop_id if c.isdigit())

def get_stop_id_variants(stop_id: str) -> List[str]:
    """Get all possible variants of a stop ID to try."""
    base_id = normalize_stop_id(stop_id)
    
    # If the original ID has a suffix, try:
    # 1. Original ID (e.g., 5710F)
    # 2. Base ID (e.g., 5710)
    if base_id != stop_id:
        return [stop_id, base_id]
    
    # If the original ID has no suffix, try:
    # 1. Original ID (e.g., 5710)
    # 2. ID with suffixes (e.g., 5710F, 5710G)
    return [stop_id] + [f"{base_id}{suffix}" for suffix in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']]

def get_stop_info_from_gtfs(stop_id: str) -> Optional[StopInfo]:
    """Get stop information from GTFS data."""
    try:
        # First try to get translations
        stops_trans_ids = load_stops_trans_ids()
        translations = load_translations()
        
        # Try all stop ID variants
        for variant_id in get_stop_id_variants(stop_id):
            trans_id = stops_trans_ids.get(variant_id)
            if trans_id and trans_id in translations:
                trans_data = translations[trans_id]
                if 'fr' in trans_data and 'nl' in trans_data:
                    # Get coordinates from GTFS
                    coords = get_coordinates_from_gtfs(variant_id)
                    
                    return StopInfo(
                        names={
                            'fr': trans_data['fr'],
                            'nl': trans_data['nl']
                        },
                        coordinates=coords,
                        metadata={
                            'source': 'gtfs',
                            'trans_id': trans_id,
                            'original_id': variant_id if variant_id != stop_id else None
                        }
                    )
        
        return None
            
    except Exception as e:
        logger.error(f"Error getting stop info from GTFS: {e}", exc_info=True)
        return None

def should_retry_stop(stop_data):
    """Check if we should retry fetching a stop based on its failure history."""
    failures = stop_data.get('_failures', {})
    
    # If no failure history or no coordinates, we should try
    if not failures and not stop_data.get('coordinates', {}).get('lat'):
        return True
    
    fail_count = failures.get('count', 0)
    last_failure = failures.get('last_failure')
    
    # If we've failed too many times, don't retry
    if fail_count >= MAX_FAILURES:
        return False
    
    # If we have a recent failure, don't retry yet
    if last_failure:
        last_failure_time = datetime.fromisoformat(last_failure)
        if datetime.now() - last_failure_time < FAILURE_TIMEOUT:
            return False
    
    return True

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
        stops_trans_ids = load_stops_trans_ids()
        trans_id = stops_trans_ids.get(stop_id)
        
        if trans_id:
            logger.debug(f"Found trans_id {trans_id} for stop {stop_id}")
            translations = load_translations(trans_id)
            if translations:
                # Only update missing languages
                if not result['fr'] and 'fr' in translations:
                    result['fr'] = translations['fr']
                    logger.debug(f"Using GTFS French translation for stop {stop_id}: {translations['fr']}")
                if not result['nl'] and 'nl' in translations:
                    result['nl'] = translations['nl']
                    logger.debug(f"Using GTFS Dutch translation for stop {stop_id}: {translations['nl']}")
                result['_metadata']['source'] = 'gtfs_translations'
                result['_metadata']['trans_id'] = trans_id
            else:
                logger.debug(f"No translations found for trans_id {trans_id}")
        else:
            logger.debug(f"No trans_id found for stop {stop_id}")
            
    except Exception as e:
        logger.error(f"Error loading GTFS translations for stop {stop_id}: {e}", exc_info=True)

    # 3. Use stop ID as fallback for any missing language
    if not result['fr']:
        result['fr'] = stop_id
        logger.debug(f"Using stop_id as fallback for French name: {stop_id}")
    if not result['nl']:
        result['nl'] = stop_id
        logger.debug(f"Using stop_id as fallback for Dutch name: {stop_id}")

    return result

def get_stop_names(stop_ids, preferred_language=None):
    """Fetch stop names and coordinates for a list of stop IDs, using cache when possible"""
    global cached_stops

    # Log unique stops being requested
    unique_stops = set(stop_ids)
    logger.debug(f"Requested {len(stop_ids)} stops ({len(unique_stops)} unique)")

    # First try to get info from GTFS for all stops
    for stop_id in unique_stops:
        if stop_id not in cached_stops:
            # Try GTFS first
            gtfs_info = get_stop_info_from_gtfs(stop_id)
            if gtfs_info:
                logger.debug(f"Found complete GTFS info for stop {stop_id}")
                cached_stops[stop_id] = {
                    'name': gtfs_info.names['fr'],  # For v1 API backward compatibility
                    'names': gtfs_info.names,
                    'coordinates': {
                        'lat': gtfs_info.coordinates.lat if gtfs_info.coordinates else None,
                        'lon': gtfs_info.coordinates.lon if gtfs_info.coordinates else None
                    },
                    '_metadata': gtfs_info.metadata,
                    '_failures': {
                        'count': 0,
                        'last_failure': None,
                        'normalized_id': None
                    }
                }

    # Now filter stops that still need API data
    stops_to_fetch = []
    for stop_id in unique_stops:
        stop_data = cached_stops.get(stop_id, {})
        # Need to fetch if:
        # 1. Not in cache at all
        # 2. No coordinates and we should retry
        # 3. Has coordinates but they're None and we should retry
        if (stop_id not in cached_stops or
            (not stop_data.get('coordinates') and should_retry_stop(stop_data)) or
            (stop_data.get('coordinates', {}).get('lat') is None and should_retry_stop(stop_data))):
            stops_to_fetch.append(stop_id)
        else:
            logger.debug(f"Skipping API fetch for stop {stop_id}: " + (
                "max failures reached" if stop_data.get('_failures', {}).get('count', 0) >= MAX_FAILURES
                else "recent failure" if stop_data.get('_failures', {}).get('last_failure')
                else "already cached with coordinates" if stop_data.get('coordinates', {}).get('lat')
                else "has GTFS info"
            ))

    if stops_to_fetch:
        logger.info(f"Fetching {len(stops_to_fetch)} stops from API")
        
        # Process stops in batches
        for i in range(0, len(stops_to_fetch), BATCH_SIZE):
            batch = stops_to_fetch[i:i + BATCH_SIZE]
            logger.debug(f"Processing batch {i//BATCH_SIZE + 1}/{(len(stops_to_fetch) + BATCH_SIZE - 1)//BATCH_SIZE}")
            
            # Build OR query for all stops in batch
            variant_queries = []
            for stop_id in batch:
                variants = get_stop_id_variants(stop_id)
                variant_queries.extend([f'id="{v}"' for v in variants])
            
            query = ' OR '.join(variant_queries)
            params = {
                'where': f'({query})',
                'limit': len(variant_queries),  # Adjust limit to match number of variants
                'apikey': API_KEY
            }

            try:
                response = requests.get(STOPS_API_URL, params=params)
                logger.debug(f"Batch API Response status: {response.status_code}")
                
                if response.status_code != 200:
                    logger.warning(f"Batch API Response text: {response.text}")
                    # Mark all stops in batch as failed
                    for stop_id in batch:
                        failures = cached_stops.get(stop_id, {}).get('_failures', {})
                        if stop_id not in cached_stops:
                            cached_stops[stop_id] = {
                                'name': stop_id,
                                'names': {'fr': stop_id, 'nl': stop_id},
                                'coordinates': {'lat': None, 'lon': None},
                                '_metadata': {'source': 'fallback'},
                                '_failures': {
                                    'count': failures.get('count', 0) + 1,
                                    'last_failure': datetime.now().isoformat(),
                                    'normalized_id': get_stop_id_variants(stop_id)[-1]
                                }
                            }
                        else:
                            cached_stops[stop_id]['_failures'] = {
                                'count': failures.get('count', 0) + 1,
                                'last_failure': datetime.now().isoformat(),
                                'normalized_id': get_stop_id_variants(stop_id)[-1]
                            }
                    continue

                response.raise_for_status()
                data = response.json()

                # Process results
                found_stops = set()
                for result in data['results']:
                    stop_data = result
                    stop_id = stop_data['id']
                    
                    # Find original stop ID that matches this result
                    original_stop_id = None
                    for batch_stop_id in batch:
                        if stop_id in get_stop_id_variants(batch_stop_id):
                            original_stop_id = batch_stop_id
                            break
                    
                    if not original_stop_id:
                        logger.warning(f"Could not map result stop {stop_id} back to original stop ID")
                        continue

                    found_stops.add(original_stop_id)

                    # Extract coordinates
                    gps_coords = json.loads(stop_data.get('gpscoordinates', '{}'))
                    coordinates = {
                        'lat': float(gps_coords.get('latitude')) if gps_coords.get('latitude') else None,
                        'lon': float(gps_coords.get('longitude')) if gps_coords.get('longitude') else None
                    }

                    # If we have coordinates, also cache them in the GTFS coordinates cache
                    if coordinates['lat'] is not None and coordinates['lon'] is not None:
                        gtfs_coords = StopCoordinates(
                            lat=coordinates['lat'],
                            lon=coordinates['lon'],
                            source='api',
                            original_id=stop_id if stop_id != original_stop_id else None
                        )
                        gtfs_cache = get_cached_gtfs_coordinates()
                        gtfs_cache[original_stop_id] = gtfs_coords
                        cache_gtfs_coordinates(gtfs_cache)

                    # If we already have GTFS names, just update coordinates
                    if original_stop_id in cached_stops:
                        cached_stops[original_stop_id]['coordinates'] = coordinates
                        cached_stops[original_stop_id]['_failures'] = {
                            'count': 0,
                            'last_failure': None,
                            'normalized_id': stop_id
                        }
                        logger.debug(f"Updated coordinates for stop {original_stop_id} from API")
                    else:
                        # No GTFS data, use API data
                        name_data = json.loads(stop_data['name'])
                        resolved_names = resolve_stop_name(original_stop_id, name_data)
                        cached_stops[original_stop_id] = {
                            'name': resolved_names['fr'],
                            'names': {
                                'fr': resolved_names['fr'],
                                'nl': resolved_names['nl']
                            },
                            'coordinates': coordinates,
                            '_metadata': resolved_names['_metadata'],
                            '_failures': {
                                'count': 0,
                                'last_failure': None,
                                'normalized_id': stop_id
                            }
                        }
                        logger.debug(f"Added stop {original_stop_id} to cache with API data")

                # Mark unfound stops as failed
                for stop_id in batch:
                    if stop_id not in found_stops:
                        failures = cached_stops.get(stop_id, {}).get('_failures', {})
                        if stop_id not in cached_stops:
                            cached_stops[stop_id] = {
                                'name': stop_id,
                                'names': {'fr': stop_id, 'nl': stop_id},
                                'coordinates': {'lat': None, 'lon': None},
                                '_metadata': {'source': 'fallback'},
                                '_failures': {
                                    'count': failures.get('count', 0) + 1,
                                    'last_failure': datetime.now().isoformat(),
                                    'normalized_id': get_stop_id_variants(stop_id)[-1]
                                }
                            }
                        else:
                            cached_stops[stop_id]['_failures'] = {
                                'count': failures.get('count', 0) + 1,
                                'last_failure': datetime.now().isoformat(),
                                'normalized_id': get_stop_id_variants(stop_id)[-1]
                            }
                        logger.warning(f"No data found for stop {stop_id}, failure count: {cached_stops[stop_id]['_failures']['count']}")

            except Exception as e:
                logger.error(f"Error fetching batch of stops: {e}", exc_info=True)
                # Mark all stops in batch as failed
                for stop_id in batch:
                    failures = cached_stops.get(stop_id, {}).get('_failures', {})
                    if stop_id not in cached_stops:
                        cached_stops[stop_id] = {
                            'name': stop_id,
                            'names': {'fr': stop_id, 'nl': stop_id},
                            'coordinates': {'lat': None, 'lon': None},
                            '_metadata': {'source': 'fallback'},
                            '_failures': {
                                'count': failures.get('count', 0) + 1,
                                'last_failure': datetime.now().isoformat(),
                                'normalized_id': get_stop_id_variants(stop_id)[-1]
                            }
                        }
                    else:
                        cached_stops[stop_id]['_failures'] = {
                            'count': failures.get('count', 0) + 1,
                            'last_failure': datetime.now().isoformat(),
                            'normalized_id': get_stop_id_variants(stop_id)[-1]
                        }

        # Save updated cache
        save_cached_stops(cached_stops)
        logger.info("Saved updated stops cache")

    # Return requested stop details from cache with language selection
    result = {}
    for stop_id in stop_ids:  # Use original stop_ids to maintain order
        stop_data = cached_stops.get(stop_id, {
            'name': stop_id,
            'names': {'fr': stop_id, 'nl': stop_id},
            'coordinates': {'lat': None, 'lon': None},
            '_metadata': {'source': 'fallback'}
        })
        
        # Apply language selection
        name_with_metadata, _metadata = select_language(content=stop_data['names'], provider_languages=language_precedence, requested_language=preferred_language)
        
        result[stop_id] = {
            'name': name_with_metadata,
            'coordinates': stop_data['coordinates'],
            '_metadata': {
                'language': _metadata['language'],
                'source': stop_data.get('_metadata', {}).get('source', 'fallback'),
                'trans_id': stop_data.get('_metadata', {}).get('trans_id'),
                'original_id': stop_data.get('_metadata', {}).get('original_id')
            }
        }
    
    return result
