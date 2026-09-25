"""Codex/macOS MCP 启动兼容入口。

MCP 握手发生在能力网关之前，不能靠网关能力自举凭证。启动时优先使用
已有环境变量；桌面客户端未继承 shell 环境时，再从本机受管 LaunchAgent
读取凭证并注入薄壳。找不到凭证则 fail-closed，不打印凭证。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 项目根入 sys.path：本文件是 MCP 启动入口，由桌面客户端按绝对路径拉起，
# sys.path[0] 是薄壳目录而不是项目根（与 `薄壳服务.py` 同一条坑）。
_项目根 = Path(__file__).resolve().parents[2]
if str(_项目根) not in sys.path:
    sys.path.insert(0, str(_项目根))

from 开发工具.薄壳.网关凭证 import 环境变量别名, 凭证键, 凭证缺失, 取网关凭证  # noqa: E402

薄壳文件 = Path(__file__).with_name("薄壳服务.py")


def 读取凭证() -> str:
    # 凭证取用走唯一腿 `开发工具/薄壳/网关凭证.py`：回退顺序=("环境变量", "plist") ——
    # MCP 握手在网关之前，桌面客户端可能没继承 shell 环境，故先 env 再落 plist 兜底（原有口径）。
    try:
        return 取网关凭证(回退顺序=("环境变量", "plist"), 环境变量别名=环境变量别名)
    except 凭证缺失:
        return ""


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
