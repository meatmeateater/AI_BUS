from cachetools import TTLCache
import time
from typing import Optional, Dict, Any, Callable

# Cache storage: 1000 items, 180 seconds TTL (3 minutes)
_route_cache = TTLCache(maxsize=1000, ttl=180)

class CacheManager:
    @staticmethod
    def get_cached_route_data(route_id: str) -> Optional[Dict[str, Any]]:
        """
        Get route data from cache if available.
        """
        return _route_cache.get(route_id)

    @staticmethod
    def set_route_data(route_id: str, data: Dict[str, Any]):
        """
        Store route data in cache.
        """
        if data:
            _route_cache[route_id] = data

    @staticmethod
    def get_or_fetch(route_id: str, fetch_func: Callable[[str], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        """
        Get from cache, or fetch using fetch_func and cache the result.
        """
        cached = _route_cache.get(route_id)
        if cached:
            # print(f"Cache Hit for {route_id}") # Debug
            return cached
            
        print(f"Cache Miss for {route_id}, fetching...")
        data = fetch_func(route_id)
        
        if data:
            _route_cache[route_id] = data
            
        return data
