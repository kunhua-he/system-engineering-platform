"""`列表型` / `字典型` 的冻结契约与严格校验（**类型判定的唯一真源**）。

**为什么需要本模块**：两者收口前同样只有网关 `类型匹配表` 的私有 lambda
（`isinstance(值, list)` / `isinstance(值, dict)`），没有公共可复用层。现场实测
（2026-09-19）参数位声明：`列表型` **117** 处、`字典型` **124** 处——属高频类型。

**口径（与 `公共契约/基础类型/类型目录.md` 逐条一致）**：

- `列表型`：合法值只有 Python `list`（有序集合）。`tuple`／`set`／`str`／`dict`
  **不是**列表型——`str` 虽然可迭代，但它是文本型，不得混入；
- `字典型`：合法值只有 Python `dict`（字符串键到声明类型值的映射）。
  键必须是 `str`（JSON 对象键只能是字符串）——**非文本键判为不符合**，
  否则一个 `{1: "x"}` 能当字典型穿过边界，再被 JSON 序列化悄悄改成 `{"1": "x"}`，
  等于边界上静默改了值；
- 元素类型、键集合、最大数量都是**契约面声明**（`类型目录.md` 校验规则 4），
  **不在本模块硬判**——硬判会把契约口径搬进代码，两处又要分叉。

**相对安全（哲学第 9 条 9.5）**：本函数只保证「容器形状对」，**不**保证元素类型
逐个正确、**不**保证规模有界（有界由契约声明的上限与资源预算负责）。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假

__all__ = ["校验列表类型", "确保列表类型", "校验字典类型", "确保字典类型"]


def 校验列表类型(值: Any) -> bool:
    """严格校验值是否为 `列表型`：只接受 `list`。

    `tuple`／`set`／`frozenset`／`str`／`dict` 一律判为**不符合**
    （不做隐式转换：需要列表就显式转换，不靠校验器猜）。
    """
    return isinstance(值, list)


def 确保列表类型(值: Any) -> list:
    """校验并返回 `列表型`；不符合时抛稳定的 ``TypeError``。"""
    if not isinstance(值, list):
        raise TypeError(f"值不符合列表型契约：{值!r}（列表型只接受 list）")
    return 值


def 校验字典类型(值: Any) -> bool:
    """严格校验值是否为 `字典型`：只接受 `dict`，且键必须全为 `str`。

    键非文本（如 `{1: "x"}`）判为**不符合**：JSON 对象键只能是字符串，
    放行等于让边界在序列化时静默改写键。
    """
    if not isinstance(值, dict):
        return 假
    return all(isinstance(键, str) for 键 in 值)


def 确保字典类型(值: Any) -> dict:
    """校验并返回 `字典型`；不符合时抛稳定的 ``TypeError``。"""
    if not isinstance(值, dict):
        raise TypeError(f"值不符合字典型契约：{值!r}（字典型只接受 dict）")
    if not all(isinstance(键, str) for 键 in 值):
        raise TypeError(f"值不符合字典型契约：{值!r}（字典型键必须全为 str）")
    return 值
