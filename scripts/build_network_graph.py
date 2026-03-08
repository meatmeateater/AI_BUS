# ===========================================================================
#  build_network_graph.py — 公車路網圖建構腳本
#
#  從 TDX API 爬取所有路線的站序資料，建構離線路網圖 (bus_graph.json)。
#  這是一次性的離線處理，產出的 JSON 檔供 GraphEngine 使用。
#
#  執行時間：約 3-4 小時（受 TDX API 限流影響）
#  產出格式：v3（方向感知 + StopUID + GPS 座標）
#
#  使用方式：
#    1. 先執行 init_static_data.py 產生 routes_map.json
#    2. 再執行本腳本建構 bus_graph.json
# ===========================================================================

import os
import sys
import json
import time
import logging
from typing import Dict, List, Any

# 將專案根目錄加入 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from src.crawler_core import BusCrawler
from config.settings import DIR_GO, DIR_BACK

# 檔案路徑
ROUTES_MAP_FILE = os.path.join(BASE_DIR, 'data', 'static', 'routes_map.json')
GRAPH_FILE = os.path.join(BASE_DIR, 'data', 'static', 'bus_graph.json')
LOG_DIR = os.path.join(BASE_DIR, 'data', 'logs')

os.makedirs(LOG_DIR, exist_ok=True)

# Logging 同時輸出到檔案和終端機
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'graph_builder.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def build_graph():
    """
    主流程：逐一爬取每條路線的站序，組裝成圖結構後存檔。

    資料結構：
        stops:        { "站名": {"routes": ["307__go", ...], "lat": ..., "lon": ...} }
        routes:       { "307__go": ["站A", "站B", ...] }  (有序站序)
        stop_uid_map: { "307__go": {"站A": "TPE12345", ...} }
    """
    logger.info("Starting graph builder (v3: direction-aware + UID + GPS)...")

    if not os.path.exists(ROUTES_MAP_FILE):
        logger.error(f"Routes map not found at {ROUTES_MAP_FILE}")
        return

    with open(ROUTES_MAP_FILE, 'r', encoding='utf-8') as f:
        routes_map = json.load(f)

    logger.info(f"Loaded {len(routes_map)} routes.")

    # 三個核心資料結構
    stops_index: Dict[str, Dict[str, Any]] = {}     # 站點 → 路線 + GPS
    routes_data: Dict[str, List[str]] = {}            # 路線 → 站序
    stop_uid_map: Dict[str, Dict[str, str]] = {}      # 路線 → 站名 → UID

    count = 0
    total = len(routes_map)
    
    for route_name, route_id in routes_map.items():
        count += 1
        logger.info(f"[{count}/{total}] Processing {route_name}...")
        
        data = BusCrawler.get_route_data(route_name, only_static=True)
        
        if not data:
            logger.warning(f"Failed to fetch data for {route_name}")
            # Rate limit backoff: if we failed, wait longer before next request
            time.sleep(2)
            continue
        
        # Rate limit: pause between requests to avoid 429
        time.sleep(3)

        directions = [
            (DIR_GO, data.get("GoDirStops", [])),
            (DIR_BACK, data.get("BackDirStops", []))
        ]
        
        for dir_suffix, dir_stops in directions:
            if not dir_stops:
                continue
                
            route_key = route_name + dir_suffix
            routes_data[route_key] = []
            stop_uid_map[route_key] = {}
            
            for stop in dir_stops:
                s_name = stop.get("Name")
                s_uid = stop.get("StopUID")
                if not s_name:
                    continue
                
                # 路線站序
                routes_data[route_key].append(s_name)
                
                # P1: UID 映射 (route_key -> stop_name -> StopUID)
                if s_uid:
                    stop_uid_map[route_key][s_name] = s_uid

                # 站點索引
                if s_name not in stops_index:
                    stops_index[s_name] = {"routes": []}
                
                if route_key not in stops_index[s_name]["routes"]:
                    stops_index[s_name]["routes"].append(route_key)
                
                # P2: GPS 座標 (取第一次遇到的值)
                if "lat" not in stops_index[s_name]:
                    pos = stop.get("StopPosition", {})
                    lat = pos.get("PositionLat")
                    lon = pos.get("PositionLon")
                    if lat and lon:
                        stops_index[s_name]["lat"] = lat
                        stops_index[s_name]["lon"] = lon

    # Save
    os.makedirs(os.path.dirname(GRAPH_FILE), exist_ok=True)
    
    graph_output = {
        "stops": stops_index,
        "routes": routes_data,
        "stop_uid_map": stop_uid_map,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": 3,
        "direction_aware": True
    }
    
    with open(GRAPH_FILE, 'w', encoding='utf-8') as f:
        json.dump(graph_output, f, ensure_ascii=False, indent=2)
        
    logger.info(f"Graph built! {len(stops_index)} stops, {len(routes_data)} directed routes -> {GRAPH_FILE}")


if __name__ == "__main__":
    build_graph()
