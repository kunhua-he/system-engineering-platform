"""包声明契约：包身份、版本、依赖与能力列表的统一声明。

一份包声明是支持库或模块的机器可读元信息（JSON），遵循易语言式工程
原则：永久包 id、版本、依赖要求、能力、说明属于声明，不靠导入源码猜测。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

版本正则 = re.compile(r"^\d+\.\d+\.\d+$")

允许类型集合 = {"支持库", "模块", "基础模块", "功能模块"}
必填字段表 = ("包id", "名称", "类型", "版本", "能力")


@dataclass(frozen=True)
class 能力声明:
    """能力契约声明：能力 id、名称、参数、返回与说明。"""

    能力id: str
    名称: str = ""
    参数: list[dict[str, str]] = field(default_factory=list)
    返回: str = ""
    说明: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "能力id": self.能力id,
            "名称": self.名称,
            "参数": self.参数,
            "返回": self.返回,
            "说明": self.说明,
        }


@dataclass(frozen=True)
class 包声明:
    """一份支持库或模块的包声明。"""

    包id: str
    名称: str
    类型: str
    版本: str
    说明: str = ""
    入口: str = ""
    依赖: list[dict] = field(default_factory=list)
    能力: list[能力声明] = field(default_factory=list)
    配置项: list[dict] = field(default_factory=list)
    来源路径: str = ""
    已废弃: bool = False

    def 转字典(self) -> dict[str, Any]:
        return {
            "包id": self.包id,
            "名称": self.名称,
            "类型": self.类型,
            "版本": self.版本,
            "说明": self.说明,
            "入口": self.入口,
            "依赖": self.依赖,
            "能力": [能力.转字典() for 能力 in self.能力],
            "来源路径": self.来源路径,
        }


def 校验版本(版本: str) -> None:
    """版本必须为 x.y.z 三段式。"""
    if not 版本正则.match(版本):
        raise ValueError(f"版本格式不合法（应为 x.y.z）: {版本}")


def 从字典构建(数据: dict[str, Any], *, 来源路径: str = "") -> 包声明:
    """从字典构建包声明并做结构校验。"""
    缺失 = [字段 for 字段 in 必填字段表 if 字段 not in 数据]
    if 缺失:
        raise ValueError(f"包声明缺少必填字段: {', '.join(缺失)}")
    类型 = str(数据["类型"])
    if 类型 not in 允许类型集合:
        raise ValueError(f"包类型不合法: {类型}，可选: {'/'.join(允许类型集合)}")
    版本 = str(数据["版本"])
    校验版本(版本)
    依赖 = 数据.get("依赖") or []
    if not isinstance(依赖, list):
        raise ValueError("依赖必须是列表")
    能力列表 = []
    for 条目 in 数据.get("能力") or []:
        if not isinstance(条目, dict) or not 条目.get("能力id"):
            raise ValueError("能力声明缺少 能力id")
        能力列表.append(
            能力声明(
                能力id=str(条目["能力id"]),
                名称=str(条目.get("名称", "")),
                参数=条目.get("参数") or [],
                返回=str(条目.get("返回", "")),
                说明=str(条目.get("说明", "")),
            )
        )
    return 包声明(
        包id=str(数据["包id"]),
        名称=str(数据["名称"]),
        类型=类型,
        版本=版本,
        说明=str(数据.get("说明", "")),
        入口=str(数据.get("入口", "")),
        依赖=依赖,
        能力=能力列表,
        配置项=数据.get("配置项") or [],
        来源路径=来源路径,
        已废弃=bool(数据.get("已废弃", False)),
    )


def 加载声明文件(路径: Path | str) -> 包声明:
    """从 JSON 文件加载并校验包声明。"""
    文件路径 = Path(路径)
    if not 文件路径.is_file():
        raise FileNotFoundError(f"包声明文件不存在: {文件路径}")
    try:
        数据 = json.loads(文件路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError as 错误:
        raise ValueError(f"包声明不是合法 JSON: {文件路径} ({错误})") from 错误
    if not isinstance(数据, dict):
        raise ValueError(f"包声明必须是 JSON 对象: {文件路径}")
    return 从字典构建(数据, 来源路径=str(文件路径))
