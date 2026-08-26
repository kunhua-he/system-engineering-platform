"""无第三方依赖的确定性类型转换。"""
from __future__ import annotations

import math
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

def _文本(值: Any) -> 结果[str]:
    if not isinstance(值, str):
        return 结果.失败("参数不合法", "值必须是文本型")
    return 结果.成功结果(值.strip())

def 文本转整数(文本: str, 进制: int = 10) -> 结果[int]:
    try:
        值 = _文本(文本)
        if not 值.成功 or not 2 <= 进制 <= 36 or not 值.值:
            return 结果.失败("参数不合法", "文本或进制不合法")
        return 结果.成功结果(int(值.值, 进制))
    except ValueError:
        return 结果.失败("类型转换失败", "文本不是整数")
    except (OverflowError, TypeError):
        return 结果.失败("数值溢出", "整数超出范围")

def 文本转长整数(文本: str, 进制: int = 10) -> 结果[int]:
    return 文本转整数(文本, 进制)

def 整数转文本(整数: int) -> 结果[str]:
    if isinstance(整数, bool) or not isinstance(整数, int):
        return 结果.失败("参数不合法", "值必须是整数型")
    return 结果.成功结果(str(整数))

def 长整数转文本(长整数: int) -> 结果[str]:
    return 整数转文本(长整数)

def _浮点(文本: str, 单精度: bool = False) -> 结果[float]:
    try:
        值 = _文本(文本)
        if not 值.成功 or not 值.值:
            return 结果.失败("参数不合法", "文本不能为空")
        数值 = float(值.值)
        if not math.isfinite(数值):
            return 结果.失败("类型转换失败", "不接受 NaN 或无穷")
        if 单精度 and abs(数值) > 3.4028235e38:
            return 结果.失败("数值溢出", "单精度数超出范围")
        return 结果.成功结果(数值)
    except (ValueError, TypeError):
        return 结果.失败("类型转换失败", "文本不是数值")

def 文本转单精度数(文本: str) -> 结果[float]:
    return _浮点(文本, True)

def 文本转双精度数(文本: str) -> 结果[float]:
    return _浮点(文本)

def 数值转文本(数值: int | float, 小数位数: int | None = None) -> 结果[str]:
    if isinstance(数值, bool) or not isinstance(数值, (int, float)):
        return 结果.失败("参数不合法", "值必须是数值型")
    if isinstance(数值, float) and not math.isfinite(数值):
        return 结果.失败("类型转换失败", "不接受 NaN 或无穷")
    if 小数位数 is None:
        return 结果.成功结果(str(数值))
    if isinstance(小数位数, bool) or not isinstance(小数位数, int) or not 0 <= 小数位数 <= 15:
        return 结果.失败("参数不合法", "小数位数必须为 0 到 15 的整数")
    return 结果.成功结果(f"{数值:.{小数位数}f}")

def 逻辑转文本(逻辑值: bool) -> 结果[str]:
    if not isinstance(逻辑值, bool):
        return 结果.失败("参数不合法", "值必须是逻辑型")
    return 结果.成功结果("真" if 逻辑值 else "假")

def 文本转逻辑(文本: str) -> 结果[bool]:
    值 = _文本(文本)
    if not 值.成功:
        return 结果.失败("参数不合法", "值必须是文本型")
    if 值.值 in ("真", "true", "True", "1"):
        return 结果.成功结果(True)
    if 值.值 in ("假", "false", "False", "0"):
        return 结果.成功结果(False)
    return 结果.失败("类型转换失败", "文本不是逻辑型")

def 校验类型(值: Any, 目标类型: str) -> 结果[bool]:
    类型表 = {"逻辑型": bool, "整数型": int, "长整数型": int,
              "单精度数型": float, "双精度数型": float, "文本型": str,
              "列表型": list, "字典型": dict}
    类型 = 类型表.get(目标类型)
    if 类型 is None:
        return 结果.失败("参数不合法", "未知目标类型")
    有效 = isinstance(值, 类型) and not (类型 is int and isinstance(值, bool))
    return 结果.成功结果(有效)
