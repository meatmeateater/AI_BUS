import sys
import os
import json

GRAPH_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'static', 'bus_graph.json')

def debug_connectivity():
    if not os.path.exists(GRAPH_FILE):
        return

    with open(GRAPH_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        stops = data.get("stops", {})
        
    s1 = "新北板橋公車站"
    s2 = "臺北客運板橋前站(藝文)"
    
    print(f"--- Debugging {s1} ---")
    if s1 in stops:
        print(f"Routes: {stops[s1]['routes']}")
    else:
        print("Not in graph")

    print(f"\n--- Debugging {s2} ---")
    if s2 in stops:
        print(f"Routes: {stops[s2]['routes']}")
    else:
        print("Not in graph")
        
    # Check intersection
    if s1 in stops and s2 in stops:
        r1 = set(stops[s1]['routes'])
        r2 = set(stops[s2]['routes'])
        common = r1.intersection(r2)
        print(f"\nCommon Routes: {common}")

if __name__ == "__main__":
    debug_connectivity()
