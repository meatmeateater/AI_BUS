import sys
import os
import json

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from tdx_client import TDXClient

def debug_tdx():
    client = TDXClient()
    client._authenticate()
    
    # Debug Stops
    print("\n--- Debug Stops (307) ---")
    stops = client.get_stops(route_name="307", city="Taipei")
    if stops:
        print(f"Count: {len(stops)}")
        print(json.dumps(stops[0], ensure_ascii=False, indent=2))
    else:
        print("No stops found")

if __name__ == "__main__":
    debug_tdx()
