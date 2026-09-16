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


清理问题上限 = 32
清理问题: list[str] = []
_清理问题丢弃数 = 0


def _记录清理问题(文本: str) -> None:
    """登记一条进程回收失败留痕（有界：超上限只累加丢弃计数，不无界增长）。

    长驻进程里 `清理问题` 是模块级列表，若只 append 会随每次回收失败无限膨胀；
    保留最近 上限 条即够定位，超出的只记数量——不静默丢，丢了多少读得到。
    """
    global _清理问题丢弃数
    if len(清理问题) >= 清理问题上限:
        _清理问题丢弃数 += 1
        return
    清理问题.append(文本)


def 取清理问题() -> dict[str, Any]:
    """读取进程回收失败留痕（有界快照）：{问题, 丢弃数, 上限}。

    这是 `清理问题` 的**读取方**：有界执行 在超时回收路径上把它挂进返回信封
    （`进程回收留痕`），调用方与诊断入口据此判断「子进程是否真被回收」，
    而不是只看一个「超时」错误码。
    """
    return {"问题": list(清理问题), "丢弃数": _清理问题丢弃数, "上限": 清理问题上限}


def _附回收留痕(信封: dict[str, Any], 留痕: list[str]) -> dict[str, Any]:
    """本次调用有回收失败留痕时挂进信封：问题清单 + 有界累计快照（无留痕不动形状）。"""
    if 留痕:
        信封["进程回收留痕"] = 取清理问题()
    return 信封


def _回收(进程: subprocess.Popen) -> list[str]:
    """回收子进程：终止失败必须留痕（哲学第 3 条 2 项），但不阻塞上层错误上报。

    平台分叉（POSIX 进程组强杀 / 非 POSIX terminate）已删除：终止与存活判定全部
    收口在 公共契约.运行时.进程终止，本处不做任何平台判断。
    返回本次回收的失败留痕（空表 = 回收成功），供调用方随信封读到。
    """
    留痕: list[str] = []
    终止 = 进程终止.强制结束子进程(进程, 宽限秒=1.0, 等待秒=2.0)
    if not 终止.成功:
        留痕.append(f"进程回收失败（进程可能残留）: {终止.错误说明}")
        _记录清理问题(留痕[0])
    with contextlib.suppress(Exception):
        进程.communicate(timeout=1.0)
    return 留痕


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
        留痕 = _回收(进程)
        return _附回收留痕(
            {"成功": False, "错误码": "超时", "错误说明": f"外部命令超过 {超时秒} 秒"}, 留痕)
    输出 = _截断(输出 or "", 输出上限)
    错误 = _截断(错误 or "", min(65536, max(2000, 输出上限 // 4)))
    if 进程.returncode != 0:
        return {"成功": False, "错误码": "Provider执行失败", "错误说明": 错误 or f"退出码 {进程.returncode}", "输出": 输出}
    return {"成功": True, "退出码": 0, "输出": 输出, "错误输出": 错误}
