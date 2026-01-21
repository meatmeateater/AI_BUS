import sys
import os
import json

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from tdx_client import TDXClient

def debug_route_info():
    client = TDXClient()
    client._authenticate()
    
    # Get all routes to check structure
    print("Fetching routes...")
    routes = client.get_routes(city="Taipei")
    
    # Look for 307 or 299 as examples of high frequency
    targets = ["307", "299", "小2"] # Small 2 is usually low freq
    
    for r in routes:
        name = r.get("RouteName", {}).get("Zh_tw", "")
        if name in targets:
            print(f"\n--- Route: {name} ---")
            # print useful fields
            keys = ["DepartureStopNameZh", "DestinationStopNameZh", "RouteUID", "City", 
                    "HasSubRoutes", "BusRouteType", "Daily" ] # Daily might not exist but let's check structure
            
            # Dump full first to see keys
            print(json.dumps(r, ensure_ascii=False, indent=2))
            
            # We specifically look for "Frequency" or "Headway" info?
            # Usually basic /Route endpoint DOES NOT have frequency.
            # We might need /Frequency/City/{City}/{RouteName}? No, that's not standard.
            # Or /Route/Schedule?
            
            # Let's check keys.
            break

if __name__ == "__main__":
    debug_route_info()
