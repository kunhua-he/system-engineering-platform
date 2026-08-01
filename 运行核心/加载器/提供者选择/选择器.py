"""提供者选择器：为能力选择唯一提供者。

多提供者冲突必须失败（禁止静默选第一个）；无提供者必须失败。
选择只读公共契约与包声明，不加载实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from 公共契约.包声明.声明 import 包声明


@dataclass
class 提供者选择结果:
    """一次能力提供者选择的结果。"""

    能力id: str
    提供包id: str = ""
    提供版本: str = ""
    冲突列表: list[str] = field(default_factory=list)
    缺失: bool = False

    @property
    def 成功(self) -> bool:
        return bool(self.提供包id) and not self.冲突列表


def 选择提供者(能力id: str, 声明列表: list[包声明]) -> 提供者选择结果:
    """为能力选择唯一提供者；多提供者或缺失时返回失败并说明。"""
    提供者列表 = [
        (声明.包id, 声明.版本)
        for 声明 in 声明列表
        if any(能力.能力id == 能力id for 能力 in 声明.能力)
    ]
    结果 = 提供者选择结果(能力id=能力id)
    if not 提供者列表:
        结果.缺失 = True
        return 结果
    if len(提供者列表) > 1:
        结果.冲突列表 = [f"{包id}@{版本}" for 包id, 版本 in 提供者列表]
        return 结果
    结果.提供包id, 结果.提供版本 = 提供者列表[0]
    return 结果


def 选择全部提供者(声明列表: list[包声明]) -> dict[str, 提供者选择结果]:
    """为全部声明中出现的能力逐一选择提供者。"""
    能力集合: set[str] = set()
    for 声明 in 声明列表:
        for 能力 in 声明.能力:
            能力集合.add(能力.能力id)
    return {能力id: 选择提供者(能力id, 声明列表) for 能力id in sorted(能力集合)}
