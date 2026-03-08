# ===========================================================================
#  tdx_client.py — TDX (運輸資料流通服務平台) API 客戶端
#
#  負責與 TDX Open API v2 通訊，提供以下功能：
#    - OAuth2 認證（Client Credentials）
#    - 路線查詢、站序查詢、班表 / 班距查詢
#    - 即時到站時間 (ETA)、即時車輛位置
#    - 自動重試（429 限流 / 5xx 伺服器錯誤）
#
#  執行緒安全：token 刷新使用 double-check locking。
# ===========================================================================

import os
import time
import threading
import requests
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# 載入 .env 中的 TDX_CLIENT_ID / TDX_CLIENT_SECRET
load_dotenv()

logger = logging.getLogger(__name__)


class TDXClient:
    """
    TDX API 客戶端。

    使用方式:
        client = TDXClient()                         # 從 .env 讀取憑證
        stops = client.get_stops("307", city="Taipei") # 查詢 307 路線的站序

    認證:
        TDX 使用 OAuth2 Client Credentials Grant。
        Token 會自動快取，過期前 60 秒自動刷新。
    """

    # TDX 認證端點
    AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    # TDX 公車 API 基礎 URL
    API_BASE_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus"

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        """
        初始化 TDX 客戶端。

        Args:
            client_id: TDX Client ID（可選，預設從環境變數讀取）
            client_secret: TDX Client Secret（可選，預設從環境變數讀取）

        Raises:
            ValueError: 找不到 Client ID 或 Secret
        """
        self.client_id = client_id or os.getenv("TDX_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("TDX_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "TDX_CLIENT_ID and TDX_CLIENT_SECRET must be provided "
                "either in constructor or environment variables."
            )

        self.access_token = None   # 目前的 Bearer Token
        self.token_expiry = 0      # Token 過期 timestamp
        self._auth_lock = threading.Lock()  # 保護 token 刷新

    def _get_auth_header(self) -> Dict[str, str]:
        """
        取得帶有效 Bearer Token 的 HTTP Header（執行緒安全）。

        使用 double-check locking 避免多執行緒同時刷新 token：
        1. 先不加鎖檢查 → 大多數情況直接命中（快路徑）
        2. 過期才加鎖 → 加鎖後再檢查一次（避免重複刷新）
        """
        if self.access_token is None or time.time() >= self.token_expiry:
            with self._auth_lock:
                # 取得鎖後再檢查一次（可能已被其他執行緒刷新）
                if self.access_token is None or time.time() >= self.token_expiry:
                    self._authenticate()
        return {
            "authorization": f"Bearer {self.access_token}",
            "Accept-Encoding": "gzip"  # TDX 建議啟用 gzip 壓縮
        }

    def _authenticate(self):
        """
        向 TDX 請求新的 Access Token。

        使用 OAuth2 Client Credentials Grant。
        Token 有效期通常為 86400 秒 (24 小時)，
        我們提前 60 秒刷新以避免邊界情況。
        """
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
            # 提前 60 秒刷新，避免在剛好過期瞬間發送請求
            expires_in = token_data.get("expires_in", 86400)
            self.token_expiry = time.time() + expires_in - 60
            logger.info("Successfully authenticated with TDX.")
        except requests.RequestException as e:
            logger.error(f"Authentication failed: {e}")
            if e.response:
                logger.error(f"Response: {e.response.text}")
            raise

    # ====================================================================
    #  公車 API 端點封裝
    #  每個方法對應一個 TDX API 端點，回傳原始 JSON (list of dicts)
    # ====================================================================

    def get_routes(self, city: str = "Taipei") -> List[Dict[str, Any]]:
        """取得指定城市的所有公車路線。"""
        url = f"{self.API_BASE_URL}/Route/City/{city}"
        params = {"$format": "JSON"}
        return self._make_request(url, params)

    def get_stops(self, route_name: str, city: str = "Taipei") -> List[Dict[str, Any]]:
        """取得指定路線的站序（含站牌 UID、GPS 座標）。"""
        url = f"{self.API_BASE_URL}/StopOfRoute/City/{city}/{route_name}"
        params = {"$format": "JSON"}
        return self._make_request(url, params)

    def get_schedule(self, route_name: str, city: str = "Taipei") -> List[Dict[str, Any]]:
        """取得指定路線的靜態時刻表。"""
        url = f"{self.API_BASE_URL}/Schedule/City/{city}/{route_name}"
        params = {"$format": "JSON"}
        return self._make_request(url, params)

    def get_route_frequency(self, route_name: str, city: str = "Taipei") -> List[Dict[str, Any]]:
        """取得指定路線的班距資訊（最小/最大班距分鐘數）。"""
        url = f"{self.API_BASE_URL}/Route/Frequency/City/{city}/{route_name}"
        params = {"$format": "JSON"}
        return self._make_request(url, params)

    def get_estimated_arrival(self, route_name: str, city: str = "Taipei") -> List[Dict[str, Any]]:
        """
        取得指定路線的即時到站預估。

        回傳欄位:
            - StopUID: 站牌唯一識別碼
            - EstimateTime: 預估到站秒數 (可能為 null)
            - StopStatus: 0=正常, 1=尚未發車, 2=已過站, 3=末班車
            - NextBusTime: 下次發車 ISO 時間字串 (可能為 null)
        """
        url = f"{self.API_BASE_URL}/EstimatedTimeOfArrival/City/{city}/{route_name}"
        params = {"$format": "JSON"}
        return self._make_request(url, params)

    def get_realtime_vehicle(self, route_name: Optional[str] = None, city: str = "Taipei") -> List[Dict[str, Any]]:
        """
        取得即時車輛位置 (A1 資料)。

        Args:
            route_name: 指定路線名（None = 取得所有車輛）
        """
        if route_name:
            url = f"{self.API_BASE_URL}/RealTimeByFrequency/City/{city}/{route_name}"
        else:
            url = f"{self.API_BASE_URL}/RealTimeByFrequency/City/{city}"
        params = {"$format": "JSON"}
        return self._make_request(url, params)

    # ====================================================================
    #  底層 HTTP 請求（含自動重試）
    # ====================================================================

    def _make_request(self, url: str, params: Dict[str, Any], max_retries: int = 3) -> Any:
        """
        發送 GET 請求到 TDX API，自動處理：
        - 429 (Rate Limit): 指數退避重試 (2, 4, 8 秒)
        - 5xx (Server Error): 固定 2 秒重試
        - Token 過期: 自動刷新

        Args:
            url: API 端點完整 URL
            params: URL 查詢參數
            max_retries: 最大重試次數

        Returns:
            解析後的 JSON (通常是 list)，失敗時回傳空 list
        """
        for attempt in range(max_retries + 1):
            try:
                headers = self._get_auth_header()
                response = requests.get(url, headers=headers, params=params)

                # 429 限流 → 指數退避重試
                if response.status_code == 429:
                    if attempt < max_retries:
                        wait = 2 ** (attempt + 1)  # 2, 4, 8 秒
                        logger.warning(f"Rate limited (429). Retry {attempt+1}/{max_retries} in {wait}s...")
                        time.sleep(wait)
                        continue

                response.raise_for_status()
                return response.json()

            except requests.RequestException as e:
                logger.error(f"Request failed for {url}: {e}")
                if e.response is not None:
                    try:
                        logger.error(f"TDX Error: {e.response.json()}")
                    except Exception:
                        logger.error(f"Response text: {e.response.text}")

                # 5xx 伺服器錯誤 → 固定 2 秒重試
                if e.response is not None and e.response.status_code >= 500 and attempt < max_retries:
                    time.sleep(2)
                    continue

                return []
        return []


# ====================================================================
#  快速驗證腳本（直接執行此檔案時觸發）
# ====================================================================
if __name__ == "__main__":
    try:
        client = TDXClient()
        print("Authenticating...")
        client._authenticate()
        print("Authentication successful.")

        print("Fetching a test route (307)...")
        routes = client.get_routes(city="Taipei")
        r307 = next((r for r in routes if r.get("RouteName", {}).get("Zh_tw") == "307"), None)
        if r307:
            print(f"Found 307: {r307.get('RouteName')}")
        else:
            print("307 not found in first batch (might be paged or huge list?)")

    except Exception as e:
        print(f"Test failed: {e}")
