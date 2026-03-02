import json
import os
import math
import logging
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict

logger = logging.getLogger(__name__)

# Direction suffix constants
DIR_GO = "__go"
DIR_BACK = "__back"


def get_base_route_name(route_key: str) -> str:
    """Strip direction suffix: '307__go' -> '307'"""
    if route_key.endswith(DIR_GO):
        return route_key[:-len(DIR_GO)]
    if route_key.endswith(DIR_BACK):
        return route_key[:-len(DIR_BACK)]
    return route_key


def get_direction_label(route_key: str) -> str:
    """Get human-readable direction label."""
    if route_key.endswith(DIR_GO):
        return "去程"
    if route_key.endswith(DIR_BACK):
        return "返程"
    return ""


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two GPS coordinates in meters.
    Uses Haversine formula.
    """
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


class GraphEngine:
    def __init__(self, graph_file: str):
        self.graph_file = graph_file
        self.stops: Dict[str, Dict] = {}
        self.routes: Dict[str, List[str]] = {}
        self.stop_uid_map: Dict[str, Dict[str, str]] = {}  # P1: route -> stop_name -> UID
        self.is_loaded = False
        
        # P2: Pre-computed index { route_key: { stop_name: [indices] } }
        self._stop_index: Dict[str, Dict[str, List[int]]] = {}
        
    def load_graph(self):
        if not os.path.exists(self.graph_file):
            logger.warning(f"Graph file not found: {self.graph_file}")
            return
            
        with open(self.graph_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.stops = data.get("stops", {})
            self.routes = data.get("routes", {})
            self.stop_uid_map = data.get("stop_uid_map", {})
            self.is_loaded = True
            
            version = data.get("version", 1)
            if version < 2:
                logger.warning("Graph file is v1. Run build_network_graph.py to rebuild.")
            
            # P2: Build pre-computed stop index for O(1) lookups
            self._build_stop_index()
    
    def _build_stop_index(self):
        """
        Pre-compute { route_key: { stop_name: [indices] } } for O(1) distance lookups.
        Called once at load time, replaces per-query linear scans.
        """
        self._stop_index = {}
        for route_key, stops in self.routes.items():
            index: Dict[str, List[int]] = defaultdict(list)
            for i, stop_name in enumerate(stops):
                index[stop_name].append(i)
            self._stop_index[route_key] = dict(index)
        
        logger.debug(f"Built stop index for {len(self._stop_index)} routes")
            
    def find_best_stop_match(self, query: str, 
                              ref_lat: Optional[float] = None,
                              ref_lon: Optional[float] = None) -> Optional[str]:
        """
        Find best matching stop name with normalization and fuzzy matching.
        
        Strategy:
        1. Exact match
        2. Normalized exact match (台↔臺, 車站→station variants)
        3. Substring match on normalized names
        4. GPS-based disambiguation if coordinates provided
        """
        if not self.is_loaded:
            self.load_graph()

        if query in self.stops:
            return query
        
        # Normalize query: expand common variants
        normalized_queries = self._normalize_stop_name(query)
        
        # Try exact match with normalized variants
        for nq in normalized_queries:
            if nq in self.stops:
                return nq
        
        # Substring match with all normalized variants
        candidates = set()
        for nq in normalized_queries:
            for s in self.stops:
                if nq in s:
                    candidates.add(s)
        
        if not candidates:
            return None
        
        candidate_list = list(candidates)
        
        # Scoring: lower = better
        def match_score(stop_name: str) -> tuple:
            """
            Sort priority:
            1. query starts the stop name (prefix match) → score 0
            2. any normalized variant starts the stop name → score 1
            3. substring match only → score 2
            Then by: route count (more routes = bigger station = better, negative for desc)
            Then by: name length (shorter = more specific)
            """
            tier = 2
            for nq in normalized_queries:
                if stop_name.startswith(nq):
                    tier = 0 if nq == query else 1
                    break
            
            route_count = len(self.stops.get(stop_name, {}).get("routes", []))
            return (tier, -route_count, len(stop_name))

        # P2: If GPS is available, sort by distance to reference point
        if ref_lat is not None and ref_lon is not None:
            def distance_to_ref(stop_name: str) -> float:
                lat = self.stops[stop_name].get("lat")
                lon = self.stops[stop_name].get("lon")
                if lat and lon:
                    return haversine_distance(ref_lat, ref_lon, lat, lon)
                return float('inf')
            
            candidate_list.sort(key=distance_to_ref)
            return candidate_list[0]
        
        # Fallback: use match_score (prefix match > substring, more routes = better)
        candidate_list.sort(key=match_score)
        return candidate_list[0]
    
    @staticmethod
    def _normalize_stop_name(query: str) -> List[str]:
        """
        Generate normalized variants of a stop name query.
        Handles: 台↔臺, common abbreviations, MRT station prefixes.
        """
        variants = [query]
        
        # 台 ↔ 臺 互轉
        if "台" in query:
            variants.append(query.replace("台", "臺"))
        if "臺" in query:
            variants.append(query.replace("臺", "台"))
        
        # 線 → 幹線 (e.g. "民權線" -> "民權幹線")
        # 不做，避免誤判
        
        # 嘗試加上「捷運」前綴 (e.g. "西門站" -> "捷運西門站")
        extra = []
        for v in variants:
            if not v.startswith("捷運"):
                extra.append("捷運" + v)
                # 也嘗試加站字尾
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

    def get_stop_uid(self, route_key: str, stop_name: str) -> Optional[str]:
        """P1: Get StopUID for a specific stop on a specific route."""
        return self.stop_uid_map.get(route_key, {}).get(stop_name)
    
    def get_stop_gps(self, stop_name: str) -> Optional[Tuple[float, float]]:
        """P2: Get GPS coordinates (lat, lon) for a stop."""
        stop = self.stops.get(stop_name, {})
        lat = stop.get("lat")
        lon = stop.get("lon")
        if lat is not None and lon is not None:
            return (lat, lon)
        return None

    def get_route_stop_distance(self, route_name: str, start: str, end: str) -> int:
        """
        Calculate directed distance using pre-computed index. O(K²) where K = occurrences.
        Only counts FORWARD direction (end index > start index).
        Returns 999 if not found or wrong direction.
        """
        if not self.is_loaded:
            self.load_graph()
        if route_name not in self._stop_index:
            return 999
            
        idx = self._stop_index[route_name]
        start_indices = idx.get(start)
        end_indices = idx.get(end)
        
        if not start_indices or not end_indices:
            return 999
            
        min_dist = 999
        for s_idx in start_indices:
            for e_idx in end_indices:
                dist = e_idx - s_idx
                if 0 < dist < min_dist:
                    min_dist = dist
        
        return min_dist

    def get_route_stops(self, route_name: str, start: str, end: str) -> List[str]:
        """Get list of stops between start and end (inclusive), forward direction only."""
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
        
        min_dist = 999
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

    def _expand_stop_group(self, stop_name: str) -> List[str]:
        """
        Expand a stop to all sibling sub-stations.
        e.g. '臺北車站(忠孝)' -> ['臺北車站(忠孝)', '臺北車站(承德)', '臺北車站(鄭州)', ...]
        For stops without parenthetical suffix, returns just [stop_name].
        """
        if "(" not in stop_name:
            # Check if there are sibling stops with parenthetical suffixes
            siblings = [s for s in self.stops if s.startswith(stop_name + "(")]
            if siblings:
                return [stop_name] + siblings
            return [stop_name]
        
        # Extract base name: '臺北車站(忠孝)' -> '臺北車站'
        base = stop_name.split("(")[0]
        siblings = [s for s in self.stops if s.startswith(base + "(") or s == base]
        return siblings if siblings else [stop_name]
    
    def _expand_stop_group_full(self, original_query: str, matched_stop: str) -> List[str]:
        """
        Full expansion: parenthetical siblings + normalized variant matches.
        
        e.g. query='西門', matched='西門' ->
            parenthetical: ['西門']  (no 西門(xxx) exists)
            normalized variants: '捷運西門站' also exists in graph
            result: ['西門', '捷運西門站']
        
        e.g. query='台北車站', matched='臺北車站(忠孝)' ->
            parenthetical: ['臺北車站(忠孝)', '臺北車站(承德)', ...]
            result: all 臺北車站(*) variants
        """
        # Start with parenthetical expansion
        group = set(self._expand_stop_group(matched_stop))
        
        # Also expand using normalized variants of the original query
        variants = self._normalize_stop_name(original_query)
        for v in variants:
            # Exact match
            if v in self.stops:
                group.add(v)
                # Also expand that match's parenthetical siblings
                for sib in self._expand_stop_group(v):
                    group.add(sib)
            # Prefix match for key transit stops
            for s in self.stops:
                if s.startswith(v) and len(s) - len(v) <= 5:
                    # Only add if suffix is short (e.g. "(忠孝)" but not "國小附近")
                    group.add(s)
        
        return list(group)
    
    def _get_merged_routes(self, stop_group: List[str]) -> set:
        """Get union of all routes from a group of stops."""
        routes = set()
        for s in stop_group:
            routes.update(self.stops.get(s, {}).get("routes", []))
        return routes

    def find_candidate_paths(self, start: str, end: str, top_k: int = 5) -> List[Dict]:
        """
        Find candidates using Greedy Hop Strategy (direction-aware, with UID).
        Expands station groups (e.g. all 台北車站 sub-stations) for broader coverage.
        """
        if not self.is_loaded:
            self.load_graph()
            
        real_start = self.find_best_stop_match(start)
        real_end = self.find_best_stop_match(end)
        
        if not real_start or not real_end:
            return []
        
        # Expand to sibling sub-stations (parenthetical + normalized variants)
        start_group = self._expand_stop_group_full(start, real_start)
        end_group = self._expand_stop_group_full(end, real_end)
        
        candidates = []
        TIME_PER_STOP = 2.5
        
        # Merge routes from all sub-stations
        start_routes = self._get_merged_routes(start_group)
        end_routes = self._get_merged_routes(end_group)
        
        # --- Priority 1: Direct ---
        common_routes = start_routes.intersection(end_routes)
        
        for r in common_routes:
            # Try all start_sub × end_sub combinations to find valid pairs
            best_dist = 999
            best_from = None
            best_to = None
            for s in start_group:
                for e in end_group:
                    dist = self.get_route_stop_distance(r, s, e)
                    if 0 < dist < best_dist:
                        best_dist = dist
                        best_from = s
                        best_to = e
            
            if best_dist < 900 and best_from and best_to:
                est_time = best_dist * TIME_PER_STOP
                start_uid = self.get_stop_uid(r, best_from)
                candidates.append({
                    "type": "direct",
                    "segments": [{"route": r, "from": best_from, "to": best_to,
                                  "from_uid": start_uid}],
                    "static_time": est_time,
                    "stop_count": best_dist
                })
        
        if candidates:
            candidates.sort(key=lambda x: x["static_time"])
            return candidates[:top_k]

        # --- Priority 2: 1-Transfer (Greedy Leg 1) ---
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
            if mid in start_group or mid in end_group:
                continue
            
            r1_candidates = [r for r in start_routes if mid in self._stop_index.get(r, {})]
            
            best_r1 = None
            best_from = None
            min_d1 = 999
            
            for r in r1_candidates:
                # Find best sub-station from start_group for this route
                for sg in start_group:
                    d = self.get_route_stop_distance(r, sg, mid)
                    if d < min_d1:
                        min_d1 = d
                        best_r1 = r
                        best_from = sg
            
            if min_d1 >= 900 or not best_r1:
                continue
            
            # Find Best Leg 2 (Mid -> End)
            r2_candidates = [r for r in end_routes if mid in self._stop_index.get(r, {})]
            
            best_r2 = None
            min_d2 = 999
            
            for r in r2_candidates:
                for eg in end_group:
                    d = self.get_route_stop_distance(r, mid, eg)
                    if d < min_d2:
                        min_d2 = d
                        best_r2 = r
            
            if not best_r2:
                continue
                
            est_time_leg1 = min_d1 * TIME_PER_STOP
            est_time_leg2 = min_d2 * TIME_PER_STOP if min_d2 < 900 else 0
            
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

        # --- Priority 3: 2-Transfer (Bridge Route) ---
        if len(candidates) < top_k * 2:
            routes_touching_s1 = set()
            for s in stops_from_start:
                for r in self.stops.get(s, {}).get("routes", []):
                    routes_touching_s1.add(r)
            
            routes_touching_s2 = set()
            for s in stops_from_end:
                for r in self.stops.get(s, {}).get("routes", []):
                    routes_touching_s2.add(r)
            
            bridge_routes = routes_touching_s1.intersection(routes_touching_s2)
            bridge_routes = bridge_routes - start_routes - end_routes
            
            for bridge in bridge_routes:
                m1_candidates = stops_from_start.intersection(
                    set(self._stop_index.get(bridge, {}).keys())
                )
                if not m1_candidates:
                    continue
                
                best_m1 = None
                best_r1 = None
                best_from_bridge = None
                min_time_to_m1 = 9999
                
                for m1 in m1_candidates:
                     valid_r1s = [r for r in start_routes if m1 in self._stop_index.get(r, {})]
                     for r in valid_r1s:
                         for sg in start_group:
                             d = self.get_route_stop_distance(r, sg, m1)
                             if d < 900:
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
        
        candidates.sort(key=lambda x: x["static_time"])
        return candidates[:top_k]
