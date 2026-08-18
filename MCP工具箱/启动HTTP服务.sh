#!/bin/bash
# 启动系统工程平台 MCP 的 HTTP(Streamable) 服务，供 opencode remote 接入。
# 用法: ./MCP工具箱/启动HTTP服务.sh [端口] [角色]
# 默认端口 8766，角色 平台维护者（其他可选：核心开发者 / 调用者 / 发布者 等）。
set -euo pipefail
cd "$(dirname "$0")/.."
端口="${1:-8766}"
角色="${2:-平台维护者}"
mkdir -p 工程缓存
日志="工程缓存/mcp_http_${端口}.log"
echo "启动 MCP HTTP 服务: http://127.0.0.1:${端口}/mcp/  (角色: ${角色})"
echo "日志: ${日志}"
SYSTEM_ENGINEERING_MCP_ROLE="${角色}" PYTHONPATH=. \
  exec python3.14 MCP工具箱/项目服务.py --http --端口 "${端口}"
