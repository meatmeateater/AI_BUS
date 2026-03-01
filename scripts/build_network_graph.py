import os
import sys
import json
import time
import logging
from typing import Dict, List

# Setup paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from src.crawler_core import BusCrawler

# Config
ROUTES_MAP_FILE = os.path.join(BASE_DIR, 'data', 'static', 'routes_map.json')
GRAPH_FILE = os.path.join(BASE_DIR, 'data', 'static', 'bus_graph.json')
LOG_DIR = os.path.join(BASE_DIR, 'data', 'logs')

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Setup logging (this is a standalone script, so basicConfig is appropriate here)
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
    logger.info("Starting graph builder...")
    
    # 1. Load routes map
    if not os.path.exists(ROUTES_MAP_FILE):
        logger.error(f"Routes map not found at {ROUTES_MAP_FILE}")
        return

    with open(ROUTES_MAP_FILE, 'r', encoding='utf-8') as f:
        routes_map = json.load(f)  # {"Name": "ID"}

    logger.info(f"Loaded {len(routes_map)} routes.")

    # Data structures
    # stops: { "StopName": { "routes": ["RouteName"] } }
    # routes_data: { "RouteName": ["StopName1", "StopName2", ...] }
    
    stops_index: Dict[str, Dict[str, List[str]]] = {}
    routes_data: Dict[str, List[str]] = {}

    count = 0
    total = len(routes_map)
    
    for route_name, route_id in routes_map.items():
        count += 1
        logger.info(f"[{count}/{total}] Processing {route_name} ({route_id})...")
        
        # Fetch static data only (skip real-time ETA)
        data = BusCrawler.get_route_data(route_name, only_static=True)
        
        if not data:
            logger.warning(f"Failed to fetch data for {route_name}")
            continue

        # Combine stops from both directions
        all_stops = []
        if "GoDirStops" in data and data["GoDirStops"]:
             all_stops.extend(data["GoDirStops"])
        if "BackDirStops" in data and data["BackDirStops"]:
             all_stops.extend(data["BackDirStops"])
             
        for stop in all_stops:
            s_name = stop.get("Name")
            if not s_name:
                continue
            
            if route_name not in routes_data:
                routes_data[route_name] = []
            if s_name not in routes_data[route_name]:
                routes_data[route_name].append(s_name)

            if s_name not in stops_index:
                stops_index[s_name] = {"routes": []}
            
            if route_name not in stops_index[s_name]["routes"]:
                stops_index[s_name]["routes"].append(route_name)

    # Save to file
    os.makedirs(os.path.dirname(GRAPH_FILE), exist_ok=True)
    
    graph_output = {
        "stops": stops_index,
        "routes": routes_data,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open(GRAPH_FILE, 'w', encoding='utf-8') as f:
        json.dump(graph_output, f, ensure_ascii=False, indent=2)
        
    logger.info(f"Graph built! Saved {len(stops_index)} stops and {len(routes_data)} routes to {GRAPH_FILE}")


if __name__ == "__main__":
    build_graph()
