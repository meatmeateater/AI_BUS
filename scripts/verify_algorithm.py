import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_server import plan_trip, get_bus_arrival_time
from graph_engine import GraphEngine

def verify_flow():
    print("--- 1. Testing Route Planning (Algorithm) ---")
    # Using a common route: Taipei Main Station to a known location
    # Valid stops found in graph
    start = "新北板橋公車站"
    end = "臺北客運板橋前站(藝文)"
    
    print(f"Planning trip from {start} to {end}...")
    result = plan_trip(start, end)
    print("Result:")
    print(result)
    
    if "最快路線建議" in result:
        print("\n[Analysis]")
        print("The algorithm successfully simulated a route based on valid static data.")
        if "分" in result: # Check for minutes or dynamic data
            print("The system successfully injected Real-Time TDX data into the response.")
        else:
            print("WARNING: Real-Time data was NOT found in the response (check route name mapping).")
    else:
        print("\n[Analysis]")
        print("Route planning failed. This might be due to missing static graph data.")

if __name__ == "__main__":
    verify_flow()
