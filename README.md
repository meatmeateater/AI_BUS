# 台北公車 AI 路線規劃助手 (Taipei Bus AI - v3)

基於 Python 的 AI 代理程式，專為導航台北/新北公車路網而設計。結合 **TDX 交通部運輸資料流通服務** 即時數據，採用 **Greedy Hop & Recursive Bridging** 演算法，找出高效乘車方案。

## 🚀 核心功能

- **即時 + 靜態混合策略**：預計算路網圖 (~7ms 搜尋) + 即時 ETA 查詢
- **方向感知路線** (v3)：去程 `__go` / 返程 `__back` 分離，避免反向誤判
- **智慧站名匹配**：
  - 台 ↔ 臺 自動互轉
  - 站點群組展開（「台北車站」→ 7 個子站合併搜尋 110 條路線）
  - 捷運前綴、站字尾自動補全（「西門」→「捷運西門站」）
  - GPS 座標消歧義
- **StopUID 精準比對**：ETA 匹配使用唯一站點 ID，非模糊站名
- **三層路徑搜尋**：
  1. **直達路線** — 最優先
  2. **貪婪跳躍 (1 次轉乘)** — 找最快到轉乘樞紐的車
  3. **遞迴橋接 (多次轉乘)** — 跨區深層連通
- **安全轉乘檢查**：自動查詢目標路線班距，對低頻路線發出警告
- **MCP Server 整合**：可供 AI 助理 (Claude, Cursor 等) 呼叫

## 📊 效能

| 指標 | 數值 |
|---|---|
| 圖載入時間 | ~256ms |
| 路徑搜尋延遲 | **5-9ms** |
| 站名匹配 | < 1ms |
| 記憶體佔用 | ~15MB |
| 站點數 | 5,159 |
| 方向性路線數 | 1,266 |

## 🛠️ 安裝

```bash
# 1. Clone
git clone https://github.com/meatmeateater/AI_BUS.git

# 2. 安裝套件
pip install -r requirements.txt

# 3. 設定 .env（參考 .env.example）
TDX_CLIENT_ID=你的_client_id
TDX_CLIENT_SECRET=你的_client_secret

# 4. 初始化靜態資料（首次使用，約 1-3 小時因 TDX rate limit）
python scripts/init_static_data.py
python scripts/build_network_graph.py
```

## 🏗️ 專案結構

```
src/
├── mcp_server.py      # MCP 工具端點 (plan_trip, get_bus_arrival_time)
├── graph_engine.py    # 路徑搜尋核心 (GraphEngine, Greedy Hop)
├── tdx_client.py      # TDX API 封裝 (OAuth2 + REST + 429 retry)
├── crawler_core.py    # TDX 資料轉接器
└── cache_manager.py   # TTL 記憶體快取 (60s)

config/
└── settings.py        # 全域常數

data/static/
├── routes_map.json    # 路線名稱對照表 (1,044 條)
└── bus_graph.json     # 路網圖 v3 (方向分離 + StopUID + GPS)

scripts/
├── init_static_data.py       # 取得路線列表
├── build_network_graph.py    # 建立路網圖
├── test_tdx_connection.py    # API 連線測試
└── run_server.bat            # 啟動 MCP Server

tests/
└── test_graph_engine.py      # 28 個單元測試
```

## 📝 演算法設計

傳統 BFS 在即時路網失敗率高（無法預測一小時後的車況）。本系統策略：

1. **專注第一段** — 找出 *現在* 最好的車
2. **引導至樞紐** — 帶到轉乘點（模擬在地人直覺：「先上車，到了再說」）
3. **遞迴重算** — 到轉乘點後根據最新即時資料再評估

**方向感知距離**：`e_idx - s_idx`（非 `abs()`），確保只推薦正向行駛路線。

## 🧪 測試

```bash
python -m unittest tests.test_graph_engine -v
```

## ⚠️ 注意

- 即時數據快取 60 秒（遵守 API 速率限制）
- 首次建圖需要數小時（TDX 免費帳號 rate limit）
- 系統自動處理 429 Rate Limit（exponential backoff, max 3 retries）
- 跨市路線自動嘗試 Taipei → NewTaipei fallback
