"""分支名安全校验与建议命名（迁移自 V3 版本控制工作流 安全.py）。

规则为 git check-ref-format 的常用子集：非空、只含字母数字与 . _ / -、
首字符为字母数字、无 ".."、不以 / 或 . 或 .lock 结尾、无 "/."、不以 "-" 开头。
"""

from __future__ import annotations

import re

from 公共契约.基础类型.结果类型 import 结果

_分支名安全模式 = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_默认前缀 = "codex/local-sync"


def 校验分支名(分支名: str | None = None) -> 结果:
    """校验分支名是否安全。返回 {是否安全, 原因}（原因在安全时为空字符串）。"""
    if not isinstance(分支名, str) or not 分支名.strip():
        return 结果.成功结果({"是否安全": False, "原因": "分支名不能为空"})
    名 = 分支名.strip()
    原因 = ""
    if not _分支名安全模式.match(名):
        原因 = "包含不允许的字符（只允许字母、数字、. _ / -，且首字符须为字母或数字）"
    elif ".." in 名:
        原因 = "不允许包含连续两个点"
    elif 名.endswith("/") or 名.endswith(".") or 名.endswith(".lock"):
        原因 = "不允许以 / 或 . 或 .lock 结尾"
    elif "/." in 名:
        原因 = "不允许包含 /. 组合"
    elif 名.startswith("-"):
        原因 = "不允许以 - 开头"
    return 结果.成功结果({"是否安全": not 原因, "原因": 原因})


def 建议分支名(前缀: str | None = None, 时间戳: str | None = None) -> 结果:
    """按前缀生成建议分支名；前缀非法时回退默认值。

    时间戳 不传则取当前本地时间 %Y%m%d-%H%M%S；显式传入便于确定性测试。
    """
    from datetime import datetime

    实际前缀 = (前缀 or "").strip().strip("/") or _默认前缀
    试探 = 校验分支名(实际前缀 + "-probe")
    if not (试探.成功 and (试探.值 or {}).get("是否安全")):
        实际前缀 = _默认前缀
    时刻 = 时间戳 or datetime.now().strftime("%Y%m%d-%H%M%S")
    return 结果.成功结果({"分支名": f"{实际前缀}-{时刻}", "前缀": 实际前缀, "时间戳": 时刻})
