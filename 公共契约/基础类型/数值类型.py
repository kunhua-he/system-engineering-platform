"""四类数值基础类型的冻结契约与严格校验。

数值类型不做隐式转换：整数只接受 ``int``，浮点只接受 ``float``；
布尔值属于独立的逻辑型，不能因为 Python 的继承关系混入整数型。
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假


@dataclass(frozen=True)
class 数值类型:
    """数值类型的公开边界。"""

    名称: str
    位数: int
    最小值: int | float
    最大值: int | float


数值类型定义: dict[str, 数值类型] = {
    "整数型": 数值类型("整数型", 64, -(2**63), 2**63 - 1),
    "长整数型": 数值类型("长整数型", 128, -(2**127), 2**127 - 1),
    "单精度数型": 数值类型("单精度数型", 32, -3.4028234663852886e38, 3.4028234663852886e38),
    "双精度数型": 数值类型("双精度数型", 64, -1.7976931348623157e308, 1.7976931348623157e308),
}


def 校验数值类型(值: Any, 类型名: str) -> bool:
    """严格校验值是否符合冻结的数值类型；类型名非法时抛 ``ValueError``。"""

    定义 = 数值类型定义.get(类型名)
    if 定义 is None:
        raise ValueError(f"未知数值类型：{类型名}")
    if 类型名 in {"整数型", "长整数型"}:
        return (
            isinstance(值, int)
            and not isinstance(值, bool)
            and 定义.最小值 <= 值 <= 定义.最大值
        )
    # 浮点类型**接受 int**：JSON 只有一种数值类型，`120` 与 `120.0` 都是合法 JSON 数字，
    # 落到 Python 侧是 int 还是 float 由传输层决定。把「必须带小数点」当契约要求，等于让
    # 传输细节泄漏成调用方的错 —— 实测踩过：`执行命令` 的 `超时秒` 传 120 被拒、传 120.0 才过，
    # Agent 因此连错 3 次、白付三轮往返（2026-09-21）。int→double 无损，故放行；
    # bool 必须显式排除（Python 里 bool 是 int 子类，`True` 不该被当成 1）。
    if isinstance(值, bool) or not isinstance(值, (int, float)):
        return 假
    if not math.isfinite(值):
        return 假
    if 类型名 == "单精度数型":
        try:
            # struct 使用 IEEE 754 binary32，并可捕获超出单精度范围的值。
            struct.pack(">f", 值)
        except (OverflowError, struct.error):
            return 假
    return 定义.最小值 <= 值 <= 定义.最大值


def 确保数值类型(值: Any, 类型名: str) -> int | float:
    """校验数值类型，不符合时抛出稳定的 ``TypeError``/``ValueError``。"""

    if 类型名 not in 数值类型定义:
        raise ValueError(f"未知数值类型：{类型名}")
    if not 校验数值类型(值, 类型名):
        raise TypeError(f"值不符合{类型名}契约")
    return 值


__all__ = ["数值类型", "数值类型定义", "校验数值类型", "确保数值类型"]
