"""
init_static_data.py — 使用 TDX API 取得所有公車路線列表，產生 routes_map.json
取代舊版 HTML 爬蟲 (ebus.gov.taipei)。
"""
import os
import sys
import json
import logging

# Setup paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from src.tdx_client import TDXClient

# Config
DATA_DIR = os.path.join(BASE_DIR, 'data', 'static')
ROUTES_MAP_FILE = os.path.join(DATA_DIR, 'routes_map.json')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def fetch_routes():
    """
    從 TDX API 取得台北市 + 新北市所有公車路線，組成 routes_map。
    格式: { "307": "307", "復興幹線": "復興幹線", ... }
    （TDX 的查詢 key 就是 RouteName，不需要另外的 ID）
    """
    logger.info("Initializing TDX Client...")
    try:
        client = TDXClient()
    except Exception as e:
        logger.error(f"Failed to initialize TDX: {e}")
        return

    routes_map = {}

    for city in ["Taipei", "NewTaipei"]:
        logger.info(f"Fetching routes for {city}...")
        try:
            routes = client.get_routes(city=city)
            for r in routes:
                name_obj = r.get("RouteName", {})
                route_name = name_obj.get("Zh_tw", "")
                if route_name and route_name not in routes_map:
                    # 使用 RouteName 作為 key 和 value（TDX 的端點用 RouteName 查詢）
                    routes_map[route_name] = route_name
            logger.info(f"  Found {len(routes)} routes in {city}.")
        except Exception as e:
            logger.error(f"Failed to fetch routes for {city}: {e}")

    # 儲存結果
    os.makedirs(DATA_DIR, exist_ok=True)
    
    with open(ROUTES_MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump(routes_map, f, ensure_ascii=False, indent=2)
        
    logger.info(f"Successfully saved {len(routes_map)} routes to {ROUTES_MAP_FILE}")


if __name__ == "__main__":
    fetch_routes()
