"""
xiaozhi_bridge.py — 將 TaipeiBusAI MCP Server 接入小智 AI (xiaozhi.me)

架構：
  小智 AI (WSS) ←→ api.xiaozhi.me ←→ 本腳本 ←→ mcp_server.py (stdio subprocess)

使用：
  python scripts/xiaozhi_bridge.py

依賴：  pip install websockets
"""
import asyncio
import sys
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bridge] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# 從環境變數讀取 — 絕對不要把 Token 硬寫在程式碼裡
_token = os.getenv("XIAOZHI_TOKEN")
if not _token:
    logger.error("缺少 XIAOZHI_TOKEN 環境變數，請在 .env 中設定後重試。")
    sys.exit(1)

WSS_URL = f"wss://api.xiaozhi.me/mcp/?token={_token}"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _run_bridge_once():
    """單次橋接嘗試（失敗由外層 run_bridge 重連）。"""
    try:
        import websockets
    except ImportError:
        logger.error("請先安裝: python -m pip install websockets")
        sys.exit(1)

    logger.info("啟動 MCP Server subprocess...")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "src.mcp_server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=BASE_DIR
    )
    logger.info(f"MCP Server PID: {proc.pid}")

    async def log_stderr():
        try:
            async for line in proc.stderr:
                logger.info(f"[mcp-err] {line.decode('utf-8', errors='replace').rstrip()}")
        except Exception:
            pass

    stderr_task = asyncio.create_task(log_stderr())

    logger.info("連接 xiaozhi.me WSS...")
    try:
        async with websockets.connect(
            WSS_URL,
            ping_interval=30,
            subprotocols=["mcp"]
        ) as ws:
            logger.info("✅ 成功連接 xiaozhi.me！等待小智 AI 呼叫工具...")

            async def wss_to_mcp():
                """接收 WSS 訊息 → 寫入 mcp_server stdin"""
                async for msg in ws:
                    text = msg if isinstance(msg, str) else msg.decode()
                    logger.info(f"← [WSS -> MCP]: {text[:500]}")
                    if not text.endswith("\n"):
                        text += "\n"
                    proc.stdin.write(text.encode())
                    await proc.stdin.drain()

            async def mcp_to_wss():
                """讀取 mcp_server stdout → 送往 WSS"""
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        logger.warning("MCP Server stdout closed")
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    if text:
                        logger.info(f"→ [MCP -> WSS]: {text[:500]}")
                        await ws.send(text)

            done, pending = await asyncio.wait(
                [asyncio.create_task(wss_to_mcp()),
                 asyncio.create_task(mcp_to_wss())],
                return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()

    except Exception as e:
        logger.error(f"橋接錯誤: {e}", exc_info=True)
        raise  # 讓外層重連機制知道已斷線
    finally:
        stderr_task.cancel()
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        logger.info("子程序已關閉。")


async def run_bridge():
    """帶自動重連的主迴圈（M-4 修復）。"""
    RECONNECT_DELAY = 5  # 秒
    while True:
        try:
            await _run_bridge_once()
        except SystemExit:
            raise  # 致命錯誤（如缺少金鑰）不重連
        except Exception as e:
            logger.error(f"連線中斷: {e}，{RECONNECT_DELAY} 秒後重連...")
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    asyncio.run(run_bridge())
