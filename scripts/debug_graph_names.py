import sys
import os
import json

GRAPH_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'static', 'bus_graph.json')

def search_stops():
    if not os.path.exists(GRAPH_FILE):
        print("Graph file missing")
        return

    with open(GRAPH_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        stops = data.get("stops", {})
        
    print(f"Total stops in graph: {len(stops)}")
    
    print("\n--- Searching for '大安森林公園' ---")
    matches = [s for s in stops.keys() if "大安森林公園" in s]
    for m in matches[:10]:
        print(m)

if __name__ == "__main__":
    search_stops()
