import json
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Direction suffix constants
DIR_GO = "__go"
DIR_BACK = "__back"


def get_base_route_name(route_key: str) -> str:
    """
    Strip direction suffix from route key.
    '307__go' -> '307', '復興幹線__back' -> '復興幹線'
    """
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
            
            version = data.get("version", 1)
            if version < 2:
                logger.warning("Graph file is v1 (not direction-aware). "
                               "Run build_network_graph.py to rebuild.")
            
    def find_best_stop_match(self, query: str) -> Optional[str]:
        """Find best matching stop name."""
        if not self.is_loaded:
            self.load_graph()

        if query in self.stops:
            return query
            
        # Partial match (e.g. "台北車站" in "台北車站(忠孝)")
        candidates = [s for s in self.stops.keys() if query in s]
        if candidates:
            candidates.sort(key=len)
            return candidates[0]
            
        return None

    def get_route_stop_distance(self, route_name: str, start: str, end: str) -> int:
        """
        Calculate directed distance (number of stops) from start to end on a route.
        Only counts FORWARD direction (end must appear AFTER start in the stop list).
        Returns 999 if not found or wrong direction.
        """
        if not self.is_loaded:
            self.load_graph()
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
                    # Direction-enforced: end must come AFTER start
                    dist = e_idx - s_idx
                    if dist > 0 and dist < min_dist:
                        min_dist = dist
            
            return min_dist
        except Exception:
            return 999

    def get_route_stops(self, route_name: str, start: str, end: str) -> List[str]:
        """
        Get list of stops between start and end (inclusive), forward direction only.
        """
        if not self.is_loaded:
            self.load_graph()
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
                    dist = e_idx - s_idx
                    if dist > 0 and dist < min_dist:
                        min_dist = dist
                        best_s = s_idx
                        best_e = e_idx
            
            if best_s == -1:
                return []
                
            return stops[best_s : best_e + 1]
        except Exception:
            return []

    def find_candidate_paths(self, start: str, end: str, top_k: int = 5) -> List[Dict]:
        """
        Find candidates using Greedy Hop Strategy (direction-aware).
        
        Route keys in the graph are direction-specific (e.g. '307__go', '307__back').
        Distance calculation enforces forward direction only.
        
        Priority 1: Direct Routes.
        Priority 2: 1-Transfer (Optimize Leg 1, include Leg 2 info).
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
        
        start_routes = set(self.stops.get(start, {}).get("routes", []))
        end_routes = set(self.stops.get(end, {}).get("routes", []))
        
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
            
            if min_d1 >= 900 or not best_r1:
                continue
            
            # Find Best Leg 2 (Mid -> End) for transfer safety check
            r2_candidates = [r for r in end_routes if mid in self.routes.get(r, [])]
            
            best_r2 = None
            min_d2 = 999
            
            for r in r2_candidates:
                d = self.get_route_stop_distance(r, mid, end)
                if d < min_d2:
                    min_d2 = d
                    best_r2 = r
            
            if not best_r2:
                continue
                
            est_time_leg1 = min_d1 * TIME_PER_STOP
            est_time_leg2 = min_d2 * TIME_PER_STOP if min_d2 < 900 else 0
            
            candidates.append({
                "type": "transfer_greedy",
                "transfer_stop": mid,
                "segments": [
                    {"route": best_r1, "from": start, "to": mid}
                ],
                "transfer_route": best_r2,  # For safety check
                "static_time": est_time_leg1,
                "remaining_time": est_time_leg2,  # Estimated Leg 2 time
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
                        "transfer_route": bridge,  # Bridge route for safety check
                        "static_time": min_time_to_m1,
                        "remaining_time": 0,
                        "stop_count": int(min_time_to_m1 / TIME_PER_STOP),
                        "note": "Bridge Route"
                    })
        
        candidates.sort(key=lambda x: x["static_time"])
        return candidates[:top_k]
