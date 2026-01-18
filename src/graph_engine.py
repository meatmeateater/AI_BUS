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
        
        return None 
