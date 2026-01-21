import sys
import os
import json
import time

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_server import calculate_best_route, plan_trip, graph_engine
from graph_engine import GraphEngine

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
    if start_point not in all_stops:
        start_point = "大安森林公園"
        if start_point not in all_stops:
            print("Start point not found in graph.")
            return

    print(f"Starting Benchmark from: {start_point}")
    
    # Test Failures
    destinations = [
        "富士坪21號", "圳阿公", "善息寺", "龜子山", "黃櫸皮寮", 
        "溪邊寮", "汐止火車站(公園)", "新民國中", "八連二抽水站", "黎明清境", 
        "玉皇宮", "大埔路口", "圓山頂", "台貿八村", "鐘鼎山林", 
        "雙溪淨水場", "新潭路1段212號", "山豬湖", "漁人碼頭", "鳳福公園", 
        "山中湖", "公館華廈"
    ]
    
    report_file = "benchmark_fixes.md" 
    
    print(f"Testing {len(destinations)} routes... (This may take a while)")
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# Taipei Bus AI Route Benchmark\n\n")
        f.write(f"**Start Point**: {start_point}\n")
        f.write(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("| ID | Destination | Status | Total Time | Route Summary | Route Details |\n")
        f.write("|----|-------------|--------|------------|---------------|---------------|\n")
        
        for i, dest in enumerate(destinations):
            print(f"Processing {i+1}/50: -> {dest}")
            try:
                # Add slight delay
                time.sleep(0.5) 
                
                # Use structure data
                best = calculate_best_route(start_point, dest)
                
                status = "Fail"
                total_time = "N/A"
                summary = "Route not found"
                details = ""
                
                if "error" not in best:
                    status = "Success"
                    total_time = f"{int(best['total_time'])} min"
                    if "SafeWarn" in best.get("safety_note", ""):
                         total_time += " (SafeWarn)"
                    
                    # Build Summary & Details
                    seg_strs = []
                    detail_strs = []
                    
                    for seg in best["segments"]:
                        r = seg["route"]
                        s_from = seg["from"]
                        s_to = seg["to"]
                        
                        # Get stops
                        stops = graph_engine.get_route_stops(r, s_from, s_to)
                        stop_count = len(stops)
                        
                        seg_strs.append(r)
                        
                        # Format stop list
                        stop_list_str = " -> ".join(stops)
                        detail_strs.append(f"**【{r}】** ({stop_count}站):<br>{stop_list_str}")
                    
                    summary = " -> ".join(seg_strs)
                    if best["type"] == "transfer_greedy":
                        summary += " -> (TBD) (Greedy)"
                    elif best["type"] == "direct":
                        summary += " (Direct)"
                        
                    details = "<br><br>".join(detail_strs)
                
                row = f"| {i+1} | {dest} | {status} | {total_time} | {summary} | {details} |\n"
                f.write(row)
                f.flush()
                
            except Exception as e:
                f.write(f"| {i+1} | {dest} | Error | - | {str(e)} | |\n")
                
    print(f"\nBenchmark completed. Report saved to {report_file}")

if __name__ == "__main__":
    run_benchmark()
