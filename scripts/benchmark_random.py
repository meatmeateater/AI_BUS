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

def run_benchmark():
    # Ensure graph engine is loaded
    if not graph_engine.is_loaded:
        graph_engine.load_graph()

    print("Loading stops...")
    all_stops = load_all_stops()
    
    start_point = "捷運大安森林公園站"
    
    # 1. Select Taipei 101 (Find best match)
    taipei_101 = "捷運台北101/世貿站(信義)"
    if taipei_101 not in all_stops:
        # Fallback search
        candidates = [s for s in all_stops if "台北101" in s]
        if candidates:
            taipei_101 = candidates[0]
        else:
            print("Warning: Taipei 101 not found! Using fallback.")
            taipei_101 = "台北101"

    # 2. Pick 49 Random
    # Filter out start point and 101
    pool = [s for s in all_stops if s != start_point and s != taipei_101]
    random_stops = random.sample(pool, 49)
    
    destinations = [taipei_101] + random_stops
    
    report_file = "benchmark_random.md" 
    
    print(f"Testing {len(destinations)} routes... (Start: {start_point})")
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# Random 50 Benchmark Report\n\n")
        f.write(f"**Start Point**: {start_point}\n")
        f.write(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("| ID | Destination | Status | Leg 1 Time | Route Summary | Route Details |\n")
        f.write("|----|-------------|--------|------------|---------------|---------------|\n")
        
        for i, dest in enumerate(destinations):
            print(f"Processing {i+1}/50: -> {dest}")
            try:
                # Add slight delay
                time.sleep(0.2) 
                
                best = calculate_best_route(start_point, dest)
                
                status = "Fail"
                total_time = "N/A"
                summary = "Route not found"
                details = ""
                
                if "error" not in best:
                    status = "Success"
                    total_time = f"{int(best['total_time'])} min"
                    
                    seg_strs = []
                    detail_strs = []
                    
                    for seg in best["segments"]:
                        r = seg["route"]
                        s_from = seg["from"]
                        s_to = seg["to"]
                        
                        stops = graph_engine.get_route_stops(r, s_from, s_to)
                        stop_count = len(stops)
                        
                        seg_strs.append(r)
                        stop_list_str = " -> ".join(stops)
                        detail_strs.append(f"**【{r}】** ({stop_count}站):<br>{stop_list_str}")
                    
                    summary = " -> ".join(seg_strs)
                    if best["type"] == "transfer_greedy":
                        summary += " -> (TBD)"
                    elif best["type"] == "direct":
                        summary += " (Direct)"
                        
                    details = "<br><br>".join(detail_strs)
                
                row = f"| {i+1} | {dest} | {status} | {total_time} | {summary} | {details} |\n"
                f.write(row)
                f.flush()
                
            except Exception as e:
                f.write(f"| {i+1} | {dest} | Error | - | {str(e)} | |\n")
                
    print(f"\nRandom Benchmark completed. Report saved to {report_file}")

if __name__ == "__main__":
    run_benchmark()
