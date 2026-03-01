"""
test_tdx_connection.py — TDX API 連線與基本功能驗證
"""
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.tdx_client import TDXClient


def test_tdx():
    print("Initializing TDX Client...")
    try:
        client = TDXClient()
        
        # 1. Test Auth
        print("\n--- Testing Authentication ---")
        client._authenticate()
        print("✅ Authentication Verified.")
        
        # 2. Test Get Stops (307)
        print("\n--- Testing Get Stops (307) ---")
        stops = client.get_stops(route_name="307", city="Taipei")
        if stops:
            print(f"✅ Successfully fetched {len(stops)} direction entries for route 307.")
            first_dir = stops[0]
            dir_stops = first_dir.get("Stops", [])
            if dir_stops:
                print(f"   First stop: {dir_stops[0].get('StopName', {}).get('Zh_tw')}")
        else:
            print("❌ Failed to fetch stops for 307 (or empty).")
            
        # 3. Test ETA
        print("\n--- Testing ETA (307) ---")
        etas = client.get_estimated_arrival(route_name="307", city="Taipei")
        if etas:
            print(f"✅ Successfully fetched {len(etas)} ETA records.")
            sample = etas[0]
            print(f"   Sample: {sample.get('StopName', {}).get('Zh_tw')} - "
                  f"EstimateTime={sample.get('EstimateTime')}s, "
                  f"StopStatus={sample.get('StopStatus')}")
        else:
            print("⚠️ No ETA data (maybe off-hours or no buses running).")

        # 4. Test Frequency
        print("\n--- Testing Route Frequency (307) ---")
        freqs = client.get_route_frequency(route_name="307", city="Taipei")
        if freqs:
            print(f"✅ Successfully fetched {len(freqs)} frequency records.")
        else:
            print("⚠️ No frequency data.")

        print("\n--- All Tests Passed ---")

    except Exception as e:
        print(f"\n❌ [ERROR] Test Failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_tdx()
