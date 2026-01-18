import os
import sys
import json
import time
import logging
from typing import Dict, List, Set

# Setup paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from src.crawler_core import BusCrawler

# Config
ROUTES_MAP_FILE = os.path.join(BASE_DIR, 'data', 'static', 'routes_map.json')
GRAPH_FILE = os.path.join(BASE_DIR, 'data', 'static', 'bus_graph.json')
LOG_DIR = os.path.join(BASE_DIR, 'data', 'logs')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'graph_builder.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def build_graph():
    logging.info("Starting graph builder...")
    
    # 1. Load routes map
    if not os.path.exists(ROUTES_MAP_FILE):
        logging.error(f"Routes map not found at {ROUTES_MAP_FILE}")
        return

    with open(ROUTES_MAP_FILE, 'r', encoding='utf-8') as f:
        routes_map = json.load(f) # {"Name": "ID"}

    logging.info(f"Loaded {len(routes_map)} routes.")

    # Data structures
    # stops: { "StopName": { "routes": ["RouteName"] } }
    # routes_data: { "RouteName": ["StopName1", "StopName2", ...] }
    
    stops_index: Dict[str, Dict[str, List[str]]] = {}
    routes_data: Dict[str, List[str]] = {}

    count = 0
    total = len(routes_map)
    
    for route_name, route_id in routes_map.items():
        count += 1
        print(f"[{count}/{total}] Processing {route_name} ({route_id})...")
        
        # Fetch static data only
        data = BusCrawler.get_route_data(route_id, only_static=True)
        
        if not data:
            logging.warning(f"Failed to fetch data for {route_name}")
            continue
            
        # Process stops
        # We need to capture both directions but treat them carefully.
        # For simplicity in navigation Plan V1, we will just list all stations this route passes through.
        # Ideally, we should separate directions, but graph logic can handle "Reachability".
        
        # Merge stops from both directions for the "Route coverage" list
        unique_stops_in_route = []
        
        # We also want to record directionality, but for V1 BFS, let's keep it undirected or simple directed.
        # Let's save the simplified list of stops for this route first.
        
        # Combine lists
        all_stops = []
        if "GoDirStops" in data and data["GoDirStops"]:
             all_stops.extend(data["GoDirStops"])
        if "BackDirStops" in data and data["BackDirStops"]:
             all_stops.extend(data["BackDirStops"])
             
        for stop in all_stops:
            s_name = stop.get("Name")
            if not s_name:
                continue
            
            # Update Routes Data
            # (Wait, Graph connection needs Order. But for "Transfer", we just need to know "Route X goes to Station Y")
            # If I am at Station A, and I want to go to Station B.
            # I find routes at A: [R1, R2]
            # I find routes at B: [R2, R3]
            # Intersection: R2. So take R2.
            # This "Set Intersection" logic works without knowing the order, 
            # AS LONG AS R2 actually goes A -> B. (This is the catch, direction matters)
            # But usually bus routes are loops or bi-directional. 
            # For V1, we assume if a bus stops at A and B, it connects them. (Roughly true)
            
            if route_name not in routes_data:
                routes_data[route_name] = []
            if s_name not in routes_data[route_name]:
                routes_data[route_name].append(s_name)

            # Update Stops Index
            if s_name not in stops_index:
                stops_index[s_name] = {"routes": []}
            
            if route_name not in stops_index[s_name]["routes"]:
                stops_index[s_name]["routes"].append(route_name)

        # Sleep slightly to be nice
        # time.sleep(0.1) 

    # Save to file
    graph_output = {
        "stops": stops_index,
        "routes": routes_data,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open(GRAPH_FILE, 'w', encoding='utf-8') as f:
        json.dump(graph_output, f, ensure_ascii=False, indent=2)
        
    logging.info(f"Graph built! Saved {len(stops_index)} stops and {len(routes_data)} routes to {GRAPH_FILE}")
    print(f"Graph building complete. File saved to {GRAPH_FILE}")

if __name__ == "__main__":
    build_graph()
