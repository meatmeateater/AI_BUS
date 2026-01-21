import sys
import os
import json

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from tdx_client import TDXClient

def test_tdx():
    print("Initializing TDX Client...")
    try:
        client = TDXClient()
        
        # 1. Test Auth
        print("\n--- Testing Authentication ---")
        client._authenticate()
        print("Authentication Verified.")
        
        # 2. Test Get Routes (Taipei - 307)
        print("\n--- Testing Get Routes (307) ---")
        # Note: TDX RouteName is usually an object {"Zh_tw": "...", "En": "..."}
        # But the API call might just take the string "307" if filtering on client side or specialized endpoint
        # The generic get_routes gets ALL routes, so we filter locally for the test.
        # Alternatively use OData $filter if we wanted to be fancy, but let's stick to Python filtering for simplicity.
        
        # Doing a specific route fetch using get_stops as a proxy for "does this route exist" is easier
        # Or using the specific route endpoint if available.
        # Let's try get_stops for 307
        stops = client.get_stops(route_name="307", city="Taipei")
        if stops:
            print(f"Successfully fetched {len(stops)} stops for route 307.")
            print(f"Sample stop: {stops[0].get('StopName', {}).get('Zh_tw')}")
        else:
            print("Failed to fetch stops for 307 (or empty).")
            
        # 3. Test ETA
        print("\n--- Testing ETA (307) ---")
        etas = client.get_estimated_arrival(route_name="307", city="Taipei")
        if etas:
            print(f"Successfully fetched {len(etas)} ETA records.")
            print(f"Sample ETA: {etas[0].get('StopName', {}).get('Zh_tw')} - {etas[0].get('EstimateTime')}s")
        else:
            print("Failed to fetch ETAs (maybe off hours?).")

    except Exception as e:
        print(f"\n[ERROR] Test Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_tdx()
