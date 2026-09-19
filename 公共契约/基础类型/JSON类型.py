"""`JSON值型` 的冻结契约与严格校验（**类型判定的唯一真源**）。

**为什么需要本模块**：`JSON值型` 收口前只有网关私有 `_是JSON值`，没有公共可复用层。
现场实测（2026-09-19）：参数位声明 **16** 处。

**口径（与 `公共契约/基础类型/类型目录.md` 逐条一致）**：合法的 `JSON值型` 是
「对象／数组／数字／字符串／布尔／空 的任意组合」且**必须可 JSON 序列化**。
与 `任意型` 的区别正是**有校验**（`任意型` 无校验、不入正式类型表）。

判据实现：`json.dumps(..., allow_nan=False)` 能成功即合法。由此：

- `dict`／`list`／`str`／`int`／`float`／`bool`／`None` 合法；
- `float("nan")`／`float("inf")` **否定**——JSON 标准无法表达 NaN／Infinity
  （`allow_nan=False` 让 `json.dumps` 抛 `ValueError`）。放行它们等于让一个
  序列化必失败的值穿过边界，在更下游才炸；
- `bytes`／`set`／`datetime`／自定义对象一律**否定**（不可 JSON 序列化）；
- 含非文本键的 `dict`（如 `{1: "x"}`）**否定**——JSON 对象键只能是字符串，
  放行等于让边界在序列化时静默改写键。

**相对安全（哲学第 9 条 9.5）**：本函数只保证「可 JSON 序列化」，**不**保证
规模有界（深层嵌套／超大数组仍可序列化）。有界由契约声明的上限与资源预算负责。
"""

from __future__ import annotations

import json
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假

__all__ = ["校验JSON值类型", "确保JSON值类型"]


def 校验JSON值类型(值: Any) -> bool:
    """严格校验值是否为 `JSON值型`：可被 JSON 序列化（拒绝 NaN／Infinity／非文本键）。"""
    try:
        json.dumps(值, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return 假
    return 真


def 确保JSON值类型(值: Any) -> Any:
    """校验并返回 `JSON值型`；不符合时抛稳定的 ``TypeError``。"""
    if not 校验JSON值类型(值):
        raise TypeError(
            f"值不符合JSON值型契约：{值!r}"
            "（必须可 JSON 序列化：不接受 NaN／Infinity、bytes、set、非文本键）"
        )
    return 值
