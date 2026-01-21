import sys
import os
import json
from collections import deque

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from graph_engine import GraphEngine

GRAPH_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'static', 'bus_graph.json')

def debug_failures():
    ge = GraphEngine(GRAPH_FILE)
    ge.load_graph()
    
    start_node = "捷運大安森林公園站"
    if start_node not in ge.stops:
        start_node = "大安森林公園"
        
    # List of failures from report
    failures = [
        "富士坪21號", "圳阿公", "善息寺", "龜子山", "黃櫸皮寮", 
        "溪邊寮", "汐止火車站(公園)", "新民國中", "八連二抽水站", "黎明清境"
    ]
    
    print(f"Graph loaded. Stops: {len(ge.stops)}, Routes: {len(ge.routes)}")
    print(f"Start Node: {start_node}")
    
    for fail in failures:
        print(f"\n--- Analyzing: {fail} ---")
        
        # 1. Check Existence / Match
        real_name = ge.find_best_stop_match(fail)
        if not real_name:
            print(f"  [X] Name Mismatch: '{fail}' not found in graph (even partial).")
            continue
        print(f"  [O] Match Found: '{real_name}'")
        
        # 2. Check Routes at destination
        routes = ge.stops[real_name]["routes"]
        print(f"  routes serving this stop: {routes}")
        if not routes:
             print("  [X] Orphan Node: No routes connected.")
             continue
             
        # 3. BFS for Reachability (Unlimited Depth)
        # Check if reachable at all
        visited = {start_node}
        queue = deque([(start_node, 0)]) # (node, transfers)
        
        # Note: Standard BFS on stops is hard because edges are routes.
        # We assume 1 hop = same route.
        # This simple BFS might be slow if not optimized.
        # Let's try a simplified reachability check: 
        # Can we reach it? And how many route-hops?
        
        found = False
        min_detail = None
        
        # Heuristic BFS for "Transfers"
        # State: (Stop, CurrentRoute, TransferCount)
        # To make it fast, we just want to know MIN transfers.
        # We can compute this by BFS on "Route Graph"?
        # Routes are nodes, edges if they share a stop.
        # Start Routes -> End Routes.
        
        start_routes = set(ge.stops[start_node]["routes"])
        end_routes = set(routes)
        
        # BFS on Routes
        visited_routes = set(start_routes)
        route_queue = deque([(r, 0) for r in start_routes])
        
        reached_dist = None
        
        while route_queue:
            curr_r, depth = route_queue.popleft()
            
            if curr_r in end_routes:
                reached_dist = depth
                break
                
            if depth >= 3: # Limit checking to 3 transfers
                continue
            
            # Find neighbors (routes intersecting with curr_r)
            # This is expensive if not pre-calculated.
            # ge.routes[curr_r] = [StopA, StopB...]
            # For each stop in curr_r, get all other routes.
            pass 
            # Optimization: Just scan stops
            for s in ge.routes.get(curr_r, []):
                for next_r in ge.stops[s]["routes"]:
                    if next_r not in visited_routes:
                        visited_routes.add(next_r)
                        route_queue.append((next_r, depth + 1))
                        
        if reached_dist is not None:
            print(f"  [O] Reachable! Min Transfers needed: {reached_dist}")
            if reached_dist > 1:
                print(f"  => Current algo fails because it only looks for 1 Transfer.")
            else:
                 print(f"  => Should be found by current algo (0 or 1 transfer). Why failed?")
        else:
            print(f"  [X] Unreachable (within 3 transfers) or Disconnected Component.")

if __name__ == "__main__":
    debug_failures()
