"""Codex/macOS MCP 启动兼容入口。

MCP 握手发生在能力网关之前，不能靠网关能力自举凭证。启动时优先使用
已有环境变量；桌面客户端未继承 shell 环境时，再从本机受管 LaunchAgent
读取凭证并注入薄壳。找不到凭证则 fail-closed，不打印凭证。
"""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

凭证键 = "系统库网关凭证"
LaunchAgent文件 = Path.home() / "Library" / "LaunchAgents" / "com.huashi.gateway-40007.plist"
薄壳文件 = Path(__file__).with_name("薄壳服务.py")


def 读取凭证() -> str:
    for 键 in (凭证键, "MCP_GATEWAY_TOKEN"):
        值 = os.environ.get(键, "").strip()
        if 值:
            return 值
    try:
        配置 = plistlib.loads(LaunchAgent文件.read_bytes())
        环境变量 = 配置.get("EnvironmentVariables", {})
        值 = 环境变量.get(凭证键, "")
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        return ""
    return 值.strip() if isinstance(值, str) else ""


def main() -> int:
    凭证 = 读取凭证()
    if not 凭证:
        print(f"环境变量 {凭证键} 未设置，且未找到受管 LaunchAgent 凭证", file=sys.stderr)
        return 78
    环境 = os.environ.copy()
    环境[凭证键] = 凭证
    环境.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.execve(sys.executable, [sys.executable, str(薄壳文件)], 环境)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
