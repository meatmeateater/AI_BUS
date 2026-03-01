@echo off
cd /d "%~dp0\.."
echo Starting Taipei Bus AI MCP Server...
python -m src.mcp_server
pause
