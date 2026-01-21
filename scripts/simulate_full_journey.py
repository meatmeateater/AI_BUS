import sys
import os
import json
import time
import random

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_server import calculate_best_route, graph_engine

GRAPH_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'static', 'bus_graph.json')

def load_all_stops():
    with open(GRAPH_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return list(data.get("stops", {}).keys())

def get_full_path(start, end, depth=0):
    if depth > 3:
        return {"status": "Fail", "path": [], "time": 0, "reason": "Max depth reached"}
    
    # Add delay to avoid 429
    time.sleep(0.3)
    
    try:
        best = calculate_best_route(start, end)
    except Exception as e:
        return {"status": "Error", "path": [], "time": 0, "reason": str(e)}

    if "error" in best:
        return {"status": "Fail", "path": [], "time": 0, "reason": best["error"]}
    
    # Parse Result
    # Segment 1 is always present
    seg1 = best["segments"][0]
    route_name = seg1["route"]
    time_taken = best.get("total_time", 0) # This is Static + Wait for Leg 1
    
    current_step = {
        "bus": route_name,
        "from": start,
        "to": seg1["to"], # If direct, this is end. If greedy, this is transfer_stop
        "time": time_taken
    }
    
    if best["type"] == "direct":
        return {
            "status": "Success",
            "path": [current_step],
            "time": time_taken,
            "reason": ""
        }
        
    elif best["type"] == "transfer_greedy":
        mid = best["transfer_stop"]
        # Recursive Step
        next_result = get_full_path(mid, end, depth + 1)
        
        # Combine
        full_path = [current_step] + next_result["path"]
        total_time = time_taken + next_result["time"]
        
        return {
            "status": next_result["status"],
            "path": full_path,
            "time": total_time, # Approximate
            "reason": next_result.get("reason", "")
        }
    
    return {"status": "Unknown", "path": [], "time": 0}

def run_simulation():
    # Ensure graph engine is loaded
    if not graph_engine.is_loaded:
        graph_engine.load_graph()

    print("Loading stops...")
    all_stops = load_all_stops()
    
    start_point = "捷運大安森林公園站"
    
    # 1. Select Taipei 101
    taipei_101 ="捷運台北101/世貿站(信義)"
    if taipei_101 not in all_stops:
         # Fallback search
        candidates = [s for s in all_stops if "台北101" in s]
        if candidates:
            taipei_101 = candidates[0]
        else:
            taipei_101 = "台北101"

    # 2. Pick 49 Random
    pool = [s for s in all_stops if s != start_point and s != taipei_101]
    random_stops = random.sample(pool, 49)
    destinations = [taipei_101] + random_stops
    
    report_file = "simulation_report.md" 
    
    print(f"Simulating {len(destinations)} full journeys... (Start: {start_point})")
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# Full Journey Simulation Report\n\n")
        f.write(f"**Start Point**: {start_point}\n")
        f.write(f"**Method**: Recursive Greedy Simulation (Depth Limit: 3)\n")
        f.write(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("| ID | Destination | Status | Full Route (Bus @ Transfer) | Total Time |\n")
        f.write("|----|-------------|--------|-----------------------------|------------|\n")
        
        for i, dest in enumerate(destinations):
            print(f"Processing {i+1}/50: -> {dest}")
            
            result = get_full_path(start_point, dest)
            
            # Format Output
            # Wanted: "Tell me transfer stops and buses"
            # Format: [204] -> 捷運東門站 -> [信義幹線] -> 終點
            
            route_str = ""
            if result["status"] == "Success":
                steps = []
                for step in result["path"]:
                    bus = step["bus"]
                    transfer_at = step["to"]
                    if transfer_at == dest:
                        steps.append(f"【{bus}】 (抵達)")
                    else:
                        steps.append(f"【{bus}】 -> 轉乘點: `{transfer_at}`")
                route_str = " -> ".join(steps)
            else:
                route_str = f"Failed: {result.get('reason', 'Unknown')}"
                
            row = f"| {i+1} | {dest} | {result['status']} | {route_str} | {int(result['time'])} min |\n"
            f.write(row)
            f.flush()
            
    print(f"\nSimulation completed. Report saved to {report_file}")

if __name__ == "__main__":
    run_simulation()
