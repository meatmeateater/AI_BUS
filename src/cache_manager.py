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

from config.settings import CACHE_TTL, CACHE_MAXSIZE, CACHE_STATIC_TTL

logger = logging.getLogger(__name__)

# 即時資料快取（TTL=60s）
_route_cache = TTLCache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL)
_cache_lock = threading.Lock()

# 靜態資料快取（班表/班距，TTL=3600s）— P-5 修復
_static_cache = TTLCache(maxsize=500, ttl=CACHE_STATIC_TTL)
_static_cache_lock = threading.Lock()

# in-flight 註冊表：防止同一 route_id 被多執行緒並行 fetch — M-1 修復
_inflight: Dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()


class CacheManager:
    """
    靜態快取管理器。
    - 所有方法都是 @staticmethod，不需要實例化。
    - 透過 _cache_lock 保證多執行緒安全。
    """

    @staticmethod
    def get_cached_route_data(route_id: str) -> Optional[Dict[str, Any]]:
        """從即時快取取得路線資料，未命中回傳 None。"""
        with _cache_lock:
            return _route_cache.get(route_id)

    @staticmethod
    def set_route_data(route_id: str, data: Dict[str, Any]):
        """將路線資料寫入即時快取。空資料不寫入。"""
        if data:
            with _cache_lock:
                _route_cache[route_id] = data

    @staticmethod
    def get_cached_static_data(key: str) -> Optional[Any]:
        """從靜態快取取得資料（班表/班距，TTL=3600s）。"""
        with _static_cache_lock:
            return _static_cache.get(key)

    @staticmethod
    def set_static_data(key: str, data: Any):
        """將靜態資料寫入長期快取（班表/班距）。"""
        if data:
            with _static_cache_lock:
                _static_cache[key] = data

    @staticmethod
    def get_or_fetch(
        route_id: str,
        fetch_func: Callable[[str], Optional[Dict[str, Any]]]
    ) -> Optional[Dict[str, Any]]:
        """
        Cache-Aside 模式：先查快取，未命中再 fetch。

        M-1 修復：加入 in-flight 事件機制，避免對同一 route_id
        結束快取時多執行緒同時發送重複 API 請求（dog-pile effect）。
        """
        # 步驟 1: 快取命中則直接回傳
        with _cache_lock:
            cached = _route_cache.get(route_id)
        if cached:
            return cached

        # 步驟 2: 檢查是否已有其他執行緒正在 fetch
        with _inflight_lock:
            if route_id in _inflight:
                event = _inflight[route_id]
            else:
                event = threading.Event()
                _inflight[route_id] = event
                event = None  # 標記為「我來做 fetch」

        if event is not None:
            # 其他執行緒已在 fetch，等 10 秒候它完成
            event.wait(timeout=10)
            with _cache_lock:
                return _route_cache.get(route_id)  # 可能已由其他執行緒寫入

        # 步驟 3: 我來做 fetch
        logger.debug(f"Cache miss for {route_id}, fetching...")
        try:
            data = fetch_func(route_id)
            if data:
                with _cache_lock:
                    _route_cache[route_id] = data
            return data
        finally:
            # 通知其他等候中的執行緒
            with _inflight_lock:
                ev = _inflight.pop(route_id, None)
            if ev:
                ev.set()
