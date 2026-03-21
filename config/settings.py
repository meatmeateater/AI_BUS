# ===========================================================================
#  TaipeiBusAI 全域設定檔
#  所有 magic number / 常數集中管理於此，避免散佈在各模組中
# ===========================================================================

# === 圖搜尋 ===

# 每站估計行車時間 (分鐘)
# 這是靜態估算用的，實際會再結合即時 ETA 修正
TIME_PER_STOP = 2.5

# 無效距離哨兵值 (sentinel)
# 當兩站之間在某路線上不可達時，回傳此值
INVALID_DISTANCE = 999

# 最大有效站距
# 超過此站數的路段視為無效（避免繞圈路線產生的超長距離）
MAX_VALID_DISTANCE = 900

# === 快取 ===

# 即時資料快取 TTL (秒)
# TDX API 的到站預估約 30-60 秒更新一次，60 秒 TTL 是合理的平衡
CACHE_TTL = 60

# 快取最大項目數
# 台北 + 新北共約 1,266 條路線，1,500 可容納全部路線的即時資料
CACHE_MAXSIZE = 1500

# === TDX API ===

# 預設城市（也會 fallback 到 NewTaipei）
DEFAULT_CITY = "Taipei"

# 建圖時 API 請求間隔 (秒)，避免觸發 TDX 429 限流
API_DELAY_SECONDS = 3

# API 失敗時最大重試次數
API_MAX_RETRIES = 3

# === 轉乘安全 ===

# 安全轉乘閾值 (分鐘)
# 班距 ≤ 此值視為「班次密集」，轉乘風險低
SAFE_TRANSFER_HEADWAY_MINS = 20

# 查不到即時資料時，fallback 的等候懲罰 (分鐘)
DEFAULT_NO_BUS_WAIT = 60

# === 路徑搜尋 ===

# 並行 API fetch 的最大 worker 數
MAX_PARALLEL_WORKERS = 5

# plan_trip 回傳給使用者的最多方案數
TOP_K_RESULTS = 3

# === 方向後綴 ===
# 圖中的 route key 格式：「307__go」= 307 去程、「307__back」= 307 返程
DIR_GO = "__go"
DIR_BACK = "__back"

# === 直達 / 轉乘混合搜尋 ===

# 直達方案的站數 ≤ 此值時跳過轉乘搜尋（因為短途直達一定最快）
# 超過此值則同步搜尋轉乘方案，因為轉乘可能比繞遠路的直達更快
DIRECT_SKIP_THRESHOLD = 12

# === 步行半徑搜尋 ===

# 步行速度 (公尺/分鐘)，一般成人約 70-90m/min
WALK_SPEED_M_PER_MIN = 80

# 最大允許步行時間 (分鐘)
MAX_WALK_MINUTES = 5

# 最大搜尋半徑 (公尺) = WALK_SPEED × MAX_WALK_MINUTES
MAX_WALK_RADIUS_M = WALK_SPEED_M_PER_MIN * MAX_WALK_MINUTES  # 400m (5 分鐘)

