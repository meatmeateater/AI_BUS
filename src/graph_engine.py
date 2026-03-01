import json
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class GraphEngine:
    def __init__(self, graph_file: str):
        self.graph_file = graph_file
        self.stops: Dict[str, Dict] = {}
        self.routes: Dict[str, List[str]] = {}
        self.is_loaded = False
        
    def load_graph(self):
        if not os.path.exists(self.graph_file):
            logger.warning(f"Graph file not found: {self.graph_file}")
            return
            
        with open(self.graph_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.stops = data.get("stops", {})
            self.routes = data.get("routes", {})
            self.is_loaded = True
            
    def find_best_stop_match(self, query: str) -> Optional[str]:
        """
        Find best matching stop name.
        """
        if not self.is_loaded:
            self.load_graph()

        if query in self.stops:
            return query
            
        # 1. Partial match (e.g. "台北車站" in "台北車站(忠孝)")
        candidates = [s for s in self.stops.keys() if query in s]
        if candidates:
            # Pick shortest one (most generic)
            candidates.sort(key=len)
            return candidates[0]
            
        return None

    def get_route_stop_distance(self, route_name: str, start: str, end: str) -> int:
        """
        Calculate number of stops between start and end on a route.
        Returns 999 if not found or order is wrong.
        """
        if route_name not in self.routes:
            return 999
            
        stops = self.routes[route_name]
        try:
            start_indices = [i for i, x in enumerate(stops) if x == start]
            end_indices = [i for i, x in enumerate(stops) if x == end]
            
            if not start_indices or not end_indices:
                return 999
                
            min_dist = 999
            for s_idx in start_indices:
                for e_idx in end_indices:
                    dist = abs(e_idx - s_idx)
                    if dist < min_dist:
                        min_dist = dist
            
            return min_dist
        except Exception:
            return 999

    def get_route_stops(self, route_name: str, start: str, end: str) -> List[str]:
        """
        Get list of stops between start and end (inclusive).
        Returns empty list if invalid.
        """
        if route_name not in self.routes:
            return []
            
        stops = self.routes[route_name]
        try:
            start_indices = [i for i, x in enumerate(stops) if x == start]
            end_indices = [i for i, x in enumerate(stops) if x == end]
            
            if not start_indices or not end_indices:
                return []
            
            min_dist = 999
            best_s = -1
            best_e = -1
            
            for s_idx in start_indices:
                for e_idx in end_indices:
                    dist = abs(e_idx - s_idx)
                    if dist < min_dist:
                        min_dist = dist
                        best_s = s_idx
                        best_e = e_idx
            
            if best_s == -1:
                return []
                
            if best_s <= best_e:
                return stops[best_s : best_e+1]
            else:
                segment = stops[best_e : best_s+1]
                return segment[::-1]
        except Exception:
            return []

    def find_candidate_paths(self, start: str, end: str, top_k: int = 5) -> List[Dict]:
        """
        Find candidates using Greedy Hop Strategy.
        Priority 1: Direct Routes.
        Priority 2: 1-Transfer (Optimize Leg 1).
        Priority 3: 2-Transfer (Bridge Route).
        """
        if not self.is_loaded:
            self.load_graph()
            
        real_start = self.find_best_stop_match(start)
        real_end = self.find_best_stop_match(end)
        
        if not real_start or not real_end:
            return []
            
        start, end = real_start, real_end
        candidates = []

        TIME_PER_STOP = 2.5
        
        start_routes = set(self.stops[start]["routes"])
        end_routes = set(self.stops[end]["routes"])
        
        # --- Priority 1: Direct ---
        common_routes = start_routes.intersection(end_routes)
        
        for r in common_routes:
            dist = self.get_route_stop_distance(r, start, end)
            if dist < 900: 
                est_time = dist * TIME_PER_STOP
                candidates.append({
                    "type": "direct",
                    "segments": [{"route": r, "from": start, "to": end}],
                    "static_time": est_time,
                    "stop_count": dist
                })
        
        # If Direct routes exist, return them (Highest Priority)
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
            if mid == start or mid == end:
                continue
            
            # Find Best Leg 1 (Start -> Mid)
            r1_candidates = [r for r in start_routes if mid in self.routes.get(r, [])]
            
            best_r1 = None
            min_d1 = 999
            
            for r in r1_candidates:
                d = self.get_route_stop_distance(r, start, mid)
                if d < min_d1:
                    min_d1 = d
                    best_r1 = r
            
            if min_d1 < 900 and best_r1:
                est_time = min_d1 * TIME_PER_STOP
                candidates.append({
                    "type": "transfer_greedy",
                    "transfer_stop": mid,
                    "segments": [
                        {"route": best_r1, "from": start, "to": mid}
                    ],
                    "static_time": est_time,
                    "stop_count": min_d1
                })

        # --- Priority 3: 2-Transfer (Bridge Route) ---
        if len(candidates) < top_k * 2:
            routes_touching_s1 = set()
            for s in stops_from_start:
                for r in self.stops[s]["routes"]:
                    routes_touching_s1.add(r)
            
            routes_touching_s2 = set()
            for s in stops_from_end:
                for r in self.stops[s]["routes"]:
                    routes_touching_s2.add(r)
            
            bridge_routes = routes_touching_s1.intersection(routes_touching_s2)
            bridge_routes = bridge_routes - start_routes - end_routes
            
            for bridge in bridge_routes:
                bridge_stops = set(self.routes.get(bridge, []))
                m1_candidates = stops_from_start.intersection(bridge_stops)
                if not m1_candidates:
                    continue
                
                best_m1 = None
                best_r1 = None
                min_time_to_m1 = 9999
                
                for m1 in m1_candidates:
                     valid_r1s = [r for r in start_routes if m1 in self.routes.get(r, [])]
                     for r in valid_r1s:
                         d = self.get_route_stop_distance(r, start, m1)
                         if d < 900:
                             t = d * TIME_PER_STOP
                             if t < min_time_to_m1:
                                 min_time_to_m1 = t
                                 best_m1 = m1
                                 best_r1 = r
                
                if best_m1 and best_r1:
                    candidates.append({
                        "type": "transfer_greedy",
                        "transfer_stop": best_m1,
                        "segments": [
                            {"route": best_r1, "from": start, "to": best_m1}
                        ],
                        "static_time": min_time_to_m1,
                        "stop_count": int(min_time_to_m1 / TIME_PER_STOP),
                        "note": "Bridge Route"
                    })
        
        candidates.sort(key=lambda x: x["static_time"])
        return candidates[:top_k]
