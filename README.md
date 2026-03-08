# 🚌 TaipeiBusAI — 台北公車智慧導航 MCP Server

透過 [MCP (Model Context Protocol)](https://github.com/modelcontextprotocol/mcp) 提供公車路線規劃與即時到站查詢，供 AI 助理 (Claude / Gemini / GPT) 直接呼叫。

## ✨ 功能

| 功能 | 說明 |
|---|---|
| **路線規劃** | `plan_trip(start, end)` — 最多回傳 3 個方案 (直達 + 轉乘混合排名) |
| **到站查詢** | `get_bus_arrival_time(route, stop, dir)` — 即時 ETA + 狀態 |
| **站名模糊匹配** | 台↔臺 互轉、捷運前綴、括號子站展開 |
| **方向感知** | 去程 / 返程分開計算，不會搞混方向 |
| **StopUID 精確匹配** | 用唯一站牌 ID 避免同名站混淆 |
| **轉乘安全檢查** | 查班距 / 時刻表，評估轉乘是否來得及 |

## 🏗️ 架構

```
使用者 → AI 助理 → MCP Server (mcp_server.py)
                        ├── GraphEngine (離線路網圖, ~5ms)
                        ├── BusCrawler → TDXClient (即時 API, ~500ms)
                        └── CacheManager (TTLCache, 60s)
```

### 核心演算法：Greedy Hop & Recursive Bridging

1. **Priority 1 — 直達**: 起終點路線交集
2. **Priority 2 — 一次轉乘**: 找共同中繼站，貪心選最短 leg1
3. **Priority 3 — 橋接路線**: 找同時觸碰起點側和終點側的第三條路線
4. **混合排名**: 直達站數 > 12 時，同步搜轉乘一起排名

## 📊 效能

| 指標 | 數值 |
|---|---|
| 路線數 | 1,266 (含去程/返程) |
| 站點數 | 5,159 |
| 圖載入 | ~256ms |
| 路徑搜尋 | ~5-9ms |
| 站名匹配 | <1ms |
| 記憶體 | ~15MB |
| 測試 | 41 個 (28 graph_engine + 13 mcp_server) |

## 🚀 安裝

### 環境需求
- Python 3.10+
- TDX API 帳號 ([申請連結](https://tdx.transportdata.tw/))

### 步驟

```bash
# 1. Clone
git clone https://github.com/meatmeateater/AI_BUS.git
cd AI_BUS

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env，填入 TDX_CLIENT_ID 和 TDX_CLIENT_SECRET

# 4. 初始化路線資料
python scripts/init_static_data.py

# 5. 建構路網圖 (約 3-4 小時)
python scripts/build_network_graph.py

# 6. 啟動 MCP Server
python -m src.mcp_server
```

### MCP 設定 (Claude Desktop)

```json
{
  "mcpServers": {
    "taipei-bus": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/TaipeiBusAI"
    }
  }
}
```

## 📁 專案結構

```
TaipeiBusAI/
├── config/
│   ├── __init__.py
│   └── settings.py          # 全域常數 (TTL, 閾值, 方向後綴等)
├── src/
│   ├── __init__.py
│   ├── mcp_server.py         # MCP Tool Server 主入口
│   ├── graph_engine.py        # 離線路網圖引擎 (搜尋演算法)
│   ├── crawler_core.py        # TDX API 資料適配器
│   ├── cache_manager.py       # 執行緒安全的 TTL 快取
│   └── tdx_client.py          # TDX API HTTP 客戶端
├── scripts/
│   ├── init_static_data.py    # 初始化路線列表
│   └── build_network_graph.py # 建構離線路網圖
├── tests/
│   ├── test_graph_engine.py   # GraphEngine 28 個測試
│   └── test_mcp_server.py     # MCP Server 13 個測試
├── data/
│   └── static/
│       ├── routes_map.json    # 路線名稱對照表
│       └── bus_graph.json     # 離線路網圖 (v3)
├── requirements.txt
├── .env.example
└── README.md
```

## 🧪 測試

```bash
python -m unittest tests.test_graph_engine tests.test_mcp_server -v
```

## 📝 授權

MIT License
