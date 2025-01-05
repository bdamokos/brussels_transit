from typing import Dict, Optional, Set, List
from datetime import datetime, timedelta
import logging
from pathlib import Path
import json
import os
from .gtfs_parquet import ParquetGTFSLoader, FlixbusFeed

logger = logging.getLogger(__name__)

class GTFSCache:
    """
    Manages caching of GTFS data and stop times.
    """
    def __init__(self, cache_dir: str | Path = "cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # In-memory cache for ParquetGTFSLoader instances
        self._loaders: Dict[str, ParquetGTFSLoader] = {}
        
        # In-memory cache for feed instances
        self._feeds: Dict[str, FlixbusFeed] = {}
        
        # Cache for stop times
        self._stop_times_cache: Dict[str, Dict] = {}
        self._stop_times_expiry: Dict[str, datetime] = {}
        
        # Default cache duration for stop times (1 day)
        self.stop_times_cache_duration = timedelta(days=1)
        
        logger.info(f"Initialized GTFSCache with cache directory: {self.cache_dir}")

    def get_loader(self, provider_id: str, data_dir: str | Path) -> Optional[ParquetGTFSLoader]:
        """
        Get a ParquetGTFSLoader instance for a provider, creating it if necessary.
        
        Args:
            provider_id: The ID of the provider (e.g., 'mdb-1234')
            data_dir: The directory containing the GTFS data
            
        Returns:
            ParquetGTFSLoader instance or None if creation fails
        """
        try:
            # Check if we already have a loader for this provider
            if provider_id in self._loaders:
                logger.debug(f"Returning cached loader for provider {provider_id}")
                return self._loaders[provider_id]
            
            # Create new loader
            logger.info(f"Creating new ParquetGTFSLoader for provider {provider_id}")
            loader = ParquetGTFSLoader(data_dir)
            self._loaders[provider_id] = loader
            return loader
            
        except Exception as e:
            logger.error(f"Error getting loader for provider {provider_id}: {e}")
            return None

    def get_feed(self, provider_id: str) -> Optional[FlixbusFeed]:
        """
        Get a cached feed for a provider.
        
        Args:
            provider_id: The ID of the provider
            
        Returns:
            FlixbusFeed instance or None if not cached
        """
        return self._feeds.get(provider_id)

    def cache_feed(self, provider_id: str, feed: FlixbusFeed):
        """
        Cache a feed for a provider.
        
        Args:
            provider_id: The ID of the provider
            feed: The feed to cache
        """
        self._feeds[provider_id] = feed
        logger.debug(f"Cached feed for {provider_id}")

    def get_stop_times(self, provider_id: str, stop_id: str) -> Optional[Dict]:
        """
        Get cached stop times for a stop, if available and not expired.
        
        Args:
            provider_id: The ID of the provider
            stop_id: The ID of the stop
            
        Returns:
            Dict of stop times or None if not cached or expired
        """
        cache_key = f"{provider_id}_{stop_id}"
        
        # Check if we have cached data and it's not expired
        if (cache_key in self._stop_times_cache and 
            cache_key in self._stop_times_expiry and
            datetime.now() < self._stop_times_expiry[cache_key]):
            
            logger.debug(f"Returning cached stop times for {cache_key}")
            return self._stop_times_cache[cache_key]
            
        return None

    def cache_stop_times(self, provider_id: str, stop_id: str, stop_times: Dict):
        """
        Cache stop times for a stop.
        
        Args:
            provider_id: The ID of the provider
            stop_id: The ID of the stop
            stop_times: The stop times data to cache
        """
        cache_key = f"{provider_id}_{stop_id}"
        
        self._stop_times_cache[cache_key] = stop_times
        self._stop_times_expiry[cache_key] = datetime.now() + self.stop_times_cache_duration
        
        logger.debug(f"Cached stop times for {cache_key}")

    def clear_stop_times_cache(self):
        """Clear the stop times cache."""
        self._stop_times_cache.clear()
        self._stop_times_expiry.clear()
        logger.info("Cleared stop times cache")

    def clear_feed_cache(self):
        """Clear the feed cache."""
        self._feeds.clear()
        logger.info("Cleared feed cache")

    def close(self):
        """Close all loaders and clear caches."""
        for loader in self._loaders.values():
            loader.close()
        self._loaders.clear()
        self._feeds.clear()
        self.clear_stop_times_cache()
        logger.info("Closed all loaders and cleared caches")

    def __del__(self):
        """Ensure resources are cleaned up."""
        self.close() 