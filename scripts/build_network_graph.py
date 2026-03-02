import os
import sys
import json
import time
import logging
from typing import Dict, List, Any

# Setup paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from src.crawler_core import BusCrawler

# Config
ROUTES_MAP_FILE = os.path.join(BASE_DIR, 'data', 'static', 'routes_map.json')
GRAPH_FILE = os.path.join(BASE_DIR, 'data', 'static', 'bus_graph.json')
LOG_DIR = os.path.join(BASE_DIR, 'data', 'logs')

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'graph_builder.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DIR_GO = "__go"
DIR_BACK = "__back"


def build_graph():
    logger.info("Starting graph builder (v3: direction-aware + UID + GPS)...")
    
    if not os.path.exists(ROUTES_MAP_FILE):
        logger.error(f"Routes map not found at {ROUTES_MAP_FILE}")
        return

    with open(ROUTES_MAP_FILE, 'r', encoding='utf-8') as f:
        routes_map = json.load(f)

    logger.info(f"Loaded {len(routes_map)} routes.")

    # Data structures
    # stops: { "StopName": { "routes": ["307__go", ...], "lat": float, "lon": float } }
    # routes: { "307__go": ["StopName1", "StopName2", ...] }
    # stop_uid_map: { "route_key": { "StopName": "StopUID" } }
    
    stops_index: Dict[str, Dict[str, Any]] = {}
    routes_data: Dict[str, List[str]] = {}
    stop_uid_map: Dict[str, Dict[str, str]] = {}  # P1: UID 映射

    count = 0
    total = len(routes_map)
    
    for route_name, route_id in routes_map.items():
        count += 1
        logger.info(f"[{count}/{total}] Processing {route_name}...")
        
        data = BusCrawler.get_route_data(route_name, only_static=True)
        
        if not data:
            logger.warning(f"Failed to fetch data for {route_name}")
            continue

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
