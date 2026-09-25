"""网关凭证的唯一取用件：40007 网关凭证（键名 `系统库网关凭证`）的**唯一一条取用腿**。

收口背景（T1）：此前四处同名同义「取网关凭证」各写一遍，来源与回退顺序各异 ——
`运维脚本/热接入.py`、`开发工具/能力网关/重启网关.py`（plist 现读现注入）、
`开发工具/薄壳/启动Codex薄壳.py`（env→plist）、`开发工具/薄壳/网关转发.py`（只认 env）。
四处都只是「按某个顺序取同一个键」，属同一件事多套实现（哲学 1.2），故收成本件。

**回退顺序是有意差异，参数化保留、不抹平**（各自 docstring 已声明理由）：
- `("环境变量", "plist")` —— 启动Codex薄壳：MCP 握手在网关之前，桌面客户端可能没继承
  shell 环境，故先 env 再落 plist 兜底。
- `("环境变量",)` —— 网关转发（薄壳唯一转发腿）：薄壳在平台进程之外，只认调用方注入的环境。
- `("plist",)` —— 热接入 / 重启网关：独立脚本，现读现注入 launchd 里那份，不依赖调用方环境。

凭证只允许进请求头，**不打印、不落盘**（沿用四处的既有口径）。
"""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

#: 唯一的凭证键名（四处同名同义）。
凭证键 = "系统库网关凭证"
#: 兼容别名：仅「启动Codex薄壳」历史口径保留（桌面客户端可能注入 MCP_GATEWAY_TOKEN）。
环境变量别名 = (凭证键, "MCP_GATEWAY_TOKEN")
服务标签 = "com.huashi.gateway-40007"
LaunchAgent文件 = Path.home() / "Library" / "LaunchAgents" / f"{服务标签}.plist"


class 凭证缺失(RuntimeError):
    """plist 文件不存在或不可读（硬失败）。调用方自行决定 fail-closed 形态（SystemExit / 空串）。"""


def _从环境变量(别名: tuple[str, ...]) -> str:
    for 键 in 别名:
        值 = os.environ.get(键, "").strip()
        if 值:
            return 值
    return ""


def _从plist(路径: Path) -> str:
    if not 路径.is_file():
        raise 凭证缺失(f"找不到 LaunchAgent：{路径}")
    try:
        配置 = plistlib.loads(路径.read_bytes())
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as 错误:
        raise 凭证缺失(f"LaunchAgent 不可读：{路径}") from 错误
    值 = (配置.get("EnvironmentVariables") or {}).get(凭证键, "")
    return 值.strip() if isinstance(值, str) else ""


def 取网关凭证(
    回退顺序: tuple[str, ...] = ("环境变量", "plist"),
    环境变量别名: tuple[str, ...] = 环境变量别名,
    plist路径: Path = LaunchAgent文件,
) -> str:
    """按 `回退顺序` 取网关凭证；命中即返回，取到空值继续下一来源，全落空返回空串。

    `回退顺序` 是四处的**有意差异**（见模块 docstring），故参数化而非抹平。
    plist 文件不存在/不可读时抛 `凭证缺失`（硬失败，不静默降级成空串）——
    plist-only 的调用方据此转 `SystemExit`，env 优先的调用方据此转空串。
    """
    for 来源 in 回退顺序:
        if 来源 == "环境变量":
            值 = _从环境变量(环境变量别名)
        elif 来源 == "plist":
            值 = _从plist(plist路径)
        else:
            raise ValueError(f"未知凭证来源：{来源}")
        if 值:
            return 值
    return ""
