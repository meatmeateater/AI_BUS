import json
import os
import heapq
from typing import List, Dict, Optional, Tuple, Set

class GraphEngine:
    def __init__(self, graph_file: str):
        self.graph_file = graph_file
        self.stops: Dict[str, Dict] = {}
        self.routes: Dict[str, List[str]] = {}
        self.is_loaded = False
        
    def load_graph(self):
        if not os.path.exists(self.graph_file):
            print(f"Graph file not found: {self.graph_file}")
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
            # Pick shortest one usually (most generic) or first
            candidates.sort(key=len)
            return candidates[0]
            
        # 2. Fuzzy match could go here if needed (using difflib)
        return None

    def find_path_bfs(self, start: str, end: str) -> Optional[Dict]:
        """
        Find a path using BFS (Minimize transfers).
        Returns a simplified plan: 
        {
            "type": "direct" | "transfer",
            "segments": [
                {"route": "307", "from": "A", "to": "B"}
            ]
        }
        """
        if not self.is_loaded:
            self.load_graph()
            
        # Fuzzy match for start/end
        real_start = self.find_best_stop_match(start)
        real_end = self.find_best_stop_match(end)
        
        if not real_start or not real_end:
            print(f"Could not find stops matching {start} or {end}")
            return None
            
        start, end = real_start, real_end 

        # --- Phase 1: 0-Transfer (Direct) ---
        start_routes = set(self.stops[start]["routes"])
        end_routes = set(self.stops[end]["routes"])
        
        common_routes = start_routes.intersection(end_routes)
        if common_routes:
            best_route = list(common_routes)[0]
            return {
                "type": "direct",
                "segments": [
                    {"route": best_route, "from": start, "to": end}
                ]
            }

        # --- Phase 2: 1-Transfer ---
        # Strategy: Intersection of Stops
        # S1 = Stops reachable from Start via StartRoutes
        # S2 = Stops that can reach End via EndRoutes
        # If intersection(S1, S2) exists, that's the transfer point.
        
        stops_from_start = set()
        route_to_start_map = {} # Stop -> RouteName (that gets us here from Start)
        
        for r in start_routes:
            for s in self.routes.get(r, []):
                stops_from_start.add(s)
                if s not in route_to_start_map:
                    route_to_start_map[s] = r

        stops_from_end = set()
        route_from_end_map = {} # Stop -> RouteName (that takes us to End)
        
        for r in end_routes:
            for s in self.routes.get(r, []):
                stops_from_end.add(s)
                if s not in route_from_end_map:
                    route_from_end_map[s] = r
                    
        common_stops = stops_from_start.intersection(stops_from_end)
        if common_stops:
            transfer_stop = list(common_stops)[0]
            r1 = route_to_start_map[transfer_stop]
            r2 = route_from_end_map[transfer_stop]
            return {
                "type": "transfer",
                "transfer_stop": transfer_stop,
                "segments": [
                    {"route": r1, "from": start, "to": transfer_stop},
                    {"route": r2, "from": transfer_stop, "to": end}
                ]
            }

        # --- Phase 3: 2-Transfers ---
        # Strategy: Intersection of Routes
        # R_mid must be reachable from S1 and connect to S2.
        # R_mid must serve a stop in S1 AND a stop in S2.
        
        # Get all routes passing through S1 (excluding start_routes)
        routes_from_s1 = set()
        for s in stops_from_start:
            for r in self.stops[s]["routes"]:
                routes_from_s1.add(r)
                
        # Get all routes passing through S2 (excluding end_routes)
        routes_from_s2 = set()
        for s in stops_from_end:
            for r in self.stops[s]["routes"]:
                routes_from_s2.add(r)
        
        common_mid_routes = routes_from_s1.intersection(routes_from_s2)
        
        if common_mid_routes:
            # Found a bridge route!
            mid_route = list(common_mid_routes)[0]
            
            # Now find the transfer points
            # T1: Stop on mid_route that is in stops_from_start
            # T2: Stop on mid_route that is in stops_from_end
            
            mid_route_stops = set(self.routes.get(mid_route, []))
            
            t1_candidates = stops_from_start.intersection(mid_route_stops)
            t2_candidates = stops_from_end.intersection(mid_route_stops)
            
            if t1_candidates and t2_candidates:
                t1 = list(t1_candidates)[0]
                t2 = list(t2_candidates)[0]
                
                r1 = route_to_start_map[t1]
                r3 = route_from_end_map[t2]
                
                return {
                    "type": "2-transfer",
                    "transfer_stops": [t1, t2],
                    "segments": [
                        {"route": r1, "from": start, "to": t1},
                        {"route": mid_route, "from": t1, "to": t2},
                        {"route": r3, "from": t2, "to": end}
                    ]
                }
        
    def get_route_stop_distance(self, route_name: str, start: str, end: str) -> int:
        """
        Calculate number of stops between start and end on a route.
        Returns 999 if not found or order is wrong (implicit check).
        """
        if route_name not in self.routes:
            return 999
            
        stops = self.routes[route_name]
        try:
            # We need to handle directions. storage might be a simple list.
            # If the list is [A, B, C, D], dist(A,C) = 2.
            # If storage doesn't separate directions (common in simple graphs), 
            # we might find A before B (idxA < idxB) or B before A.
            # Assuming the graph stores one sequence per route ID (or merged).
            # If merged, we just take abs(buffer).
            # If separate route IDs for directions exist, we should use them.
            # But here `route_name` is likely the key in `self.routes`.
            
            # Simple assumption: One direction or merged. 
            # If we find both, take simple distance.
            
            start_indices = [i for i, x in enumerate(stops) if x == start]
            end_indices = [i for i, x in enumerate(stops) if x == end]
            
            if not start_indices or not end_indices:
                return 999
                
            # Find minimum positive distance (end > start)
            # If we allow "Back" direction logic in the same list, just closest pair.
            # But bus routes assume A->B.
            # Let's assume the list is ordered.
            
            min_dist = 999
            for s_idx in start_indices:
                for e_idx in end_indices:
                    # Calculate absolute distance to support graph ambiguity
                    dist = abs(e_idx - s_idx)
                    if dist < min_dist:
                        min_dist = dist
            
            return min_dist
        except:
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
            
            # Find closest pair
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
                # Reverse slice
                # extended slice [start:end:-1] ? 
                # stops[5:2:-1] gives [5,4,3] (not including 2). 
                # We want inclusive.
                segment = stops[best_e : best_s+1]
                return segment[::-1]
        except:
            return []

    def find_candidate_paths(self, start: str, end: str, top_k: int = 5) -> List[Dict]:
        """
        Find candidates using Greedy Hop Strategy.
        Priority 1: Direct Routes.
        Priority 2: 1-Transfer (Optimize Leg 1).
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
        
        # If Direct routes exist, return them immediately (User: "Highest Priority")
        if candidates:
            candidates.sort(key=lambda x: x["static_time"])
            return candidates[:top_k]

        # --- Priority 2: 1-Transfer (Greedy Leg 1) ---
        # Find intersections
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
        
        # If 1-Transfer found, return? 
        # User wants "Greedy Leg 1". A direct bus to a Hub (1-transfer) is likely better than 
        # a bus to a Bridge (2-transfer). 
        # But what if 1-Transfer is huge detour? 
        # For now, let's include 2-Transfers but sort by time.
        # If 1-transfer exists with short time, it will win.

        # --- Priority 3: 2-Transfer (Bridge Route) ---
        # Only needed if candidates list is small or empty?
        # Or always search to be thorough?
        # Let's search if len(candidates) < top_k * 2 to ensure variety.
        
        if len(candidates) < top_k * 2:
            # We need routes that pass through stops_from_start AND stops_from_end
            
            # Map stop -> routes is needed efficiently
            # We have self.stops[s]["routes"]
            
            # Get all routes reachable from S1 (excluding start_routes)
            routes_touching_s1 = set()
            for s in stops_from_start:
                for r in self.stops[s]["routes"]:
                    routes_touching_s1.add(r)
            
            # Get all routes reachable from S2
            routes_touching_s2 = set()
            for s in stops_from_end:
                for r in self.stops[s]["routes"]:
                    routes_touching_s2.add(r)
            
            bridge_routes = routes_touching_s1.intersection(routes_touching_s2)
            
            # Filter out start/end routes (already covered)
            bridge_routes = bridge_routes - start_routes - end_routes
            
            for bridge in bridge_routes:
                # Find connection points
                bridge_stops = set(self.routes.get(bridge, []))
                
                # M1: intersection(S1, BridgeStops)
                m1_candidates = stops_from_start.intersection(bridge_stops)
                if not m1_candidates: continue
                
                # We just pick ONE m1 (closest to start preferably)
                # Or generate candidates for all? Too many.
                # Pick the one that yields fastest Leg 1.
                
                best_m1 = None
                best_r1 = None
                min_time_to_m1 = 9999
                
                for m1 in m1_candidates:
                     # Find r1: Start -> m1
                     # Reuse logic
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
                    # Check if M2 exists (it must, by set logic, but good to be sane)
                    # We don't need M2 for the candidate, just existence.
                    
                    # Add candidate
                    # Note: Type is still "transfer_greedy" because we guide to M1.
                    # We can add a note it's a "Bridge" path?
                    # The UI just says "Transfer".
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
        
        # Deduplicate candidates by (route, to)
        # Keep fastest for same (route, to) pair?
        # Actually (route, from, to) is unique enough.
        # But we might have multiple routes to same 'mid'.
        # We can keep them.
        
        # Sort by Leg 1 time
        candidates.sort(key=lambda x: x["static_time"])
        return candidates[:top_k]

