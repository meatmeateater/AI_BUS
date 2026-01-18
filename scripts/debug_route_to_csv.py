import sys
import os
import csv
import json
from datetime import datetime

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.crawler_core import BusCrawler
from src.cache_manager import CacheManager

def save_route_to_csv(route_id: str, output_file: str = None):
    print(f"Fetching data for Route ID: {route_id}...")
    
    # Force fetch (bypass cache if needed, but here we use the crawler directly)
    data = BusCrawler.get_route_data(route_id)
    
    if not data:
        print("Failed to fetch data.")
        return

    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
            'data', 'logs', 
            f'route_{route_id}_{timestamp}.csv'
        )

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    print(f"Parsing data...")
    rows = []
    
    # Process Go Direction
    if "GoDirStops" in data:
        for stop in data["GoDirStops"]:
            rows.append({
                "Direction": "Go (去程)",
                "StopName": stop.get("Name"),
                "ETA_Seconds": stop.get("ETA"),
                "NextDepTime": stop.get("NextDepTime", ""),
                "BusTimeDesc": stop.get("BusTimeDesc", ""),
                "UniStopId": stop.get("UniStopId"),
                "Latitude": stop.get("Latitude"),
                "Longitude": stop.get("Longitude")
            })

    # Process Back Direction
    if "BackDirStops" in data:
        for stop in data["BackDirStops"]:
            rows.append({
                "Direction": "Back (返程)",
                "StopName": stop.get("Name"),
                "ETA_Seconds": stop.get("ETA"),
                "NextDepTime": stop.get("NextDepTime", ""),
                "BusTimeDesc": stop.get("BusTimeDesc", ""),
                "UniStopId": stop.get("UniStopId"),
                "Latitude": stop.get("Latitude"),
                "Longitude": stop.get("Longitude")
            })

    # Write to CSV
    if rows:
        headers = rows[0].keys()
        with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Successfully saved {len(rows)} stops to: {output_file}")
    else:
        print("No stop data found to write.")

if __name__ == "__main__":
    # Default to 307 if no argument provided
    target_id = "0100030700" 
    if len(sys.argv) > 1:
        target_id = sys.argv[1]
        
    save_route_to_csv(target_id)
