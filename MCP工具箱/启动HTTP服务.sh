#!/bin/bash
# 启动系统工程平台 MCP 的 HTTP(Streamable) 服务，供 opencode remote 接入。
# 用法: ./MCP工具箱/启动HTTP服务.sh [端口]
# 默认端口 8766（单一对外网关，无角色）。
set -euo pipefail
cd "$(dirname "$0")/.."
SERVICE_PORT="${1:-8766}"
mkdir -p 工程缓存
LOG_PATH="工程缓存/mcp_http_${SERVICE_PORT}.log"
echo "启动 MCP HTTP 服务: http://127.0.0.1:${SERVICE_PORT}/mcp/  (单一网关)"
echo "日志: ${LOG_PATH}"
PYTHONPATH=. \
  exec python3.14 MCP工具箱/项目服务.py --http --端口 "${SERVICE_PORT}"
