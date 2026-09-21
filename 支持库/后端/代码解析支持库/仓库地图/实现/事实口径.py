"""语法事实口径：行号与名称末段的统一取法（纯函数，供 图构建/建边 共用）。

为什么单独一层：建节点（图构建）与连边（建边）都要按行号排布、按名称末段解析调用目标；
把这两个取法留在任一文件里，另一个就得反向依赖，形成环。
"""

from __future__ import annotations

#: 语法事实的 类别 → 节点种类 映射；Python 类内函数（名称带点）由调用方再归一到 method。
类别表 = {"class": "class", "function": "function", "method": "method"}


def 取行号(项: dict, 键: str = "行号") -> int:
    """取正整数行号：缺省/非法一律退化为 1（不抛错，不阻断整文件）。"""
    值 = 项.get(键)
    if isinstance(值, int) and not isinstance(值, bool) and 值 > 0:
        return 值
    return 1


def 取末段(名称: str) -> str:
    """取点分名称末段（`结果.成功结果` → `成功结果`）。"""
    return 名称.rsplit(".", 1)[-1] if "." in 名称 else 名称


def 取导入名(导入: dict) -> str:
    """取导入事实的名字：优先 导入名，退到 路径（from 相对导入无导入名）。"""
    return str(导入.get("导入名") or 导入.get("路径") or "").strip()
