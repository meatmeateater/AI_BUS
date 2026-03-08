# ===========================================================================
#  mcp_server.py — MCP Tool Server 主入口
#
#  提供兩個 MCP Tool 給 AI 助理使用:
#    1. plan_trip(start, end)         — 規劃公車路線 (最多 3 個方案)
#    2. get_bus_arrival_time(route, stop, dir) — 查詢即時到站時間
#
#  架構:
#    使用者 → AI 助理 → MCP Server → GraphEngine (離線搜尋)
#                                   → BusCrawler (即時 API)
#                                   → CacheManager (快取層)
#
#  即時資料流程:
#    1. GraphEngine 找出候選路徑 (5ms)
#    2. 並行呼叫 TDX API 取得即時 ETA (~500ms)
#    3. 結合靜態站距 + 即時等候 → 算出 total_time
#    4. 排序後回傳 top-3 方案
# ===========================================================================

from mcp.server.fastmcp import FastMCP
import json
import os
import difflib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# 確保專案根目錄在 sys.path 中（讓 src.xxx 和 config.xxx 可以正確 import）
import sys
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.crawler_core import BusCrawler
from src.cache_manager import CacheManager
from src.graph_engine import (
    GraphEngine, get_base_route_name, get_direction_label
)
from config.settings import (
    DIR_GO, DIR_BACK, SAFE_TRANSFER_HEADWAY_MINS,
    DEFAULT_NO_BUS_WAIT, MAX_PARALLEL_WORKERS, TOP_K_RESULTS,
    INVALID_DISTANCE
)

logger = logging.getLogger(__name__)

# ====================================================================
#  初始化
# ====================================================================

# 檔案路徑
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTES_MAP_FILE = os.path.join(BASE_DIR, 'data', 'static', 'routes_map.json')
GRAPH_FILE = os.path.join(BASE_DIR, 'data', 'static', 'bus_graph.json')

# MCP 伺服器實例
mcp = FastMCP("Taipei Bus AI")

# 路線名稱對照表 (用於模糊匹配路線名)
routes_map = {}
if os.path.exists(ROUTES_MAP_FILE):
    with open(ROUTES_MAP_FILE, 'r', encoding='utf-8') as f:
        routes_map = json.load(f)
else:
    logger.warning(f"Routes map not found at {ROUTES_MAP_FILE}")

# 離線路網圖引擎 (lazy load)
graph_engine = GraphEngine(GRAPH_FILE)


# ====================================================================
#  輔助函數
# ====================================================================

def find_canonical_route_name(route_name: str) -> Optional[str]:
    """
    模糊查詢路線名稱，回傳 routes_map 中的標準名。

    策略:
        1. 完全比對
        2. difflib fuzzy match (cutoff=0.6)

    回傳 None 表示找不到。
    """
    if route_name in routes_map:
        return route_name

    matches = difflib.get_close_matches(route_name, routes_map.keys(), n=1, cutoff=0.6)
    if matches:
        return matches[0]

    return None


def _normalize_stop_for_eta(stop_name: str, dir_stops: list) -> list:
    """
    用 GraphEngine 的正規化邏輯匹配 ETA 站名。

    流程:
        1. 產生 stop_name 的所有正規化變體 (台↔臺, 捷運前綴等)
        2. 對 dir_stops 中的每個站名做子字串比對
        3. 回傳所有匹配的 stop dict

    這確保了 get_bus_arrival_time 和 plan_trip 使用同一套匹配邏輯。
    """
    variants = GraphEngine._normalize_stop_name(stop_name)

    matched = []
    for s in dir_stops:
        s_name = s.get("Name", "")
        for v in variants:
            if v in s_name:
                matched.append(s)
                break
    return matched


# ====================================================================
#  MCP Tool: 查詢到站時間
# ====================================================================

@mcp.tool()
def get_bus_arrival_time(route_name: str, stop_name: str, direction: str = "go") -> str:
    """
    查詢台北市公車到站時間。

    Args:
        route_name: 路線名稱 (如 "307", "299")
        stop_name: 站牌名稱 (如 "台北車站", "板橋")
        direction: 方向 ("go" 去程 / "back" 返程 / 其他 = 搜尋雙向)

    Returns:
        格式化的到站狀態文字
    """
    try:
        # ── 步驟 1: 查詢標準路線名 ──
        real_route_name = find_canonical_route_name(route_name)
        if not real_route_name:
            if not routes_map:
                real_route_name = route_name  # routes_map 為空時直通
            else:
                return f"找不到路線：{route_name}"

        # ── 步驟 2: 取得即時資料 (含快取) ──
        data = CacheManager.get_or_fetch(real_route_name, BusCrawler.get_route_data)
        if not data:
            return f"無法取得 {real_route_name} 的即時資料，請稍後再試。"

        # ── 步驟 3: 根據方向篩選站牌 ──
        found_stops = []

        directions_to_search = []
        if direction.lower() in ["go", "去程"]:
            directions_to_search.append(("去程", data.get("GoDirStops", [])))
        elif direction.lower() in ["back", "return", "返程"]:
            directions_to_search.append(("返程", data.get("BackDirStops", [])))
        else:
            # 未指定方向 → 搜尋雙向
            directions_to_search.append(("去程", data.get("GoDirStops", [])))
            directions_to_search.append(("返程", data.get("BackDirStops", [])))

        for dir_name, stops in directions_to_search:
            if not stops:
                continue

            # 用正規化邏輯匹配站名 (台↔臺, 捷運前綴等)
            matched_stops = _normalize_stop_for_eta(stop_name, stops)

            for stop in matched_stops:
                s_name = stop.get("Name", "")
                eta = stop.get("ETA")
                next_dep = stop.get("NextDepTime")

                # ── 解析 ETA 狀態 ──
                status_text = ""
                if next_dep:
                    status_text = f"預計 {next_dep} 發車"
                elif eta is not None:
                    eta_val = int(eta)
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
                        mins = (eta_val + 59) // 60  # 無條件進位
                        status_text = f"還有 {mins} 分鐘"
                else:
                    status_text = "無資料"

                found_stops.append(f"往 {dir_name}：{s_name} - {status_text}")

        if not found_stops:
            return f"路線 {route_name} ({real_route_name}) 上找不到站牌「{stop_name}」。"

        return f"【{real_route_name}】目前狀態：\n" + "\n".join(found_stops)

    except Exception as e:
        logger.error(f"get_bus_arrival_time error: {e}", exc_info=True)
        return f"查詢失敗：{e}"


# ====================================================================
#  轉乘安全性檢查
# ====================================================================

def check_transfer_safety(route_name: str, estimated_arrival: datetime) -> tuple:
    """
    檢查轉乘路線是否安全（有車可搭）。

    策略:
        1. 先查班距 (Frequency) → 班距 ≤ 20 分鐘視為安全
        2. 再查時刻表 (Schedule) → 找預計到達後的下一班車

    Returns:
        (is_safe: bool, reason: str, added_wait_minutes: float)
    """
    client = BusCrawler.get_client()
    if not client:
        return True, "無法驗證 (API Error)", 0

    # ── 檢查班距 (高頻路線直接通過) ──
    try:
        cache_key = f"__freq__{route_name}"
        freqs = CacheManager.get_cached_route_data(cache_key)
        if freqs is None:
            freqs = client.get_route_frequency(route_name)
            if freqs:
                CacheManager.set_route_data(cache_key, freqs)
        if freqs:
            f = freqs[0]
            min_h = f.get("MinHeadwayMins", INVALID_DISTANCE)
            if min_h <= SAFE_TRANSFER_HEADWAY_MINS:
                return True, f"班次密集 (約 {min_h}分一班)", min_h / 2
    except Exception as e:
        logger.warning(f"Freq check fail: {e}")

    # ── 檢查時刻表 (固定班次) ──
    try:
        sched_key = f"__sched__{route_name}"
        scheds = CacheManager.get_cached_route_data(sched_key)
        if scheds is None:
            scheds = client.get_schedule(route_name)
            if scheds:
                CacheManager.set_route_data(sched_key, scheds)
        if not scheds:
            return False, "無班表資料", 30

        # 找預計到達後的所有有效班次
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
            # 計算等候時間
            next_bus = valid_trips[0]
            nb_h, nb_m = map(int, next_bus.split(':'))
            ea_h, ea_m = estimated_arrival.hour, estimated_arrival.minute
            wait = (nb_h * 60 + nb_m) - (ea_h * 60 + ea_m)
            if wait < 0:
                wait = 0

            return True, f"表定尚有 {count} 班車 (下班 {next_bus})", wait
        elif count == 1:
            return True, "僅剩 1 班車 (注意轉乘風險)", 60

        return False, "已無合適班次 (末班已過或極少)", INVALID_DISTANCE

    except Exception as e:
        logger.warning(f"Schedule check fail: {e}")

    return False, "資料無法判讀", 30


# ====================================================================
#  核心路由計算
# ====================================================================

def calculate_best_route(start: str, end: str) -> Dict[str, Any]:
    """
    結合離線圖搜尋 + 即時 API 資料，計算最佳路線。

    流程:
        1. GraphEngine.find_candidate_paths → 取得候選路徑 (離線, ~5ms)
        2. 並行呼叫 TDX API 取得即時 ETA (ThreadPoolExecutor, ~500ms)
        3. 對每個候選計算 total_time = 等候 + 行車 + 剩餘估計
        4. 若有轉乘，額外檢查轉乘安全性
        5. 排序後回傳 top-N

    Returns:
        {"results": [...]} 或 {"error": "..."}
    """
    # ── 步驟 1: 離線圖搜尋 ──
    candidates = graph_engine.find_candidate_paths(start, end, top_k=5)

    if not candidates:
        return {"error": "No candidates"}

    ranked_results = []
    current_time = datetime.now()

    # ── 步驟 2: 收集需要抓取的路線，並行 API fetch ──
    routes_to_fetch = set()
    for cand in candidates:
        seg1 = cand["segments"][0]
        base_route = get_base_route_name(seg1["route"])
        real_name = find_canonical_route_name(base_route)
        if not real_name and not routes_map:
            real_name = base_route
        if real_name:
            routes_to_fetch.add(real_name)

    # 只抓未快取的路線
    uncached = [r for r in routes_to_fetch if not CacheManager.get_cached_route_data(r)]
    if uncached:
        def _fetch(route_id):
            return route_id, BusCrawler.get_route_data(route_id)

        with ThreadPoolExecutor(max_workers=min(len(uncached), MAX_PARALLEL_WORKERS)) as pool:
            futures = {pool.submit(_fetch, r): r for r in uncached}
            for future in as_completed(futures):
                try:
                    rid, data = future.result()
                    if data:
                        CacheManager.set_route_data(rid, data)
                except Exception as e:
                    logger.warning(f"Parallel fetch failed: {e}")

    # ── 步驟 3: 對每個候選計算即時分數 ──
    for cand in candidates:
        seg1 = cand["segments"][0]
        route_key = seg1["route"]
        base_route = get_base_route_name(route_key)
        stop_from = seg1["from"]
        stop_from_uid = seg1.get("from_uid")

        real_route_name = find_canonical_route_name(base_route)
        if not real_route_name:
            if not routes_map:
                real_route_name = base_route
            else:
                continue

        data = CacheManager.get_cached_route_data(real_route_name)

        wait_time = INVALID_DISTANCE  # 預設：無資料時的懲罰
        wait_text = "無資料"

        if data:
            valid_etas = []

            # 根據方向後綴選擇站牌清單
            if route_key.endswith(DIR_GO):
                dir_stops = data.get("GoDirStops", [])
            elif route_key.endswith(DIR_BACK):
                dir_stops = data.get("BackDirStops", [])
            else:
                dir_stops = data.get("GoDirStops", []) + data.get("BackDirStops", [])

            # 用 StopUID 精確匹配（優先），否則用站名子字串匹配
            for s in dir_stops:
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
                wait_time = DEFAULT_NO_BUS_WAIT

        # ── 計算總時間 ──
        remaining = cand.get("remaining_time", 0)
        total_time = cand["static_time"] + wait_time + remaining

        # ── 步驟 4: 轉乘安全性檢查 ──
        safety_note = ""
        if cand["type"] == "transfer_greedy" and cand.get("transfer_route"):
            transfer_route_key = cand["transfer_route"]
            transfer_base = get_base_route_name(transfer_route_key)
            estimated_arrival_at_mid = current_time + timedelta(
                minutes=cand["static_time"] + wait_time
            )
            is_safe, reason, extra_wait = check_transfer_safety(
                transfer_base, estimated_arrival_at_mid
            )
            safety_note = f"({reason})"
            if not is_safe:
                total_time += extra_wait

        cand["total_time"] = total_time
        cand["wait_text"] = wait_text
        cand["safety_note"] = safety_note
        cand["display_route"] = base_route
        ranked_results.append(cand)

    # ── 步驟 5: 排序，取 top-N ──
    ranked_results.sort(key=lambda x: x["total_time"])

    if not ranked_results:
        return {"error": "No reachable route with data"}

    return {"results": ranked_results[:TOP_K_RESULTS]}


# ====================================================================
#  MCP Tool: 路線規劃
# ====================================================================

@mcp.tool()
def plan_trip(start: str, end: str) -> str:
    """
    規劃公車路線 (A站 到 B站)，依據「最快到達時間」推薦。
    若需轉乘，會採用「分段導航」模式，優先引導搭上最快到中繼站的車。
    顯示最多 3 個方案供選擇。

    Args:
       start: 起點站牌名稱
       end: 終點站牌名稱
    """
    try:
        result = calculate_best_route(start, end)

        if "error" in result:
            return f"找不到從「{start}」到「{end}」的建議路線。({result['error']})"

        ranked = result["results"]
        parts = [f"🔍 找到 {len(ranked)} 個方案 (從「{start}」到「{end}」)\n"]

        for i, best in enumerate(ranked, 1):
            est = int(best['total_time'])
            parts.append(f"{'━' * 40}")
            parts.append(f"📌 方案 {i} — 預估 {est} 分鐘")

            if best["type"] == "direct":
                # ── 直達方案 ──
                seg = best["segments"][0]
                route_display = get_base_route_name(seg['route'])
                direction = get_direction_label(seg['route'])
                dir_info = f" {direction}" if direction else ""
                parts.append(f"  👉 搭乘【{route_display}】{dir_info} (直達)")
                parts.append(f"     從 [{seg['from']}] 上車 (等候: {best['wait_text']})")
                parts.append(f"     抵達 [{seg['to']}] ({best['stop_count']} 站)")

            elif best["type"] == "transfer_greedy":
                # ── 轉乘方案（分段導航）──
                s1 = best["segments"][0]
                route_display = get_base_route_name(s1['route'])
                direction = get_direction_label(s1['route'])
                dir_info = f" {direction}" if direction else ""
                mid = best["transfer_stop"]
                safety = best.get("safety_note", "")
                parts.append(f"  👉 需轉乘 {safety}")
                parts.append(f"  1. 搭【{route_display}】{dir_info} 從 [{s1['from']}] 上車 (等候: {best['wait_text']})")
                parts.append(f"     坐到 [{mid}] 下車 (行車約 {int(best['static_time'])} 分鐘)")
                parts.append(f"  2. 抵達 [{mid}] 後，請再問我『{mid} 到 {end}』以獲取最新動態")

            parts.append("")

        return "\n".join(parts)

    except Exception as e:
        logger.error(f"plan_trip error: {e}", exc_info=True)
        return f"規劃路線時發生錯誤：{e}"


# ====================================================================
#  啟動入口
# ====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )
    mcp.run()
