# TaipeiBusAI 全域設定

# === 圖搜尋 ===
# 每站估計行車時間 (分鐘)
TIME_PER_STOP = 2.5
# 無效距離 sentinel
INVALID_DISTANCE = 999
# 最大有效站距 (超過視為無效)
MAX_VALID_DISTANCE = 900

# === 快取 ===
# TTL (秒)
CACHE_TTL = 60
# 最大項目數
CACHE_MAXSIZE = 1500

# === TDX API ===
# 預設城市
DEFAULT_CITY = "Taipei"
# API 請求間隔 (秒, graph build 用)
API_DELAY_SECONDS = 3
# 最大重試次數
API_MAX_RETRIES = 3

# === 轉乘安全 ===
# 安全轉乘閾值 (分鐘)：低於此值的班距視為密集
SAFE_TRANSFER_HEADWAY_MINS = 20
# 無車輛時的預設等候時間 (分鐘)
DEFAULT_NO_BUS_WAIT = 60

# === 路徑搜尋 ===
# 並行 API fetch worker 數
MAX_PARALLEL_WORKERS = 5
# plan_trip 回傳候選數
TOP_K_RESULTS = 3

# === 方向後綴 ===
DIR_GO = "__go"
DIR_BACK = "__back"
