import threading
from cachetools import TTLCache
import logging
from typing import Optional, Dict, Any, Callable

from config.settings import CACHE_TTL, CACHE_MAXSIZE

logger = logging.getLogger(__name__)

# Thread-safe cache storage
_route_cache = TTLCache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL)
_cache_lock = threading.Lock()


class CacheManager:
    @staticmethod
    def get_cached_route_data(route_id: str) -> Optional[Dict[str, Any]]:
        """Get route data from cache if available (thread-safe)."""
        with _cache_lock:
            return _route_cache.get(route_id)

    @staticmethod
    def set_route_data(route_id: str, data: Dict[str, Any]):
        """Store route data in cache (thread-safe)."""
        if data:
            with _cache_lock:
                _route_cache[route_id] = data

    @staticmethod
    def get_or_fetch(route_id: str, fetch_func: Callable[[str], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        """Get from cache, or fetch using fetch_func and cache the result (thread-safe)."""
        with _cache_lock:
            cached = _route_cache.get(route_id)
        if cached:
            return cached
            
        logger.debug(f"Cache miss for {route_id}, fetching...")
        data = fetch_func(route_id)
        
        if data:
            with _cache_lock:
                _route_cache[route_id] = data
            
        return data
