"""
xiaozhi_bridge.py — 將 TaipeiBusAI MCP Server 接入小智 AI (xiaozhi.me)

架構：
  小智 AI (WSS) ←→ api.xiaozhi.me ←→ 本腳本 ←→ mcp_server.py (stdio subprocess)

使用：
  python scripts/xiaozhi_bridge.py

依賴：  pip install websockets
"""
import asyncio
import subprocess
import sys
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bridge] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

WSS_URL = (
    "wss://api.xiaozhi.me/mcp/?token="
    "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJ1c2VySWQiOjY5NTUyMCwiYWdlbnRJZCI6MTM0NzQyMywiZW5kcG9pbnRJZCI6ImFnZW50XzEz"
    "NDc0MjMiLCJwdXJwb3NlIjoibWNwLWVuZHBvaW50IiwiaWF0IjoxNzczNDAwMzcyLCJleHAiOjE4"
    "MDQ5NTc5NzJ9."
    "EJC_CI-PhkQH62XKPM-GAPi4ngcZeKVuhOcYvV4FwOiFtiVc8q_ZkvJTwBccXOpc7kP6IlplZ8u"
    "JdKi0dTm5gQ"
)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def run_bridge():
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

    # 背景記錄 stderr
    async def log_stderr():
        try:
            async for line in proc.stderr:
                logger.info(f"[mcp-err] {line.decode('utf-8', errors='replace').rstrip()}")
        except Exception:
            pass

    stderr_task = asyncio.create_task(log_stderr())

    logger.info("連接 xiaozhi.me WSS...")
    try:
        # websockets 11+ 用 connect(), 12+ 部分版本改 connect as contextmanager
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
    finally:
        stderr_task.cancel()
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        logger.info("已關閉。")


if __name__ == "__main__":
    asyncio.run(run_bridge())
