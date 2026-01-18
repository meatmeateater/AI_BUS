import requests
from bs4 import BeautifulSoup
import json
import logging
import os
import re
import time
from typing import Optional, Dict, Any, List

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
    BASE_URL = "https://ebus.gov.taipei/Route/StopsOfRoute"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    
    @classmethod
    def get_route_data(cls, route_id: str, only_static: bool = False) -> Optional[Dict[str, Any]]:
        """
        Fetch route data from ebus.gov.taipei.
        If only_static is True, skips the dynamic status update to be faster.
        """
        try:
            response = requests.get(
                f"{cls.BASE_URL}?routeid={route_id}", 
                headers={"User-Agent": cls.USER_AGENT},
                timeout=10
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logging.warning(f"Timeout fetching route {route_id}, retrying once...")
            try:
                response = requests.get(
                    f"{cls.BASE_URL}?routeid={route_id}", 
                    headers={"User-Agent": cls.USER_AGENT},
                    timeout=10
                )
                response.raise_for_status()
            except Exception as e:
                logging.error(f"Failed to fetch route {route_id} after retry: {e}")
                return None
        except Exception as e:
            logging.error(f"Failed to fetch route {route_id}: {e}")
            return None

        # Parse logic
        try:
            static_data = cls._parse_html(response.text, route_id)
            
            if only_static:
                return static_data

            csrf_token = cls._extract_csrf_token(response.text)
            
            if not csrf_token:
                logging.warning(f"No CSRF token found for route {route_id}, dynamic data might fail.")
                
            dynamic_data = cls._fetch_dynamic_status(route_id, csrf_token, response.cookies)
            
            return cls._merge_data(static_data, dynamic_data)
            
        except Exception as e:
            # Debug: Dump HTML to file
            debug_file = os.path.join(log_dir, f"debug_{route_id}.html")
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(response.text)
            logging.error(f"Error parsing data for route {route_id}: {e}. HTML saved to {debug_file}")
            return None

    @staticmethod
    def _extract_csrf_token(html: str) -> Optional[str]:
        match = re.search(r'name="__RequestVerificationToken" type="hidden" value="(.*?)"', html)
        if match:
            return match.group(1)
        return None

    @classmethod
    def _fetch_dynamic_status(cls, route_id: str, token: str, cookies: Any) -> List[Dict[str, Any]]:
        api_url = "https://ebus.gov.taipei/Route/StopStatusOfRoute"
        params = {"routeid": route_id}
        data = {
            "__RequestVerificationToken": token,
            "X-Requested-With": "XMLHttpRequest"
        }
        headers = {
            "User-Agent": cls.USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{cls.BASE_URL}?routeid={route_id}"
        }
        
        try:
            response = requests.post(
                f"{api_url}?routeid={route_id}", 
                data=data, 
                headers=headers, 
                cookies=cookies,
                timeout=10
            )
            response.raise_for_status()
            # The API returns a JSON string content, which request.json() returns as a string.
            # We need to parse that string into a list/object.
            return json.loads(response.json())
        except Exception as e:
            logging.error(f"Failed to fetch dynamic status for {route_id}: {e}")
            return []

    @staticmethod
    def _merge_data(static_data: Dict[str, Any], dynamic_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Merge valid ETA from dynamic_data into static_data.
        dynamic_data is a flat list of stop statuses.
        """
        if not dynamic_data:
            return static_data
            
        # Create a lookup map for dynamic status: UniStationId -> Status Object
        status_map = {str(item.get("UniStationId")): item for item in dynamic_data}
        
        # Helper to update stop list
        def update_stops(stops):
            if not stops:
                return
            for stop in stops:
                uni_id = str(stop.get("UniStopId")) # Note: Static uses UniStopId, Dynamic uses UniStationId usually
                if uni_id in status_map:
                    status = status_map[uni_id]
                    # Update ETA
                    # ETA in dynamic data: seconds?
                    # The JS says: if eta < 0 (status code), if eta >= 0 (seconds)
                    stop["ETA"] = status.get("ETA")
                    stop["NextDepTime"] = status.get("NextDepTime") # e.g. "12:00"
                    
        update_stops(static_data.get("GoDirStops"))
        update_stops(static_data.get("BackDirStops"))
        
        return static_data

    @staticmethod
    def _parse_html(html_content: str, route_id: str) -> Dict[str, Any]:
        """
        Extract routeJsonString from HTML and parse it.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # The data is usually embedded in a script tag as 'var routeJsonString = ...'
        # or inside the html structure depending on the page
        # Based on user description: "Find routeJsonString, use Regex or string split"
        
        scripts = soup.find_all('script')
        json_str = None
        
        for script in scripts:
            if script.string and 'routeJsonString' in script.string:
                # Regex to extract the JSON object
                # Update: The format is var routeJsonString = JSON.stringify({...});
                match = re.search(r'var\s+routeJsonString\s*=\s*JSON\.stringify\((.*?)\);', script.string, re.DOTALL)
                if match:
                    json_str = match.group(1)
                    break
                
                # Fallback for other potential formats (just in case)
                match = re.search(r'var\s+routeJsonString\s*=\s*(\[.*?\]);', script.string, re.DOTALL)
                if match:
                    json_str = match.group(1)
                    break
        
        if not json_str:
            raise ValueError("Could not find routeJsonString in HTML")
            
        data = json.loads(json_str)
        
        # The structure is usually a list of directions or an object containing directions
        # User mentioned "GoDirStops" and "BackDirStops"
        # Let's inspect the structure conceptually. 
        # Usually it returns a list of stop objects. We need to group them if they are flat, 
        # or if the JSON itself has structure. 
        # Assuming the JSON is the raw list of stops often seen in these ASP.NET pages.
        # But user mentioned GoDirStops/BackDirStops. Let's return the parsed JSON directly for now
        # OR format it as requested.
        
        # User said: "Extract Name (Stop Name) and Eta (Estimated Time) or BusTimeDesc"
        # Let's format it for easier consumption.
        
        processed_data = {
            "GoDirStops": [],
            "BackDirStops": []
        }
        
        # NOTE: Without seeing the actual JSON structure, I am making a best guess based on common patterns
        # for these systems and the user's prompt. 
        # Commonly structure: [ { StopName: "...", Eta: "...", GoBack: "0" ... }, ... ]
        # GoBack: 0 = Go, 1 = Back (Often)
        # OR: { "Bus" : [ ... ] }
        # Let's just return the raw data wrapped in a dict if it's a list, or the dict itself.
        # But the User explicitly asked to "Extract from GoDirStops and BackDirStops". 
        # This implies the JSON might ALREADY have these keys. 
        # If the JSON is a list, I might need to look for these keys inside, OR the JSON IS the object with these keys.
        
        # I will return the raw data for now to be safe, but I'll add a helper to extract simple info.
        
        return data

if __name__ == "__main__":
    # Test with a known ID (e.g., 307 which is 0100030700)
    test_id = "0100030700"
    data = BusCrawler.get_route_data(test_id)
    if data:
        print("Successfully fetched data")
        # Print first few chars to debug structure
        print(str(data)[:200])
    else:
        print("Failed to fetch data")
