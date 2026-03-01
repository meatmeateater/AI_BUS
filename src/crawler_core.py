import logging
import os
from typing import Optional, Dict, Any, List
from .tdx_client import TDXClient

logger = logging.getLogger(__name__)


class BusCrawler:
    """
    Adapter class to fetch bus data using TDXClient.
    Replaces the old HTML scraping logic.
    """
    _client = None

    @classmethod
    def get_client(cls):
        if not cls._client:
            try:
                cls._client = TDXClient()
            except Exception as e:
                logger.error(f"Failed to initialize TDXClient: {e}")
        return cls._client

    @classmethod
    def get_route_data(cls, route_name: str, only_static: bool = False, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Fetch route data using TDX API.
        
        Args:
            route_name: The name of the route (e.g. "307").
            only_static: If True, skip fetching real-time ETA data (for graph building).
            **kwargs: Ignored compatibility args.
        
        Returns:
            Dict in the format:
            {
                "GoDirStops": [ { "Name": "...", "ETA": int, "NextDepTime": "...", ... }, ... ],
                "BackDirStops": [ ... ]
            }
        """
        client = cls.get_client()
        if not client:
            return None

        try:
            # 1. Get Stops (to build the skeleton)
            stops_data = client.get_stops(route_name, city="Taipei")
            if not stops_data:
                # Try NewTaipei if Taipei fails (many buses are cross-city)
                stops_data = client.get_stops(route_name, city="NewTaipei")
                if not stops_data:
                     logger.warning(f"No stops found for {route_name} in Taipei or NewTaipei")
                     return None
                city_found = "NewTaipei"
            else:
                city_found = "Taipei"

            # 2. Get Estimates (Real-time data) — skip if only_static
            eta_map: Dict[int, Dict[str, Any]] = {}
            if not only_static:
                etas_data = client.get_estimated_arrival(route_name, city=city_found)
                for item in etas_data:
                    d = item.get("Direction", 0)
                    uid = item.get("StopUID")
                    if d not in eta_map:
                        eta_map[d] = {}
                    eta_map[d][uid] = item

            # 3. Assemble Result
            result: Dict[str, List[Dict[str, Any]]] = {
                "GoDirStops": [],
                "BackDirStops": []
            }

            for route_dir in stops_data:
                direction = route_dir.get("Direction", 0)  # 0: Go, 1: Back
                stops = route_dir.get("Stops", [])
                
                processed_stops = []
                for stop in stops:
                    uid = stop.get("StopUID")
                    name = stop.get("StopName", {}).get("Zh_tw", "Unknown")
                    
                    stop_info: Dict[str, Any] = {
                        "Name": name,
                        "StopUID": uid,
                        "ETA": None,
                        "NextDepTime": None
                    }
                    
                    # Merge ETA (only if we fetched real-time data)
                    if direction in eta_map and uid in eta_map[direction]:
                        eta_item = eta_map[direction][uid]
                        # StopStatus: 0:Normal, 1:NotStarted, 2:Past, 3:Pit
                        status = eta_item.get("StopStatus")
                        est_time = eta_item.get("EstimateTime")
                        
                        if status == 0 and est_time is not None:
                            stop_info["ETA"] = est_time
                        elif status == 1:
                            stop_info["ETA"] = 65535  # "Not Started" marker
                            next_bus = eta_item.get("NextBusTime")
                            if next_bus:
                                try:
                                    stop_info["NextDepTime"] = next_bus.split("T")[1][:5]
                                except Exception:
                                    pass
                        elif status == 2:  # Past
                            stop_info["ETA"] = -2
                        elif status == 3:  # Pit (End of line)
                             stop_info["ETA"] = -3
                        
                    processed_stops.append(stop_info)
                
                if direction == 0:
                    result["GoDirStops"] = processed_stops
                elif direction == 1:
                    result["BackDirStops"] = processed_stops
            
            return result

        except Exception as e:
            logger.error(f"Error fetching TDX data for {route_name}: {e}")
            return None
