import os
import time
import requests
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TDXClient:
    AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    API_BASE_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus"
    
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or os.getenv("TDX_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("TDX_CLIENT_SECRET")
        
        if not self.client_id or not self.client_secret:
            raise ValueError("TDX_CLIENT_ID and TDX_CLIENT_SECRET must be provided either in constructor or environment variables.")
            
        self.access_token = None
        self.token_expiry = 0

    def _get_auth_header(self) -> Dict[str, str]:
        """Get the Authorization header with a valid access token."""
        if self.access_token is None or time.time() >= self.token_expiry:
            self._authenticate()
        return {
            "authorization": f"Bearer {self.access_token}",
            "Accept-Encoding": "gzip" # Recommended by TDX
        }

    def _authenticate(self):
        """Obtain a new access token from TDX."""
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        try:
            response = requests.post(self.AUTH_URL, data=data)
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data.get("access_token")
            # Expires in seconds, subtract a buffer (e.g., 60s)
            expires_in = token_data.get("expires_in", 86400)
            self.token_expiry = time.time() + expires_in - 60
            logger.info("Successfully authenticated with TDX.")
        except requests.RequestException as e:
            logger.error(f"Authentication failed: {e}")
            if e.response:
                logger.error(f"Response: {e.response.text}")
            raise

    def get_routes(self, city: str = "Taipei") -> List[Dict[str, Any]]:
        """
        Fetch all bus routes for a specific city.
        API: /Route/City/{City}
        """
        url = f"{self.API_BASE_URL}/Route/City/{city}"
        params = {
            "$format": "JSON"
        }
        return self._make_request(url, params)

    def get_stops(self, route_name: str, city: str = "Taipei") -> List[Dict[str, Any]]:
        """
        Fetch stops for a specific route.
        API: /StopOfRoute/City/{City}/{RouteName}
        """
        # Note: TDX uses RouteName for this endpoint usually
        url = f"{self.API_BASE_URL}/StopOfRoute/City/{city}/{route_name}"
        params = {
            "$format": "JSON"
        }
        return self._make_request(url, params)

    def get_schedule(self, route_name: str, city: str = "Taipei") -> List[Dict[str, Any]]:
        """
        Fetch static schedule.
        API: /Schedule/City/{City}/{RouteName}
        """
        url = f"{self.API_BASE_URL}/Schedule/City/{city}/{route_name}"
        params = {
            "$format": "JSON"
        }
        return self._make_request(url, params)

    def get_route_frequency(self, route_name: str, city: str = "Taipei") -> List[Dict[str, Any]]:
        """
        Fetch route frequency/headway info.
        API: /Route/Frequency/City/{City}/{RouteName}
        """
        # Note: Base URL usually /Bus, but is it /Bus/Route/Frequency?
        # Actually it's just /Frequency/City... ? No, the V2 standard is /Bus/Route/Frequency?
        # Let's check docs or try /Route/Frequency or /Frequency/Route.
        # Based on common TDX patterns: /Route/Frequency/City/{City}/{RouteName} might be it.
        # Wait, the official docs say: /api/basic/v2/Bus/Route/Frequency/City/{City}/{RouteName}
        
        url = f"{self.API_BASE_URL}/Route/Frequency/City/{city}/{route_name}"
        params = {
            "$format": "JSON"
        }
        return self._make_request(url, params)

    def get_realtime_vehicle(self, route_name: Optional[str] = None, city: str = "Taipei") -> List[Dict[str, Any]]:
        """
        Fetch real-time vehicle positions (A1).
        If route_name is provided, filter by it.
        API: /RealTimeByFrequency/City/{City}/{RouteName}
        """
        if route_name:
            url = f"{self.API_BASE_URL}/RealTimeByFrequency/City/{city}/{route_name}"
        else:
            url = f"{self.API_BASE_URL}/RealTimeByFrequency/City/{city}"
            
        params = {
            "$format": "JSON"
        }
        return self._make_request(url, params)

    def _make_request(self, url: str, params: Dict[str, Any]) -> Any:
        try:
            headers = self._get_auth_header()
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            if e.response:
                # TDX sometimes returns detailed error messages in JSON
                try:
                    logger.error(f"TDX Error: {e.response.json()}")
                except:
                    logger.error(f"Response text: {e.response.text}")
            return []

if __name__ == "__main__":
    # Quick sanity check
    try:
        client = TDXClient()
        print("Authenticating...")
        client._authenticate()
        print("Authentication successful.")
        
        print("Fetching a test route (307)...")
        routes = client.get_routes(city="Taipei")
        # Filter for 307 just to see
        r307 = next((r for r in routes if r.get("RouteName", {}).get("Zh_tw") == "307"), None)
        if r307:
            print(f"Found 307: {r307.get('RouteName')}")
        else:
            print("307 not found in first batch (might be paged or huge list?)")
            
    except Exception as e:
        print(f"Test failed: {e}")
