# ===========================================================================
#  crawler_core.py — TDX API 資料抓取適配器
#
#  封裝 TDXClient，提供統一的 get_route_data() 介面。
#  負責將 TDX API 回傳的原始 JSON 組裝成本系統使用的格式：
#    { "GoDirStops": [...], "BackDirStops": [...] }
#
#  執行緒安全：使用 double-check locking 確保 TDXClient 只初始化一次。
# ===========================================================================

import logging
import threading
from typing import Optional, Dict, Any, List
from .tdx_client import TDXClient

logger = logging.getLogger(__name__)


class BusCrawler:
    """
    公車資料抓取器（適配器模式）。

    - _client: 單例 TDXClient 實例
    - _client_lock: 保護 _client 初始化的鎖
    """
    _client = None
    _client_lock = threading.Lock()

    @classmethod
    def get_client(cls):
        """
        取得 TDXClient 單例（lazy initialization + double-check locking）。
        多執行緒下只會初始化一次。
        """
        if not cls._client:
            with cls._client_lock:
                if not cls._client:  # 取得鎖後再檢查一次
                    try:
                        cls._client = TDXClient()
                    except Exception as e:
                        logger.error(f"Failed to initialize TDXClient: {e}")
        return cls._client

    @classmethod
    def get_route_data(cls, route_name: str, only_static: bool = False, **kwargs) -> Optional[Dict[str, Any]]:
        """
        抓取指定路線的站牌資料（含即時 ETA）。

        Args:
            route_name: 路線名稱 (如 "307")
            only_static: True = 只抓站序（給建圖用），不抓即時 ETA
            **kwargs: 保留相容性，忽略

        Returns:
            格式化的路線資料字典：
            {
                "GoDirStops": [
                    {"Name": "站名", "StopUID": "UID", "ETA": 秒數, "NextDepTime": "HH:MM", ...},
                    ...
                ],
                "BackDirStops": [...]
            }
            失敗時回傳 None
        """
        client = cls.get_client()
        if not client:
            return None

        try:
            # ── 第一步：取得路線站序 ──
            # 優先查台北市，找不到再 fallback 到新北市（跨市路線）
            stops_data = client.get_stops(route_name, city="Taipei")
            if not stops_data:
                stops_data = client.get_stops(route_name, city="NewTaipei")
                if not stops_data:
                    logger.warning(f"No stops found for {route_name} in Taipei or NewTaipei")
                    return None
                city_found = "NewTaipei"
            else:
                city_found = "Taipei"

            # ── 第二步：取得即時到站時間 (ETA) ──
            # eta_map 結構：{ direction(0/1): { StopUID: eta_item } }
            eta_map: Dict[int, Dict[str, Any]] = {}
            if not only_static:
                etas_data = client.get_estimated_arrival(route_name, city=city_found)
                for item in etas_data:
                    d = item.get("Direction", 0)       # 0=去程, 1=返程
                    uid = item.get("StopUID")
                    if d not in eta_map:
                        eta_map[d] = {}
                    eta_map[d][uid] = item

            # ── 第三步：組裝結果 ──
            result: Dict[str, List[Dict[str, Any]]] = {
                "GoDirStops": [],
                "BackDirStops": []
            }

            for route_dir in stops_data:
                direction = route_dir.get("Direction", 0)  # 0=去程, 1=返程
                stops = route_dir.get("Stops", [])

                processed_stops = []
                for stop in stops:
                    uid = stop.get("StopUID")
                    name = stop.get("StopName", {}).get("Zh_tw", "Unknown")
                    position = stop.get("StopPosition", {})

                    stop_info: Dict[str, Any] = {
                        "Name": name,
                        "StopUID": uid,
                        "StopPosition": position,
                        "ETA": None,           # 到站秒數（None = 無資料）
                        "NextDepTime": None     # 下次發車時間 "HH:MM"
                    }

                    # 合併 ETA 資料（只在有抓即時資料時）
                    if direction in eta_map and uid in eta_map[direction]:
                        eta_item = eta_map[direction][uid]
                        # StopStatus: 0=正常, 1=尚未發車, 2=已過站, 3=末班
                        status = eta_item.get("StopStatus")
                        est_time = eta_item.get("EstimateTime")

                        if status == 0 and est_time is not None:
                            stop_info["ETA"] = est_time
                        elif status == 1:
                            stop_info["ETA"] = 65535  # 尚未發車標記
                            next_bus = eta_item.get("NextBusTime")
                            if next_bus:
                                try:
                                    # ISO 格式 "2026-03-08T14:30:00+08:00" → "14:30"
                                    stop_info["NextDepTime"] = next_bus.split("T")[1][:5]
                                except Exception:
                                    pass
                        elif status == 2:  # 已過站
                            stop_info["ETA"] = -2
                        elif status == 3:  # 末班車已過
                            stop_info["ETA"] = -3

                    processed_stops.append(stop_info)

                # 根據方向放入對應的 key
                if direction == 0:
                    result["GoDirStops"] = processed_stops
                elif direction == 1:
                    result["BackDirStops"] = processed_stops

            return result

        except Exception as e:
            logger.error(f"Error fetching TDX data for {route_name}: {e}")
            return None
