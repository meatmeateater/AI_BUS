import logging
import os
from typing import Optional, Dict, Any, List
from .tdx_client import TDXClient

# Setup logging
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'logs')
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
    
logging.basicConfig(
    filename=os.path.join(log_dir, 'crawler_error.log'),
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
                logging.error(f"Failed to initialize TDXClient: {e}")
        return cls._client

    @classmethod
    def get_route_data(cls, route_name: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Fetch route data using TDX API.
        
        Args:
            route_name: The name of the route (e.g. "307"). 
                        NOTE: This replaces the old `route_id` usage. 
                        If a numeric ID is passed, it might fail unless we map it.
                        The caller should pass the Route Name.
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
            # We fetch stops to ensure we have the full list and order.
            stops_data = client.get_stops(route_name, city="Taipei")
            if not stops_data:
                # Try NewTaipei if Taipei fails? 
                # Many buses are cross-city. TDX usually requires knowing the city.
                # Let's try NewTaipei if Taipei returns nothing.
                stops_data = client.get_stops(route_name, city="NewTaipei")
                if not stops_data:
                     # One last try: "Taipei" might cover both in some endpoints? No.
                     logging.warning(f"No stops found for {route_name} in Taipei or NewTaipei")
                     return None
                city_found = "NewTaipei"
            else:
                city_found = "Taipei"

            # 2. Get Estimates (Real-time data)
            etas_data = client.get_estimated_arrival(route_name, city=city_found)
            
            # Map ETAs for fast lookup: Direction -> StopUID -> ETA Data
            eta_map = {}
            for item in etas_data:
                d = item.get("Direction", 0)
                uid = item.get("StopUID")
                if d not in eta_map:
                    eta_map[d] = {}
                eta_map[d][uid] = item

            # 3. Assemble Result
            result = {
                "GoDirStops": [],
                "BackDirStops": []
            }

            for route_dir in stops_data:
                direction = route_dir.get("Direction", 0) # 0: Go, 1: Back
                stops = route_dir.get("Stops", [])
                
                processed_stops = []
                for stop in stops:
                    uid = stop.get("StopUID")
                    name = stop.get("StopName", {}).get("Zh_tw", "Unknown")
                    
                    stop_info = {
                        "Name": name,
                        "StopUID": uid,
                        "ETA": None,
                        "NextDepTime": None
                    }
                    
                    # Merge ETA
                    if direction in eta_map and uid in eta_map[direction]:
                        eta_item = eta_map[direction][uid]
                        # EstimateTime is in seconds.
                        # TDX: if StopStatus != 0 (Normal), EstimateTime might be null or meaningless?
                        # StopStatus: 0:Normal, 1:NotStarted, 2:Past, 3:Pit, 4:Operating (but not readable)
                        status = eta_item.get("StopStatus")
                        est_time = eta_item.get("EstimateTime")
                        
                        if status == 0 and est_time is not None:
                            stop_info["ETA"] = est_time
                        elif status == 1:
                            stop_info["ETA"] = 65535 # Borrowing old crawler code for "Not Started"
                            # Or check NextBusTime
                            next_bus = eta_item.get("NextBusTime")
                            if next_bus:
                                # Format: 2023-10-27T12:00:00+08:00
                                # We just want HH:MM
                                try:
                                    stop_info["NextDepTime"] = next_bus.split("T")[1][:5]
                                except:
                                    pass
                        elif status == 2: # Past
                            stop_info["ETA"] = -2 # Arbitrary negative for passed
                        elif status == 3: # Pit (End of line?)
                             stop_info["ETA"] = -3
                        
                    processed_stops.append(stop_info)
                
                if direction == 0:
                    result["GoDirStops"] = processed_stops
                elif direction == 1:
                    result["BackDirStops"] = processed_stops
            
            return result

        except Exception as e:
            logging.error(f"Error fetching TDX data for {route_name}: {e}")
            return None

if __name__ == "__main__":
    # Test with a known Route Name (e.g., 307)
    test_route = "307"
    data = BusCrawler.get_route_data(test_route)
    if data:
        print("Successfully fetched data")
        # Print first few chars to debug structure
        print(str(data)[:500])
        
        # Check ETA count
        go_stops = data.get("GoDirStops", [])
        print(f"Go Stop Count: {len(go_stops)}")
        if go_stops:
            print(f"First Stop: {go_stops[0]}")
    else:
        print("Failed to fetch data")

