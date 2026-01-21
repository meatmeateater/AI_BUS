import sys
import os
import json

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from graph_engine import GraphEngine

GRAPH_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'static', 'bus_graph.json')

def debug_pathfinding():
    print(f"Loading graph from {GRAPH_FILE}...")
    ge = GraphEngine(GRAPH_FILE)
    ge.load_graph()
    
    start = "新北板橋公車站"
    end = "臺北客運板橋前站(藝文)"
    
    print(f"\n--- Debugging: {start} -> {end} ---")
    
    start_routes = set(ge.stops[start]["routes"])
    end_routes = set(ge.stops[end]["routes"])
    common = start_routes.intersection(end_routes)
    print(f"Common Routes: {common}")
    
    for r in common:
        dist = ge.get_route_stop_distance(r, start, end)
        print(f"Route {r} Distance: {dist}")
        
    print("\n--- Testing find_candidate_paths ---")
    candidates = ge.find_candidate_paths(start, end)
    print(f"Candidates Found: {len(candidates)}")
    for c in candidates:
        print(c)

if __name__ == "__main__":
    debug_pathfinding()
