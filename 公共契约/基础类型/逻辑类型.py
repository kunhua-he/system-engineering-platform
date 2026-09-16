"""逻辑型基础类型的冻结契约与严格校验。

逻辑型只有两个合法值：``真`` 与 ``假``（见 类型目录.md：真／假，禁止用 0/1 文本替代）。

**正式代码一律从本模块取 ``真``／``假``**，不要在实现里散写 Python 字面量
``True``／``False`` —— 那是"英文漂移"的起点；两者在 Python 里是同一个对象，
本模块只提供中文口径与严格校验。

三层口径（唯一）：
- 文档／说明书：写 ``真``／``假``（人读）；
- 正式代码：``from 公共契约.基础类型.逻辑类型 import 真, 假``；
- JSON 契约与 HTTP 传输：JSON 标准 ``true``／``false``（JSON 无法表达中文），
  进出边界一律经 转JSON值／由JSON值 显式对应，不做隐式转换。
"""

from __future__ import annotations

from typing import Any

真 = True
假 = False

逻辑型取值 = (真, 假)


def 校验逻辑类型(值: Any) -> bool:
    """严格校验值是否为逻辑型：只接受 ``bool``。

    ``1``／``0``、``"真"``／``"假"``、``"true"``／``"false"`` 一律判为不符合
    （布尔不得因 Python 的继承关系混入整数型，反之亦然）。
    """
    return isinstance(值, bool)


def 确保逻辑类型(值: Any) -> bool:
    """校验并返回逻辑型；不符合时抛稳定的 ``TypeError``。"""
    if not isinstance(值, bool):
        raise TypeError(f"值不符合逻辑型契约：{值!r}（逻辑型只接受 真／假）")
    return 值


def 转JSON值(值: bool) -> bool:
    """逻辑型 → JSON 值（真→true、假→false），不合法即抛错。"""
    return 确保逻辑类型(值)


def 由JSON值(值: Any) -> bool:
    """JSON 值 → 逻辑型（只接受 JSON 的 true／false；其他一律 ``TypeError``）。"""
    if not isinstance(值, bool):
        raise TypeError(f"JSON 值不是逻辑型：{值!r}（合法形态只有 true／false）")
    return 值


__all__ = ["真", "假", "逻辑型取值", "校验逻辑类型", "确保逻辑类型", "转JSON值", "由JSON值"]
