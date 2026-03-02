from mcp.server.fastmcp import FastMCP
import json
import os
import difflib
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# Ensure project root is in sys.path for module resolution
# Preferred: run with `python -m src.mcp_server` from project root
# This fallback handles direct `python src/mcp_server.py` invocations
import sys
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.crawler_core import BusCrawler
from src.cache_manager import CacheManager
from src.graph_engine import GraphEngine

# Setup logging
logger = logging.getLogger(__name__)

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
    logger.warning(f"Routes map not found at {ROUTES_MAP_FILE}")

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
                     # TDX StopStatus 已在 crawler_core 轉換：
                     # 65535 / 65529 = 尚未發車 (正數)
                     # -2 = 已過站
                     # -3 = 末班車已過
                     # >= 0 正常值 (秒數)
                     if eta_val == 65535 or eta_val == 65529:
                         status_text = "尚未發車"
                     elif eta_val == -2:
                         status_text = "已過站"
                     elif eta_val == -3:
                         status_text = "末班車已過"
                     elif eta_val < 0:
                         status_text = "末班車已過"
                     elif eta_val <= 180:
                         status_text = "即將進站"
                     else:
                         mins = (eta_val + 59) // 60
                         status_text = f"還有 {mins} 分鐘"
                else:
                    status_text = "無資料"
                
                found_stops.append(f"往 {dir_name}：{s_name} - {status_text}")

    if not found_stops:
        return f"路線 {route_name} ({real_route_name}) 上找不到站牌「{stop_name}」。"

    return f"【{real_route_name}】目前狀態：\n" + "\n".join(found_stops)


def check_transfer_safety(route_name: str, estimated_arrival: datetime) -> tuple:
    """
    Check if a transfer is safe based on Frequency or Schedule.
    Returns: (is_safe: bool, reason: str, added_wait_cost_minutes: float)
    """
    client = BusCrawler.get_client()
    if not client:
        return True, "無法驗證 (API Error)", 0

    # 1. Check Frequency (High Freq)
    try:
        freqs = client.get_route_frequency(route_name)
        if freqs:
            f = freqs[0] 
            min_h = f.get("MinHeadwayMins", 999)
            if min_h <= 20:
                return True, f"班次密集 (約 {min_h}分一班)", min_h / 2
    except Exception as e:
        logger.warning(f"Freq check fail: {e}")

    # 2. Check Schedule (Fixed Time)
    try:
        scheds = client.get_schedule(route_name)
        if not scheds:
             return False, "無班表資料", 30

        valid_trips = []
        arrival_str = estimated_arrival.strftime("%H:%M")
        
        for ch in scheds:
            timetables = ch.get("Timetables", [])
            for t in timetables:
                stops = t.get("StopTimes", [])
                if stops:
                    dep_time = stops[0].get("DepartureTime", "00:00")
                    if dep_time > arrival_str:
                         valid_trips.append(dep_time)
        
        valid_trips.sort()
        count = len(valid_trips)
        
        if count >= 2:
            next_bus = valid_trips[0]
            nb_h, nb_m = map(int, next_bus.split(':'))
            ea_h, ea_m = estimated_arrival.hour, estimated_arrival.minute
            wait = (nb_h * 60 + nb_m) - (ea_h * 60 + ea_m)
            if wait < 0: wait = 0
            
            return True, f"表定尚有 {count} 班車 (下班 {next_bus})", wait
        elif count == 1:
            return True, "僅剩 1 班車 (注意轉乘風險)", 60
            
        return False, "已無合適班次 (末班已過或極少)", 999
        
    except Exception as e:
        logger.warning(f"Schedule check fail: {e}")
        
    return False, "資料無法判讀", 30


def calculate_best_route(start: str, end: str) -> Dict[str, Any]:
    """
    Core logic to find best route with real-time data.
    Route keys from graph_engine are direction-aware (e.g. '307__go').
    We strip the suffix when calling TDX API.
    """
    from src.graph_engine import get_base_route_name, DIR_GO, DIR_BACK
    
    candidates = graph_engine.find_candidate_paths(start, end, top_k=5)
    
    if not candidates:
        return {"error": "No candidates"}

    ranked_results = []
    current_time = datetime.now()
    
    for cand in candidates:
        seg1 = cand["segments"][0]
        route_key = seg1["route"]           # e.g. "307__go"
        base_route = get_base_route_name(route_key)  # e.g. "307"
        stop_from = seg1["from"]
        stop_from_uid = seg1.get("from_uid")  # P1: StopUID for precise matching
        
        # 1. Fetch Real-time ETA for First Leg
        real_route_name = find_canonical_route_name(base_route)
        if not real_route_name:
            if not routes_map:
                real_route_name = base_route
            else:
                continue
            
        data = CacheManager.get_or_fetch(real_route_name, BusCrawler.get_route_data)
        
        wait_time = 999 
        wait_text = "無資料"
        
        if data:
            valid_etas = []
            
            # Match ETA based on direction from route key
            if route_key.endswith(DIR_GO):
                dir_stops = data.get("GoDirStops", [])
            elif route_key.endswith(DIR_BACK):
                dir_stops = data.get("BackDirStops", [])
            else:
                dir_stops = data.get("GoDirStops", []) + data.get("BackDirStops", [])
            
            for s in dir_stops:
                # P1: Prefer StopUID matching (exact), fallback to name matching
                matched = False
                if stop_from_uid and s.get("StopUID"):
                    matched = s["StopUID"] == stop_from_uid
                else:
                    matched = stop_from in s.get("Name", "")
                
                if matched:
                    e = s.get("ETA")
                    if e is not None and int(e) >= 0:
                        valid_etas.append(int(e))
                            
            if valid_etas:
                wait_time_sec = min(valid_etas)
                wait_time = wait_time_sec / 60.0
                wait_text = f"{int(wait_time)} 分鐘"
            else:
                wait_text = "目前無車"
                wait_time = 60

        # Total Score = wait + leg1 travel + estimated remaining (for fair comparison)
        remaining = cand.get("remaining_time", 0)
        total_time = cand["static_time"] + wait_time + remaining
        
        # Check transfer safety — use the TRANSFER route (leg 2), not leg 1
        safety_note = ""
        if cand["type"] == "transfer_greedy" and cand.get("transfer_route"):
            transfer_route_key = cand["transfer_route"]
            transfer_base = get_base_route_name(transfer_route_key)
            estimated_arrival_at_mid = current_time + timedelta(minutes=cand["static_time"] + wait_time)
            is_safe, reason, extra_wait = check_transfer_safety(transfer_base, estimated_arrival_at_mid)
            safety_note = f"({reason})"
            if not is_safe:
                total_time += extra_wait
        
        cand["total_time"] = total_time
        cand["wait_text"] = wait_text
        cand["safety_note"] = safety_note
        cand["display_route"] = base_route  # Clean name for UI
        ranked_results.append(cand)

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
    from src.graph_engine import get_base_route_name, get_direction_label
    
    best = calculate_best_route(start, end)
    
    if "error" in best:
        return f"找不到從「{start}」到「{end}」的建議路線。({best['error']})"
            
    response = f"🚀 最快路線建議 (預估總時程: {int(best['total_time'])} 分鐘)\n"
    
    if best["type"] == "direct":
        seg = best["segments"][0]
        route_display = get_base_route_name(seg['route'])
        direction = get_direction_label(seg['route'])
        dir_info = f" {direction}" if direction else ""
        response += f"\n👉 請搭乘【{route_display}】{dir_info} (直達)\n"
        response += f"   從 [{seg['from']}] 上車 (等候: {best['wait_text']})\n"
        response += f"   抵達 [{seg['to']}] \n"
        
    elif best["type"] == "transfer_greedy":
        s1 = best["segments"][0]
        route_display = get_base_route_name(s1['route'])
        direction = get_direction_label(s1['route'])
        dir_info = f" {direction}" if direction else ""
        mid = best["transfer_stop"]
        safety = best.get("safety_note", "")
        response += f"\n👉 需轉乘 (分段導航) {safety}\n"
        response += f"1. 先搭乘【{route_display}】{dir_info} 從 [{s1['from']}] 上車 (等候: {best['wait_text']})\n"
        response += f"   坐到 [{mid}] 下車 (行車約 {int(best['static_time'])} 分鐘)\n"
        response += f"\n⚠️ **重要**：這是最快能帶您離開起點並接近終點的路線。\n"
        response += f"   抵達 [{mid}] 後，請再次詢問我『{mid} 到 {end} 怎麼轉車』以獲取最新動態。\n"
        
    return response


if __name__ == "__main__":
    mcp.run()

