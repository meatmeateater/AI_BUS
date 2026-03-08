# ===========================================================================
#  cache_manager.py — 執行緒安全的即時資料快取管理器
#
#  使用 cachetools.TTLCache 提供 TTL 過期機制，
#  外加 threading.Lock 保護所有讀寫操作（因為 ThreadPoolExecutor 會並行存取）
# ===========================================================================

import threading
from cachetools import TTLCache
import logging
from typing import Optional, Dict, Any, Callable

from config.settings import CACHE_TTL, CACHE_MAXSIZE

logger = logging.getLogger(__name__)

# 模組層級的快取實例 + 鎖
# 所有 CacheManager 的靜態方法共用同一份快取
_route_cache = TTLCache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL)
_cache_lock = threading.Lock()


class CacheManager:
    """
    靜態快取管理器。
    - 所有方法都是 @staticmethod，不需要實例化。
    - 透過 _cache_lock 保證多執行緒安全。
    """

    @staticmethod
    def get_cached_route_data(route_id: str) -> Optional[Dict[str, Any]]:
        """從快取取得路線資料，未命中回傳 None。"""
        with _cache_lock:
            return _route_cache.get(route_id)

    @staticmethod
    def set_route_data(route_id: str, data: Dict[str, Any]):
        """將路線資料寫入快取。空資料不寫入。"""
        if data:
            with _cache_lock:
                _route_cache[route_id] = data

    @staticmethod
    def get_or_fetch(
        route_id: str,
        fetch_func: Callable[[str], Optional[Dict[str, Any]]]
    ) -> Optional[Dict[str, Any]]:
        """
        嘗試從快取取得，若未命中則呼叫 fetch_func 抓取並寫入快取。
        這是最常用的存取模式 (Cache-Aside Pattern)。
        
        注意：fetch_func 在鎖外執行，避免長時間阻塞其他執行緒。
        """
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
