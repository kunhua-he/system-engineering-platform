"""依赖解析器：解析包依赖、拓扑排序与循环检测。

依赖声明格式：[{"能力": "能力id", "版本": ">=1.0.0"}]。
解析规则：依赖的能力必须由某支持库/模块提供且版本满足；依赖循环必须失败。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from 公共契约.包声明 import 包声明

版本约束正则 = re.compile(r"^(>=|<=|==|>|<)?\s*(\d+\.\d+\.\d+)$")


@dataclass
class 解析结果:
    """依赖解析结果：顺序列表、缺失能力、版本冲突、循环。"""

    顺序列表: list[str] = field(default_factory=list)
    缺失能力: list[str] = field(default_factory=list)
    版本冲突: list[str] = field(default_factory=list)
    循环: list[str] = field(default_factory=list)

    @property
    def 成功(self) -> bool:
        return not (self.缺失能力 or self.版本冲突 or self.循环)


def _版本元组(版本: str) -> tuple[int, int, int]:
    return tuple(int(部分) for 部分 in 版本.split("."))  # type: ignore[return-value]


def _满足约束(实际版本: str, 约束: str) -> bool:
    """判断实际版本是否满足 >=/<=/==/>/< 约束；无约束视为满足。"""
    匹配 = 版本约束正则.match(约束.strip())
    if not 匹配:
        return True
    运算符, 目标版本 = 匹配.group(1) or "==", 匹配.group(2)
    实际, 目标 = _版本元组(实际版本), _版本元组(目标版本)
    if 运算符 == ">=":
        return 实际 >= 目标
    if 运算符 == "<=":
        return 实际 <= 目标
    if 运算符 == ">":
        return 实际 > 目标
    if 运算符 == "<":
        return 实际 < 目标
    return 实际 == 目标


def 解析依赖(声明列表: list[包声明], 能力提供者: dict[str, tuple[str, str]]) -> 解析结果:
    """解析依赖。

    参数:
        声明列表: 全部支持库/模块声明。
        能力提供者: 能力id -> (提供包id, 提供版本)，来自已安装能力注册表。
    返回:
        解析结果：拓扑顺序（支持库在前）、缺失/冲突/循环问题。
    """
    结果 = 解析结果()
    包表: dict[str, 包声明] = {声明.包id: 声明 for 声明 in 声明列表}
    入度: dict[str, int] = {声明.包id: 0 for 声明 in 声明列表}
    依赖图: dict[str, list[str]] = {声明.包id: [] for 声明 in 声明列表}

    for 声明 in 声明列表:
        for 依赖 in 声明.依赖:
            能力id = str(依赖.get("能力", ""))
            提供 = 能力提供者.get(能力id)
            if 提供 is None:
                结果.缺失能力.append(f"{声明.包id} 依赖 {能力id} 但无提供者")
                continue
            提供包id, 提供版本 = 提供
            约束 = str(依赖.get("版本", ""))
            if not _满足约束(提供版本, 约束):
                结果.版本冲突.append(f"{声明.包id} 要求 {能力id} {约束}，提供方 {提供包id} 为 {提供版本}")
            if 提供包id in 包表 and 提供包id != 声明.包id:
                依赖图[提供包id].append(声明.包id)
                入度[声明.包id] += 1

    # Kahn 拓扑排序：先支持库后模块（支持库类型权重低者优先）
    待处理 = sorted(
        (包id for 包id, 度 in 入度.items() if 度 == 0),
        key=lambda 包id: (0 if 包表[包id].类型 == "支持库" else 1, 包id),
    )
    while 待处理:
        当前 = 待处理.pop(0)
        结果.顺序列表.append(当前)
        for 后继 in sorted(依赖图[当前]):
            入度[后继] -= 1
            if 入度[后继] == 0:
                待处理.append(后继)
                待处理.sort(key=lambda 包id: (0 if 包表[包id].类型 == "支持库" else 1, 包id))
    if len(结果.顺序列表) != len(包表):
        剩余 = [包id for 包id, 度 in 入度.items() if 度 > 0]
        结果.循环 = sorted(剩余)
    return 结果
