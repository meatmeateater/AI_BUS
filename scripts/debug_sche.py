import sys
import os
import json

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from tdx_client import TDXClient

def debug_schedule_freq():
    client = TDXClient()
    client._authenticate()
    
    routes = ["307", "小2"]
    
    for r in routes:
        print(f"\n=== Route {r} ===")
        
        print(f"--- Freq ---")
        freq = client.get_route_frequency(r)
        if freq:
            print(json.dumps(freq[0], ensure_ascii=False, indent=2))
        else:
            print("No Freq data")
            
        print(f"--- Schedule ---")
        sched = client.get_schedule(r)
        if sched:
            print(f"Schedule items: {len(sched)}")
            print(json.dumps(sched[0], ensure_ascii=False, indent=2))
        else:
            print("No Schedule data")

if __name__ == "__main__":
    debug_schedule_freq()
