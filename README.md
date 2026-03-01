# 台北公車 AI 路線規劃助手 (Taipei Bus AI - v3)

這是一個基於 Python 的 AI 代理程式，專為導航台北複雜的公車路網而設計。它結合了 **TDX 交通部運輸資料流通服務** 的即時數據，並採用客製化的 **Greedy Hop (貪婪跳躍) & Recursive Bridging (遞迴橋接)** 演算法，即使是難以到達、需要多次轉乘的目的地，也能找出高效的乘車方案。

## 🚀 核心功能

- **即時與靜態數據混合**：結合靜態路線圖 (用於連通性分析) 與即時預估到站時間 (ETA)，做出最準確的決策。
- **Greedy Hop 演算法 (v3)**：
    - **優先級 1：直達路線**。如果有直達車，絕對優先推薦。
    - **優先級 2：貪婪跳躍 (1次轉乘)**。尋找最快能到達「轉乘樞紐」的公車，並指示使用者在樞紐「抵達後再詢問」。這模擬了在地人的直覺：「先上車，到了再說！」。
    - **優先級 3：遞迴橋接 (>1次轉乘)**。針對深層路網連通性問題，自動尋找能連接起始區與目的區的「橋接路線」，引導使用者前往這段多程旅途的第一個轉乘點。
- **安全轉乘檢查**：在推薦轉乘方案時，自動檢查目標路線的班次頻率與時刻表，對低頻路線發出警告。
- **MCP Server 整合**：設計為可供 AI 助理 (如 Claude, Cursor 等) 呼叫的工具。

## 🛠️ 安裝教學

1. 複製 (Clone) 此儲存庫。
2. 安裝相依套件：
   ```bash
   pip install -r requirements.txt
   ```
3. 設定環境變數 `.env` (請參考 `.env.example`)：
   ```
   TDX_CLIENT_ID=你的_client_id
   TDX_CLIENT_SECRET=你的_client_secret
   ```
4. 初始化靜態資料（首次使用）：
   ```bash
   python scripts/init_static_data.py
   python scripts/build_network_graph.py
   ```

## 🏗️ 專案結構

- `src/`
    - `mcp_server.py`: 主要進入點。定義了 `plan_trip` (規劃路線) 與 `get_bus_arrival_time` (查詢到站) 工具。
    - `graph_engine.py`: 核心路徑搜尋邏輯 (Greedy Hop 實作)。
    - `tdx_client.py`: 處理 TDX API 認證與資料抓取。
    - `crawler_core.py`: TDX API 資料轉接器 (Adapter)。
    - `cache_manager.py`: 即時數據快取管理 (TTL=60秒)。
- `config/`
    - `settings.py`: 全域設定常數。
- `data/static/bus_graph.json`: 預先建立的雙北公車路網圖。
- `scripts/`
    - `init_static_data.py`: 從 TDX API 取得路線列表。
    - `build_network_graph.py`: 建立靜態路網圖。
    - `test_tdx_connection.py`: TDX API 連線測試。
    - `run_server.bat`: 啟動 MCP Server。
- `tests/`
    - `test_graph_engine.py`: GraphEngine 與 CacheManager 單元測試。

## 📝 演算法邏輯

**為什麼使用 Greedy Hop (貪婪跳躍)?**
傳統的 BFS (廣度優先搜尋) 演算法在處理大型即時路網時往往會失敗，因為要準確預測「一小時後」在第二個轉乘點的公車動態是不可靠的。
我們的策略：
1. **專注於第一段 (Leg 1)**：找出 *現在* 最好的公車。
2. **引導至樞紐**：如果沒有直達車，將使用者帶往轉乘樞紐或橋接路線。
3. **遞迴詢問**：一旦抵達樞紐，再根據最新的即時數據重新評估。

這種方法能大幅提高路線的成功率，並為通勤者提供更務實的建議。

## 🧪 測試

```bash
python -m unittest tests.test_graph_engine -v
```

## ⚠️ 注意事項
- 系統會快取即時數據 60 秒，以遵守 API 速率限制。
- 如果轉乘公車的班次頻率較低，系統會發出「安全轉乘」警告。
