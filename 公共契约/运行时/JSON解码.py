"""冻结字节集 JSON 解码：全平台唯一实现（带深度与节点预算）。

按哲学第 8 条唯一性判定②：同一件事两种语义 → 同一份实现 + 模式变量。
    · 模式「严格」：非法字节集一律拒绝（网关**入站**，请求非法就报错）
    · 模式「宽松」：非法字节集原样保留（连接器**接收回包**，容错优先）

有界（第 9 条 5 项 / 资源有界铁律）：递归深度与节点总数都设预算，超限统一抛
ValueError（调用方按非法请求收口），并兜住 RecursionError —— 深度攻击不再逃逸。
"""

from __future__ import annotations

import base64
from typing import Any

默认最大深度 = 32
默认最大节点数 = 200_000
模式表 = ("严格", "宽松")


def 解码冻结值(
    值: Any,
    *,
    模式: str = "严格",
    最大深度: int = 默认最大深度,
    最大节点数: int = 默认最大节点数,
) -> Any:
    """还原字节集 JSON 表示；深度/节点超预算即 ValueError。"""
    if 模式 not in 模式表:
        raise ValueError(f"未知模式: {模式}")
    if 最大深度 < 1 or 最大节点数 < 1:
        raise ValueError("最大深度与最大节点数必须大于零")

    已用节点 = [0]

    def 递归(节点: Any, 深度: int) -> Any:
        if 深度 > 最大深度:
            raise ValueError(f"JSON 嵌套超过最大深度 {最大深度}")
        已用节点[0] += 1
        if 已用节点[0] > 最大节点数:
            raise ValueError(f"JSON 节点数超过预算 {最大节点数}")
        if isinstance(节点, dict):
            if 节点.get("类型") == "字节集型":
                编码 = 节点.get("base64")
                if not isinstance(编码, str):
                    if 模式 == "严格":
                        raise ValueError("字节集型缺少合法 base64")
                    return 节点
                try:
                    return base64.b64decode(编码, validate=True)
                except (ValueError, TypeError):
                    if 模式 == "严格":
                        raise ValueError("字节集型 base64 不合法")
                    return 节点
            return {键: 递归(子值, 深度 + 1) for 键, 子值 in 节点.items()}
        if isinstance(节点, list):
            return [递归(子值, 深度 + 1) for 子值 in 节点]
        return 节点

    try:
        return 递归(值, 0)
    except RecursionError:
        raise ValueError(f"JSON 嵌套过深（递归溢出，最大深度 {最大深度}）") from None
