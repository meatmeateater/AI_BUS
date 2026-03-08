# ===========================================================================
#  graph_engine.py — 公車路網圖引擎
#
#  核心演算法模組，負責：
#    1. 載入離線路網圖 (bus_graph.json)
#    2. 站名模糊匹配 (台↔臺、捷運前綴、括號子站展開)
#    3. 路徑搜尋 (直達 → 一次轉乘 → 橋接路線)
#
#  演算法: Greedy Hop & Recursive Bridging
#    - 不是 Dijkstra / BFS，而是基於路線交集的貪心搜尋
#    - 方向感知：每條路線分 __go / __back 兩條有向邊
#    - 支援 StopUID 精確匹配 + GPS 消歧義
#
#  效能:
#    - 圖載入 ~256ms（5,159 站、1,266 路線）
#    - 路徑搜尋 ~5-9ms（含站名展開）
#    - 預建索引 _stop_index 讓站距查詢 O(1)
# ===========================================================================

import json
import os
import math
import logging
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict

from config.settings import (
    DIR_GO, DIR_BACK, TIME_PER_STOP,
    INVALID_DISTANCE, MAX_VALID_DISTANCE, DIRECT_SKIP_THRESHOLD
)

logger = logging.getLogger(__name__)


# ====================================================================
#  工具函數 (模組層級)
# ====================================================================

def get_base_route_name(route_key: str) -> str:
    """
    去除方向後綴，還原路線名稱。
    '307__go' → '307', '復興幹線__back' → '復興幹線'
    """
    if route_key.endswith(DIR_GO):
        return route_key[:-len(DIR_GO)]
    if route_key.endswith(DIR_BACK):
        return route_key[:-len(DIR_BACK)]
    return route_key


def get_direction_label(route_key: str) -> str:
    """
    取得方向的中文標籤。
    '307__go' → '去程', '307__back' → '返程', '307' → ''
    """
    if route_key.endswith(DIR_GO):
        return "去程"
    if route_key.endswith(DIR_BACK):
        return "返程"
    return ""


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    計算兩個 GPS 座標之間的距離（公尺）。
    使用 Haversine 公式，假設地球為正球體 (R=6371km)。
    """
    R = 6371000  # 地球半徑 (公尺)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# ====================================================================
#  GraphEngine 主類別
# ====================================================================

class GraphEngine:
    """
    公車路網圖引擎。

    資料結構:
        stops:  { "站名": {"routes": ["307__go", ...], "lat": 25.0, "lon": 121.5} }
        routes: { "307__go": ["站A", "站B", "站C", ...] }  (有序站序)
        stop_uid_map: { "307__go": {"站A": "TPE12345", ...} }
        _stop_index:  { "307__go": {"站A": [0], "站B": [1, 15], ...} }
    """

    def __init__(self, graph_file: str):
        self.graph_file = graph_file
        self.stops: Dict[str, Dict] = {}                      # 站點資料
        self.routes: Dict[str, List[str]] = {}                 # 路線站序
        self.stop_uid_map: Dict[str, Dict[str, str]] = {}      # 路線→站名→UID
        self.is_loaded = False

        # 預建的站點索引：route_key → { stop_name → [出現位置 indices] }
        # 讓 get_route_stop_distance 可以 O(K²) 查詢（K = 同名站數，通常 1-2）
        self._stop_index: Dict[str, Dict[str, List[int]]] = {}

    def load_graph(self):
        """
        從 JSON 檔載入路網圖。
        檔案格式為 build_network_graph.py 產生的 v3 格式。
        """
        if not os.path.exists(self.graph_file):
            logger.warning(f"Graph file not found: {self.graph_file}")
            return

        with open(self.graph_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.stops = data.get("stops", {})
            self.routes = data.get("routes", {})
            self.stop_uid_map = data.get("stop_uid_map", {})
            self.is_loaded = True

            # 版本檢查
            version = data.get("version", 1)
            if version < 2:
                logger.warning("Graph file is v1. Run build_network_graph.py to rebuild.")

            # 建立預計算索引
            self._build_stop_index()

    def _build_stop_index(self):
        """
        預建站點位置索引。

        結構: { route_key: { stop_name: [index1, index2, ...] } }

        為什麼需要:
            原本每次 get_route_stop_distance 都要 O(N) 掃描站序，
            建完索引後變 O(1) 查表 + O(K²) 配對 (K = 同名站出現次數)。
        """
        self._stop_index = {}
        for route_key, stops in self.routes.items():
            index: Dict[str, List[int]] = defaultdict(list)
            for i, stop_name in enumerate(stops):
                index[stop_name].append(i)
            self._stop_index[route_key] = dict(index)

        logger.debug(f"Built stop index for {len(self._stop_index)} routes")

    # ====================================================================
    #  站名匹配
    # ====================================================================

    def find_best_stop_match(
        self,
        query: str,
        ref_lat: Optional[float] = None,
        ref_lon: Optional[float] = None
    ) -> Optional[str]:
        """
        模糊匹配使用者輸入的站名，找到圖中最佳對應站點。

        匹配策略 (由精確到模糊):
            1. 完全比對
            2. 正規化後完全比對 (台↔臺、加捷運前綴等)
            3. 子字串匹配 (正規化後的所有變體)
            4. GPS 消歧義 (當有多個候選且提供了座標時)

        排序權重:
            - 前綴匹配 > 子字串匹配
            - 路線數多 > 路線數少 (大站優先)
            - 站名短 > 站名長 (越具體越好)
        """
        if not self.is_loaded:
            self.load_graph()

        # 第一層：完全比對
        if query in self.stops:
            return query

        # 產生正規化變體
        normalized_queries = self._normalize_stop_name(query)

        # 第二層：正規化後完全比對
        for nq in normalized_queries:
            if nq in self.stops:
                return nq

        # 第三層：子字串匹配
        candidates = set()
        for nq in normalized_queries:
            for s in self.stops:
                if nq in s:
                    candidates.add(s)

        if not candidates:
            return None

        candidate_list = list(candidates)

        # 評分函數：分數越低越好
        def match_score(stop_name: str) -> tuple:
            """
            排序優先級:
                tier 0: query 是站名的前綴 (最佳)
                tier 1: 任何正規化變體是站名的前綴
                tier 2: 僅子字串匹配 (最弱)
            接著按路線數 (降序) 和站名長度 (升序) 排列
            """
            tier = 2
            for nq in normalized_queries:
                if stop_name.startswith(nq):
                    tier = 0 if nq == query else 1
                    break

            route_count = len(self.stops.get(stop_name, {}).get("routes", []))
            return (tier, -route_count, len(stop_name))

        # 有 GPS 座標時，改用距離排序
        if ref_lat is not None and ref_lon is not None:
            def distance_to_ref(stop_name: str) -> float:
                lat = self.stops[stop_name].get("lat")
                lon = self.stops[stop_name].get("lon")
                if lat and lon:
                    return haversine_distance(ref_lat, ref_lon, lat, lon)
                return float('inf')

            candidate_list.sort(key=distance_to_ref)
            return candidate_list[0]

        # 預設：使用評分排序
        candidate_list.sort(key=match_score)
        return candidate_list[0]

    @staticmethod
    def _normalize_stop_name(query: str) -> List[str]:
        """
        產生站名的正規化變體。

        處理:
            - 台 ↔ 臺 互轉 (如「台北車站」↔「臺北車站」)
            - 加「捷運」前綴 (如「西門」→「捷運西門站」)
            - 加「站」後綴 (如「西門」→「西門站」)

        回傳: 去重後的變體列表，原始 query 排第一
        """
        variants = [query]

        # 台 ↔ 臺 互轉
        if "台" in query:
            variants.append(query.replace("台", "臺"))
        if "臺" in query:
            variants.append(query.replace("臺", "台"))

        # 捷運前綴 + 站後綴
        extra = []
        for v in variants:
            if not v.startswith("捷運"):
                extra.append("捷運" + v)
                if not v.endswith("站"):
                    extra.append("捷運" + v + "站")
            if not v.endswith("站"):
                extra.append(v + "站")

        variants.extend(extra)

        # 去重但保持順序 (原始 query 優先)
        seen = set()
        result = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                result.append(v)

        return result

    # ====================================================================
    #  站距查詢
    # ====================================================================

    def get_stop_uid(self, route_key: str, stop_name: str) -> Optional[str]:
        """查詢特定路線上某站的 StopUID。"""
        return self.stop_uid_map.get(route_key, {}).get(stop_name)

    def get_stop_gps(self, stop_name: str) -> Optional[Tuple[float, float]]:
        """查詢站點的 GPS 座標 (lat, lon)。"""
        stop = self.stops.get(stop_name, {})
        lat = stop.get("lat")
        lon = stop.get("lon")
        if lat is not None and lon is not None:
            return (lat, lon)
        return None

    def get_route_stop_distance(self, route_name: str, start: str, end: str) -> int:
        """
        計算同一路線上兩站之間的有向站距。

        使用預建索引 O(K²)，K = 同名站出現次數（通常 1-2 次）。
        只計算正向距離 (end_index > start_index)。

        Returns:
            站距 (int)，不可達時回傳 INVALID_DISTANCE
        """
        if not self.is_loaded:
            self.load_graph()
        if route_name not in self._stop_index:
            return INVALID_DISTANCE

        idx = self._stop_index[route_name]
        start_indices = idx.get(start)
        end_indices = idx.get(end)

        if not start_indices or not end_indices:
            return INVALID_DISTANCE

        min_dist = INVALID_DISTANCE
        for s_idx in start_indices:
            for e_idx in end_indices:
                dist = e_idx - s_idx
                if 0 < dist < min_dist:
                    min_dist = dist

        return min_dist

    def get_route_stops(self, route_name: str, start: str, end: str) -> List[str]:
        """
        取得同一路線上兩站之間的所有站名 (含頭尾)。
        只取正向最短路徑。
        """
        if not self.is_loaded:
            self.load_graph()
        if route_name not in self.routes:
            return []

        stops = self.routes[route_name]
        idx = self._stop_index.get(route_name, {})
        start_indices = idx.get(start)
        end_indices = idx.get(end)

        if not start_indices or not end_indices:
            return []

        min_dist = INVALID_DISTANCE
        best_s = -1
        best_e = -1

        for s_idx in start_indices:
            for e_idx in end_indices:
                dist = e_idx - s_idx
                if 0 < dist < min_dist:
                    min_dist = dist
                    best_s = s_idx
                    best_e = e_idx

        if best_s == -1:
            return []

        return stops[best_s : best_e + 1]

    # ====================================================================
    #  站名展開 (Stop Group Expansion)
    # ====================================================================

    def _expand_stop_group(self, stop_name: str) -> List[str]:
        """
        展開括號子站群組。

        範例:
            '臺北車站(忠孝)' → ['臺北車站(忠孝)', '臺北車站(承德)', '臺北車站(鄭州)', ...]
            '西門' → ['西門'] (無括號子站)

        用途: 同一大站的不同出口/方向有不同站牌名，展開後可涵蓋所有可能路線。
        """
        if "(" not in stop_name:
            # 嘗試找括號子站
            siblings = [s for s in self.stops if s.startswith(stop_name + "(")]
            if siblings:
                return [stop_name] + siblings
            return [stop_name]

        # 有括號 → 提取基底名稱再展開
        base = stop_name.split("(")[0]
        siblings = [s for s in self.stops if s.startswith(base + "(") or s == base]
        return siblings if siblings else [stop_name]

    def _expand_stop_group_full(self, original_query: str, matched_stop: str) -> List[str]:
        """
        完整站名展開：括號子站 + 正規化變體匹配。

        範例:
            query='西門', matched='西門'
            → 括號展開: ['西門']
            → 正規化: '捷運西門站' 也在圖中
            → 最終: ['西門', '捷運西門站']

            query='台北車站', matched='臺北車站(忠孝)'
            → 括號展開: ['臺北車站(忠孝)', '臺北車站(承德)', ...]
            → 最終: 所有 臺北車站(*) 變體
        """
        # 從括號展開開始
        group = set(self._expand_stop_group(matched_stop))

        # 用正規化變體做額外匹配
        variants = self._normalize_stop_name(original_query)
        for v in variants:
            if v in self.stops:
                group.add(v)
                for sib in self._expand_stop_group(v):
                    group.add(sib)
            # 前綴匹配：只加短後綴 (如 "(忠孝)"，5 字以內)
            for s in self.stops:
                if s.startswith(v) and len(s) - len(v) <= 5:
                    group.add(s)

        return list(group)

    def _get_merged_routes(self, stop_group: List[str]) -> set:
        """取得一組站點的所有路線聯集。"""
        routes = set()
        for s in stop_group:
            routes.update(self.stops.get(s, {}).get("routes", []))
        return routes

    # ====================================================================
    #  路徑搜尋 (核心演算法)
    # ====================================================================

    def find_candidate_paths(self, start: str, end: str, top_k: int = 5) -> List[Dict]:
        """
        搜尋從 start 到 end 的候選路徑。

        演算法 (Greedy Hop & Recursive Bridging):
            Priority 1: 直達 — 起終點在同一路線上
            Priority 2: 一次轉乘 — 找共同中繼站，貪心選最短 leg1
            Priority 3: 橋接路線 — 找同時觸碰起點側和終點側的橋接路線

        直達 / 轉乘混合排名:
            當直達方案的站數 > DIRECT_SKIP_THRESHOLD 時，也搜轉乘。
            因為長途直達（如 40 站）可能不如短途轉乘（5+3 站）快。

        Args:
            start: 起點站名 (使用者輸入的原始字串)
            end: 終點站名
            top_k: 回傳前 K 個候選

        Returns:
            排序後的候選路徑列表 (按 static_time 排序)
        """
        if not self.is_loaded:
            self.load_graph()

        # 站名模糊匹配
        real_start = self.find_best_stop_match(start)
        real_end = self.find_best_stop_match(end)

        if not real_start or not real_end:
            return []

        # 展開到所有相關子站
        start_group = self._expand_stop_group_full(start, real_start)
        end_group = self._expand_stop_group_full(end, real_end)

        candidates = []

        # 合併所有子站的路線
        start_routes = self._get_merged_routes(start_group)
        end_routes = self._get_merged_routes(end_group)

        # ── Priority 1: 直達 ──
        # 找起終點路線的交集
        common_routes = start_routes.intersection(end_routes)

        for r in common_routes:
            # 嘗試所有 start_sub × end_sub 組合，找最短站距
            best_dist = INVALID_DISTANCE
            best_from = None
            best_to = None
            for s in start_group:
                for e in end_group:
                    dist = self.get_route_stop_distance(r, s, e)
                    if 0 < dist < best_dist:
                        best_dist = dist
                        best_from = s
                        best_to = e

            if best_dist < MAX_VALID_DISTANCE and best_from and best_to:
                est_time = best_dist * TIME_PER_STOP
                start_uid = self.get_stop_uid(r, best_from)
                candidates.append({
                    "type": "direct",
                    "segments": [{"route": r, "from": best_from, "to": best_to,
                                  "from_uid": start_uid}],
                    "static_time": est_time,
                    "stop_count": best_dist
                })

        # 所有直達方案都很短 → 不用搜轉乘
        # 否則也搜轉乘，因為轉乘可能比繞遠路的直達更快
        if candidates and all(c["stop_count"] <= DIRECT_SKIP_THRESHOLD for c in candidates):
            candidates.sort(key=lambda x: x["static_time"])
            return candidates[:top_k]

        # ── Priority 2: 一次轉乘 (Greedy Leg 1) ──
        # 找到起點路線可達的所有站 ∩ 終點路線可達的所有站 = 潛在中繼站
        stops_from_start = set()
        for r in start_routes:
            for s in self.routes.get(r, []):
                stops_from_start.add(s)

        stops_from_end = set()
        for r in end_routes:
            for s in self.routes.get(r, []):
                stops_from_end.add(s)

        common_transfer_stops = stops_from_start.intersection(stops_from_end)

        for mid in common_transfer_stops:
            # 跳過起終點本身
            if mid in start_group or mid in end_group:
                continue

            # 找最佳 Leg1 (Start → Mid)
            r1_candidates = [r for r in start_routes if mid in self._stop_index.get(r, {})]

            best_r1 = None
            best_from = None
            min_d1 = INVALID_DISTANCE

            for r in r1_candidates:
                for sg in start_group:
                    d = self.get_route_stop_distance(r, sg, mid)
                    if d < min_d1:
                        min_d1 = d
                        best_r1 = r
                        best_from = sg

            if min_d1 >= MAX_VALID_DISTANCE or not best_r1:
                continue

            # 找最佳 Leg2 (Mid → End)
            r2_candidates = [r for r in end_routes if mid in self._stop_index.get(r, {})]

            best_r2 = None
            min_d2 = INVALID_DISTANCE

            for r in r2_candidates:
                for eg in end_group:
                    d = self.get_route_stop_distance(r, mid, eg)
                    if d < min_d2:
                        min_d2 = d
                        best_r2 = r

            if not best_r2:
                continue

            est_time_leg1 = min_d1 * TIME_PER_STOP
            est_time_leg2 = min_d2 * TIME_PER_STOP if min_d2 < MAX_VALID_DISTANCE else 0

            start_uid = self.get_stop_uid(best_r1, best_from)
            candidates.append({
                "type": "transfer_greedy",
                "transfer_stop": mid,
                "segments": [
                    {"route": best_r1, "from": best_from, "to": mid,
                     "from_uid": start_uid}
                ],
                "transfer_route": best_r2,
                "static_time": est_time_leg1,
                "remaining_time": est_time_leg2,
                "stop_count": min_d1
            })

        # ── Priority 3: 橋接路線 (Bridge Route) ──
        # 找同時在 start 側和 end 側都有交叉的第三條路線
        if len(candidates) < top_k * 2:
            routes_touching_s1 = set()
            for s in stops_from_start:
                for r in self.stops.get(s, {}).get("routes", []):
                    routes_touching_s1.add(r)

            routes_touching_s2 = set()
            for s in stops_from_end:
                for r in self.stops.get(s, {}).get("routes", []):
                    routes_touching_s2.add(r)

            # 橋接路線 = 同時觸碰兩側，但不是起終點直接的路線
            bridge_routes = routes_touching_s1.intersection(routes_touching_s2)
            bridge_routes = bridge_routes - start_routes - end_routes

            for bridge in bridge_routes:
                # 找起點側的交叉站
                m1_candidates = stops_from_start.intersection(
                    set(self._stop_index.get(bridge, {}).keys())
                )
                if not m1_candidates:
                    continue

                best_m1 = None
                best_r1 = None
                best_from_bridge = None
                min_time_to_m1 = INVALID_DISTANCE * TIME_PER_STOP

                for m1 in m1_candidates:
                    valid_r1s = [r for r in start_routes if m1 in self._stop_index.get(r, {})]
                    for r in valid_r1s:
                        for sg in start_group:
                            d = self.get_route_stop_distance(r, sg, m1)
                            if d < MAX_VALID_DISTANCE:
                                t = d * TIME_PER_STOP
                                if t < min_time_to_m1:
                                    min_time_to_m1 = t
                                    best_m1 = m1
                                    best_r1 = r
                                    best_from_bridge = sg

                if best_m1 and best_r1 and best_from_bridge:
                    start_uid = self.get_stop_uid(best_r1, best_from_bridge)
                    candidates.append({
                        "type": "transfer_greedy",
                        "transfer_stop": best_m1,
                        "segments": [
                            {"route": best_r1, "from": best_from_bridge, "to": best_m1,
                             "from_uid": start_uid}
                        ],
                        "transfer_route": bridge,
                        "static_time": min_time_to_m1,
                        "remaining_time": 0,
                        "stop_count": int(min_time_to_m1 / TIME_PER_STOP),
                        "note": "Bridge Route"
                    })

        # 按靜態時間排序，回傳前 K 個
        candidates.sort(key=lambda x: x["static_time"])
        return candidates[:top_k]
