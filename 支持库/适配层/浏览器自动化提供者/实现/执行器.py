"""浏览器自动化外部命令的有界执行器。"""

from __future__ import annotations

import contextlib
import subprocess
from typing import Any

from 公共契约.运行时 import 平台适配, 进程终止


def _截断(文本: str, 上限: int) -> str:
    if len(文本) <= 上限:
        return 文本
    前 = 上限 // 2
    后 = 上限 - 前
    return 文本[:前] + "\n...[中段省略]...\n" + 文本[-后:]


清理问题: list[str] = []


def _回收(进程: subprocess.Popen) -> None:
    """回收子进程：终止失败必须留痕（哲学第 3 条 2 项），但不阻塞上层错误上报。

    平台分叉（POSIX 进程组强杀 / 非 POSIX terminate）已删除：终止与存活判定全部
    收口在 公共契约.运行时.进程终止，本处不做任何平台判断。
    """
    终止 = 进程终止.强制结束子进程(进程, 宽限秒=1.0, 等待秒=2.0)
    if not 终止.成功:
        清理问题.append(f"进程回收失败（进程可能残留）: {终止.错误说明}")
    with contextlib.suppress(Exception):
        进程.communicate(timeout=1.0)


def 有界执行(
    命令: list[str], 代码: str = "", *, 环境: dict[str, str] | None = None,
    超时秒: float = 30.0, 输出上限: int = 262144,
) -> dict[str, Any]:
    """执行外部命令；超时终止进程组，输出首尾有界保留。"""
    if not 命令 or any(not isinstance(项, str) or not 项 for 项 in 命令):
        return {"成功": False, "错误码": "参数不合法", "错误说明": "外部命令不能为空"}
    try:
        进程 = subprocess.Popen(
            命令, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            env=环境, **平台适配.子进程组启动标志(),
        )
    except OSError as 错误:
        return {"成功": False, "错误码": "提供者不可用", "错误说明": str(错误)}
    try:
        输出, 错误 = 进程.communicate(代码, timeout=max(0.1, float(超时秒)))
    except subprocess.TimeoutExpired:
        _回收(进程)
        return {"成功": False, "错误码": "超时", "错误说明": f"外部命令超过 {超时秒} 秒"}
    输出 = _截断(输出 or "", 输出上限)
    错误 = _截断(错误 or "", min(65536, max(2000, 输出上限 // 4)))
    if 进程.returncode != 0:
        return {"成功": False, "错误码": "Provider执行失败", "错误说明": 错误 or f"退出码 {进程.returncode}", "输出": 输出}
    return {"成功": True, "退出码": 0, "输出": 输出, "错误输出": 错误}
