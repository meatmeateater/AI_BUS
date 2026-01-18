import requests
from bs4 import BeautifulSoup
import json
import os
import re

#設定檔案路徑
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'static')
ROUTES_MAP_FILE = os.path.join(DATA_DIR, 'routes_map.json')

EBUS_URL = "https://ebus.gov.taipei/ebus"

def fetch_routes():
    print(f"Fetching routes from {EBUS_URL}...")
    try:
        response = requests.get(EBUS_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 尋找所有帶有 javascript:go(...) 的連結
    # 格式範例: <a href="javascript:go('0100030700')">307</a>
    links = soup.find_all('a', href=re.compile(r"javascript:go\('(\d+)'\)"))
    
    routes_map = {}
    
    print(f"Found {len(links)} route links. Parsing...")
    
    for link in links:
        route_name = link.text.strip()
        href = link.get('href')
        
        # 提取 ID
        match = re.search(r"go\('(\d+)'\)", href)
        if match:
            route_id = match.group(1)
            routes_map[route_name] = route_id
            
    # 儲存結果
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    with open(ROUTES_MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump(routes_map, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully saved {len(routes_map)} routes to {ROUTES_MAP_FILE}")

if __name__ == "__main__":
    fetch_routes()
