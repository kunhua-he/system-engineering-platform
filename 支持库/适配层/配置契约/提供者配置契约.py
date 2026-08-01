"""提供者配置契约：外部提供者的配置需求声明与校验。

提供者必须声明：名称、版本、能力、配置需求。配置需求条目：
配置名称、类型、是否必填、默认值、是否敏感、说明。
同一适配能力只能选择一个提供者。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class 提供者配置需求:
    """一条提供者配置需求声明。"""

    配置名称: str
    类型: str = "文本"
    必填: bool = False
    默认值: Any = None
    敏感: bool = False
    说明: str = ""


def 校验配置需求(配置: dict[str, Any], 需求列表: list[提供者配置需求]) -> list[str]:
    """按需求列表校验提供者配置；返回问题列表（空=通过）。"""
    问题列表: list[str] = []
    for 需求 in 需求列表:
        if 需求.必填 and 需求.配置名称 not in 配置:
            问题列表.append(f"提供者配置缺失: {需求.配置名称}")
    for 名称, 值 in 配置.items():
        if 名称 not in {需求.配置名称 for 需求 in 需求列表}:
            问题列表.append(f"未知提供者配置项: {名称}")
    return 问题列表
