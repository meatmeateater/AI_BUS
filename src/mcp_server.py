from mcp.server.fastmcp import FastMCP
import json
import os
import difflib
import logging
from typing import Optional, List, Dict, Any

# Import local modules
# Hack to make imports work when running from script
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.crawler_core import BusCrawler
from src.cache_manager import CacheManager

from src.graph_engine import GraphEngine

# Config
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTES_MAP_FILE = os.path.join(BASE_DIR, 'data', 'static', 'routes_map.json')
GRAPH_FILE = os.path.join(BASE_DIR, 'data', 'static', 'bus_graph.json')

# Initialize Server
mcp = FastMCP("Taipei Bus AI")

# Load Routes Map
routes_map = {}
if os.path.exists(ROUTES_MAP_FILE):
    with open(ROUTES_MAP_FILE, 'r', encoding='utf-8') as f:
        routes_map = json.load(f)
else:
    logging.warning(f"Routes map not found at {ROUTES_MAP_FILE}")

# Initialize Graph Engine
graph_engine = GraphEngine(GRAPH_FILE)

def find_route_id(route_name: str) -> Optional[str]:
    """
    Fuzzy search for route ID by name.
    """
    if route_name in routes_map:
        return routes_map[route_name]
    
    # Fuzzy match
    matches = difflib.get_close_matches(route_name, routes_map.keys(), n=1, cutoff=0.6)
    if matches:
        return routes_map[matches[0]]
    
    return None

@mcp.tool()
def get_bus_arrival_time(route_name: str, stop_name: str, direction: str = "go") -> str:
    """
    查詢台北市公車到站時間。
    
    Args:
        route_name: 路線名稱 (如 "307", "299")
        stop_name: 站牌名稱 (如 "台北車站", "板橋")
        direction: 方向 (預設 "go" 去程, "back" 返程). 若不確定可嘗試不填，會搜尋雙向。
    
    Returns:
        String describing the arrival time or status.
    """
    # 1. Find Route ID
    route_id = find_route_id(route_name)
    if not route_id:
        return f"找不到路線：{route_name}"
    
    real_route_name = [k for k, v in routes_map.items() if v == route_id][0]

    # 2. Fetch Data (Cached)
    data = CacheManager.get_or_fetch(route_id, BusCrawler.get_route_data)
    if not data:
        return f"無法取得 {real_route_name} 的即時資料，請稍後再試。"

    # 3. Parse and Find Stop(s)
    # Data is the raw JSON structure we saw earlier.
    # It has "GoDirStops" and "BackDirStops" which are Lists of Stops.
    # Each Stop has "Name" and "BusTimeDesc" (or "BusETA", "ETA"?)
    # Based on the log, the JSON structure (objArr) has:
    # "GoDirStops": [ { "Name": "...", "BusETA": 0, "BusTimeDesc": "...", ... }, ... ]
    # Wait, the log showed `routeJsonString = JSON.stringify({...})`.
    # And inside `GoDirStops` items have `Name`, `BusETA` etc.
    
    # We need to search in both directions if not specified, or specific direction.
    
    found_stops = []
    
    directions_to_search = []
    if direction.lower() in ["go", "去程"]:
        directions_to_search.append(("去程", data.get("GoDirStops", [])))
    elif direction.lower() in ["back", "return", "返程"]:
        directions_to_search.append(("返程", data.get("BackDirStops", [])))
    else:
        # Search both
        directions_to_search.append(("去程", data.get("GoDirStops", [])))
        directions_to_search.append(("返程", data.get("BackDirStops", [])))

    for dir_name, stops in directions_to_search:
        if not stops:
            continue
            
        # Filter by stop name (Partial match)
        for stop in stops:
            s_name = stop.get("Name", "")
            if stop_name in s_name:
                eta = stop.get("ETA")
                next_dep = stop.get("NextDepTime")
                
                status_text = ""
                if next_dep:
                     status_text = f"預計 {next_dep} 發車"
                elif eta is not None:
                     eta_val = int(eta)
                     if eta_val < 0:
                         # Special codes based on observed JS
                         if eta_val in [65535, 65529]:
                             status_text = "尚未發車"
                         else:
                             status_text = "末班車已過"
                     elif eta_val <= 180:
                         status_text = "即將進站"
                     else:
                         mins = (eta_val + 59) // 60
                         status_text = f"還有 {mins} 分鐘"
                else:
                    status_text = "無資料"
                
                # Append to results
                vehicle_info = ""
                # Could add vehicle plate if available in future
                
                found_stops.append(f"往 {dir_name}：{s_name} - {status_text}")

    if not found_stops:
        return f"路線 {route_name} ({real_route_name}) 上找不到站牌「{stop_name}」。"

    return f"【{real_route_name}】目前狀態：\n" + "\n".join(found_stops)

@mcp.tool()
def plan_trip(start: str, end: str) -> str:
    """
    規劃公車路線 (A站 到 B站)。
    
    Args:
       start: 起點站牌名稱 (需精確或關鍵字)
       end: 終點站牌名稱
    """
    real_start = graph_engine.find_best_stop_match(start)
    real_end = graph_engine.find_best_stop_match(end)
    
    if not real_start or not real_end:
        return f"找不到從「{start}」到「{end}」的建議路線。請確認站牌名稱是否正確。"

    # Simply BFS for now based on static graph
    plan = graph_engine.find_path_bfs(real_start, real_end)
    
    if not plan:
        return f"找不到從 {real_start} 到 {real_end} 的建議路線。"
        
    response = ""
    if plan["type"] == "direct":
        seg = plan["segments"][0]
        route = seg['route']
        
        # Format basics
        response = f"建議路線 (直達)：\n請搭乘【{route}】\n從 {seg['from']} 上車\n抵達 {seg['to']}"
        
        # Add real-time status
        # We reuse the get_bus_arrival_time logic but internal
        try:
             # Just query the status string
             status = get_bus_arrival_time(route, real_start)
             # "【307】目前狀態：\n往 撫遠街：台北車站(忠孝) - 5分鐘"
             # Filter lines relevant
             lines = status.split('\n')
             relevant_lines = [l for l in lines if "目前狀態" not in l and real_start in l]
             if relevant_lines:
                 response += f"\n\n--- 即時動態 ---\n" + "\n".join(relevant_lines)
        except Exception as e:
            response += f"\n(即時動態查詢失敗: {e})"
            
        return response
        
    if plan["type"] == "transfer":
        s1 = plan["segments"][0]
        s2 = plan["segments"][1]
        mid = plan["transfer_stop"]
        response = f"建議路線 (需轉乘 1 次)：\n1. 搭乘【{s1['route']}】從 {s1['from']} -> {mid}\n2. 在 {mid} 轉乘【{s2['route']}】-> {s2['to']}"
        
        # Add real-time status for the first leg
        try:
             status = get_bus_arrival_time(s1['route'], real_start)
             lines = status.split('\n')
             relevant_lines = [l for l in lines if "目前狀態" not in l and real_start in l]
             if relevant_lines:
                 response += f"\n\n--- 第一段即時動態 ---\n" + "\n".join(relevant_lines)
        except:
            pass
            
        return response
        
    if plan["type"] == "2-transfer":
        s1 = plan["segments"][0]
        s2 = plan["segments"][1]
        s3 = plan["segments"][2]
        t1 = plan["transfer_stops"][0]
        t2 = plan["transfer_stops"][1]
        
        response = f"建議路線 (需轉乘 2 次)：\n"
        response += f"1. 搭乘【{s1['route']}】從 {s1['from']} -> {t1}\n"
        response += f"2. 在 {t1} 轉乘【{s2['route']}】-> {t2}\n"
        response += f"3. 在 {t2} 轉乘【{s3['route']}】-> {s3['to']}"
        
        # Add real-time status for the first leg
        try:
             status = get_bus_arrival_time(s1['route'], real_start)
             lines = status.split('\n')
             relevant_lines = [l for l in lines if "目前狀態" not in l and real_start in l]
             if relevant_lines:
                 response += f"\n\n--- 第一段即時動態 ---\n" + "\n".join(relevant_lines)
        except:
            pass
            
        return response

    return "規劃失敗。"

if __name__ == "__main__":
    mcp.run()
