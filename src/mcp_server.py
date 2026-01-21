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

def find_canonical_route_name(route_name: str) -> Optional[str]:
    """
    Fuzzy search for route Name.
    Returns the canonical route name (e.g. "307" or "復興幹線") key from the map.
    """
    if route_name in routes_map:
        return route_name
    
    # Fuzzy match
    matches = difflib.get_close_matches(route_name, routes_map.keys(), n=1, cutoff=0.6)
    if matches:
        return matches[0]
    
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
    # 1. Find Canonical Route Name
    real_route_name = find_canonical_route_name(route_name)
    if not real_route_name:
        # Fallback: if map is empty (might happen if not initialized), try using the input name
        # TDX usually handles "307" fine. 
        if not routes_map:
            real_route_name = route_name
        else:
             return f"找不到路線：{route_name}"

    # 2. Fetch Data (Cached)
    # We pass real_route_name to BusCrawler.get_route_data
    data = CacheManager.get_or_fetch(real_route_name, BusCrawler.get_route_data)
    if not data:
        return f"無法取得 {real_route_name} 的即時資料，請稍後再試。"

    # 3. Parse and Find Stop(s)
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
                         if eta_val == 65535 or eta_val == 65529:
                             status_text = "尚未發車"
                         elif eta_val == -2:
                             status_text = "已過站"
                         elif eta_val == -3:
                             status_text = "末班車已過" # Or Pit
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

from datetime import datetime, timedelta

def check_transfer_safety(route_name: str, estimated_arrival: datetime) -> tuple[bool, str, float]:
    """
    Check if a transfer is safe based on Frequency or Schedule.
    Returns: (is_safe, reason, added_wait_cost_minutes)
    """
    client = BusCrawler.get_client()
    if not client:
        return True, "無法驗證 (API Error)", 0 # Fail open or closed? Open for now.

    # 1. Check Frequency (High Freq)
    try:
        freqs = client.get_route_frequency(route_name)
        if freqs:
            # Assuming first element represents general stat. 
            # Real logic should match day type/time, but simplistic first.
            f = freqs[0] 
            # Check ServiceDay? TDX returns current applicable usually?
            # MinHeadwayMins
            min_h = f.get("MinHeadwayMins", 999)
            if min_h <= 20: # 20 mins or less is considered frequent enough
                return True, f"班次密集 (約 {min_h}分一班)", min_h / 2
    except Exception as e:
        logger.warning(f"Freq check fail: {e}")

    # 2. Check Schedule (Fixed Time)
    try:
        scheds = client.get_schedule(route_name)
        if not scheds:
             return False, "無班表資料", 30 # Penalty
             
        # Filter for trips after estimated_arrival
        valid_trips = []
        arrival_str = estimated_arrival.strftime("%H:%M")
        
        for ch in scheds:
            # Direction? We don't know direction easily without complex graphing.
            # We assume if ANY direction has trips, it's usable (Optimistic).
            # "Frequence" stops usually have trips both ways.
            
            # Times are in 'Frequencies' list? No, get_schedule returns "StopOfRoute"? 
            # No, /Schedule/City returns "BusSchedule" structure with "Frequencys" or "Timetables"?
            # Actually TDX /Schedule returns list of Route Schedules, containing "Timetables" or "Frequencies".
            # My `get_schedule` calls `/Schedule`.
            # Structure: [ { RouteName:..., Timetables: [ { TripID, StopTimes: [...] } ] } ]
            # Wait, /Bus/Schedule/ is complex.
            # Simplified: Just count TOTAL trips remaining in day? No.
            
            # Let's rely on Frequency if available. If not, assume it's low freq.
            # If get_schedule return implies Timetable...
            timetables = ch.get("Timetables", [])
            for t in timetables:
                # trip time? usually first stop time? 
                stops = t.get("StopTimes", [])
                if stops:
                    # just take first stop dep time as approx trip time
                    dep_time = stops[0].get("DepartureTime", "00:00")
                    if dep_time > arrival_str:
                         valid_trips.append(dep_time)
        
        valid_trips.sort()
        count = len(valid_trips)
        
        if count >= 2:
            # Calculat wait time for next bus
            # simple diff
            next_bus = valid_trips[0]
            # parse
            nb_h, nb_m = map(int, next_bus.split(':'))
            ea_h, ea_m = estimated_arrival.hour, estimated_arrival.minute
            wait = (nb_h * 60 + nb_m) - (ea_h * 60 + ea_m)
            if wait < 0: wait = 0
            
            return True, f"表定尚有 {count} 班車 (下班 {next_bus})", wait
        elif count == 1:
            return True, "僅剩 1 班車 (注意轉乘風險)", 60 # Penalty for risk
            
        return False, "已無合適班次 (末班已過或極少)", 999
        
    except Exception as e:
        logger.warning(f"Schedule check fail: {e}")
        
    return False, "資料無法判讀", 30

@mcp.tool()
def plan_trip(start: str, end: str) -> str:
    """
    規劃公車路線 (A站 到 B站)，依據「最快時間」與「安全轉乘」推薦。
    
    Args:
       start: 起點站牌名稱
       end: 終點站牌名稱
    """
    
def calculate_best_route(start: str, end: str) -> Dict[str, Any]:
    """
    Core logic to find best route with real-time data.
    Returns the best candidate object or None.
    """
    candidates = graph_engine.find_candidate_paths(start, end, top_k=5)
    
    if not candidates:
        return {"error": "No candidates"}

    ranked_results = []
    current_time = datetime.now()
    
    for cand in candidates:
        # Get First Leg info
        seg1 = cand["segments"][0]
        route_name = seg1["route"]
        stop_from = seg1["from"]
        stop_to_1 = seg1["to"]
        
        # 1. Fetch Real-time ETA for First Leg
        real_route_name = find_canonical_route_name(route_name)
        if not real_route_name:
            continue
            
        data = CacheManager.get_or_fetch(real_route_name, BusCrawler.get_route_data)
        
        wait_time = 999 
        wait_text = "無資料"
        
        if data:
            valid_etas = []
            dirs = [("Go", data.get("GoDirStops", [])), ("Back", data.get("BackDirStops", []))]
            for d_name, stops in dirs:
                for s in stops:
                    if stop_from in s.get("Name", ""):
                        e = s.get("ETA")
                        if e is not None and int(e) >= 0:
                            valid_etas.append(int(e))
                            
            if valid_etas:
                wait_time_sec = min(valid_etas)
                wait_time = wait_time_sec / 60.0
                wait_text = f"{int(wait_time)} 分鐘"
            else:
                wait_text = "目前無車"
                wait_time = 60 # Penalty
        
        # Total Score
        # For Direct: Static(Full) + Wait
        # For Greedy Transfer: Static(Leg1) + Wait
        total_time = cand["static_time"] + wait_time
        
        cand["total_time"] = total_time
        cand["wait_text"] = wait_text
        ranked_results.append(cand)

    # Sort by Total Time
    ranked_results.sort(key=lambda x: x["total_time"])
    
    if not ranked_results:
        return {"error": "No reachable route with data"}
        
    return ranked_results[0]

@mcp.tool()
def plan_trip(start: str, end: str) -> str:
    """
    規劃公車路線 (A站 到 B站)，依據「最快時間」推薦。
    若需轉乘，會採用「分段導航」模式，優先引導您搭上最快到達中繼站的車。
    
    Args:
       start: 起點站牌名稱
       end: 終點站牌名稱
    """
    best = calculate_best_route(start, end)
    
    if "error" in best:
        return f"找不到從「{start}」到「{end}」的建議路線。({best['error']})"
            
    response = f"🚀 最快路線建議 (預估總時程: {int(best['total_time'])} 分鐘)\n"
    
    if best["type"] == "direct":
        seg = best["segments"][0]
        response += f"\n👉 請搭乘【{seg['route']}】(直達)\n"
        response += f"   從 [{seg['from']}] 上車 (等候: {best['wait_text']})\n"
        response += f"   抵達 [{seg['to']}] \n"
        
    elif best["type"] == "transfer_greedy":
        s1 = best["segments"][0]
        mid = best["transfer_stop"]
        response += f"\n👉 需轉乘 (分段導航)\n"
        response += f"1. 先搭乘【{s1['route']}】從 [{s1['from']}] 上車 (等候: {best['wait_text']})\n"
        response += f"   坐到 [{mid}] 下車 (行車約 {int(best['static_time'])} 分鐘)\n"
        response += f"\n⚠️ **重要**：這是最快能帶您離開起點並接近終點的路線。\n"
        response += f"   抵達 [{mid}] 後，請再次詢問我『{mid} 到 {end} 怎麼轉車』以獲取最新動態。\n"
        
    return response
    
    # Format Response
    response = f"🚀 最快路線建議 (預估總時程: {int(best['total_time'])} 分鐘)\n"
    
    if best["type"] == "direct":
        seg = best["segments"][0]
        response += f"\n👉 請搭乘【{seg['route']}】(直達)\n"
        response += f"   從 [{seg['from']}] 上車 (等候: {best['wait_text']})\n"
        response += f"   抵達 [{seg['to']}] \n"
        
    elif best["type"] == "transfer":
        s1 = best["segments"][0]
        s2 = best["segments"][1]
        mid = best["transfer_stop"]
        response += f"\n👉 需轉乘 1 次\n"
        response += f"1. 搭乘【{s1['route']}】從 [{s1['from']}] 上車 (等候: {best['wait_text']})\n"
        response += f"   坐到 [{mid}] 下車\n"
        response += f"2. 轉乘【{s2['route']}】{best['safety_note']}\n"
        response += f"   抵達 [{s2['to']}]\n"
        response += f"\n⚠️ **重要**：抵達 [{mid}] 後，請再次詢問我以取得最新接博動態。\n"
        
    if len(ranked_results) > 1:
        second = ranked_results[1]
        diff = second["total_time"] - best["total_time"]
        if diff < 10:
            note = ""
            if second["type"] == "transfer":
                note = second.get("safety_note", "")
            response += f"\n💡 替代方案: 搭 {second['segments'][0]['route']} ({note}) 差不多快 (+{int(diff)}分)"
            
    return response

if __name__ == "__main__":
    mcp.run()
