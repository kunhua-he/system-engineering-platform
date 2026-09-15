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
# M3 访问守卫：设置 环境变量 MCP工具箱_访问令牌 后，服务端强制校验 Authorization: Bearer <令牌>
# （客户端需同步加 header，否则 401）；未设置时仅回环 + Host/Origin 守卫生效，服务照常启动（向后兼容）。
# 设 MCP工具箱_要求令牌=1 可切换为 fail-closed：未设置令牌则拒绝启动。
# 注意：bash 既不允许 ${中文名:-默认}（bad substitution），也不允许中文变量名（会报 command not found），
# 因此这里用 ASCII 变量名承接值，用 printenv 按中文名读取（printenv 接受任意字面量名），并允许用 env 传入。
MCP_TOKEN="$(printenv 'MCP工具箱_访问令牌' || true)"
MCP_REQUIRE_TOKEN="$(printenv 'MCP工具箱_要求令牌' || true)"
if [ -z "${MCP_TOKEN}" ]; then
  if [ -n "${MCP_REQUIRE_TOKEN}" ]; then
    echo "错误: MCP工具箱_要求令牌 已开启，但未设置 环境变量 MCP工具箱_访问令牌（fail-closed 拒绝启动）。" >&2
    exit 1
  fi
  echo "警告: 未设置 环境变量 MCP工具箱_访问令牌 —— 当前仅由回环 + Host/Origin 守卫保护，本机任意进程仍可无凭证调用全部工具。"
fi
exec python3.14 -m MCP工具箱.项目服务 --http --端口 "${SERVICE_PORT}"
