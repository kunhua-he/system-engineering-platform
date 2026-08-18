"""配置读取：统一配置读取器。

职责：读取 JSON 配置、结构校验、默认配置加载、项目配置覆盖、
环境配置覆盖、外部提供者配置覆盖、配置来源追踪、配置缺失报告、
配置类型错误报告、未知配置项报告。

覆盖顺序（固定）：支持库默认配置 → 项目默认配置 → 当前环境配置
→ 外部提供者配置 → 运行入口显式覆盖。禁止实现代码偷偷读取任意
配置文件；禁止未知字段静默接受；禁止缺失必填配置自动伪造默认值。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class 配置读取结果:
    """一次配置读取的结果。"""

    成功: bool = False
    配置: dict[str, Any] = field(default_factory=dict)
    来源表: dict[str, str] = field(default_factory=dict)
    问题列表: list[str] = field(default_factory=list)
    警告列表: list[str] = field(default_factory=list)

    def 打印(self) -> str:
        行列表 = ["配置读取结果", f"成功: {self.成功}"]
        for 名称, 来源 in self.来源表.items():
            行列表.append(f"  {名称} ← {来源}")
        for 问题 in self.问题列表:
            行列表.append(f"  ✗ {问题}")
        for 警告 in self.警告列表:
            行列表.append(f"  ⚠ {警告}")
        return "\n".join(行列表)


def 读取JSON配置(路径: Path) -> dict[str, Any]:
    """读取 JSON 配置；文件缺失或 JSON 不合法抛 ValueError。"""
    if not 路径.is_file():
        raise ValueError(f"配置文件不存在: {路径}")
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        raise ValueError(f"配置文件不可读 {路径}: {错误}") from 错误
    if not isinstance(数据, dict):
        raise ValueError(f"配置必须是 JSON 对象: {路径}")
    return 数据


def 读取配置目录(配置目录: Path) -> tuple[dict[str, Any], list[str]]:
    """读取目录下全部 JSON 配置并合并（文件名按字典序，后者覆盖前者）。

    返回 (合并配置, 来源名列表)。目录不存在返回空配置。
    """
    合并配置: dict[str, Any] = {}
    来源列表: list[str] = []
    if not 配置目录.is_dir():
        return 合并配置, 来源列表
    for 文件 in sorted(配置目录.glob("*.json")):
        数据 = 读取JSON配置(文件)
        合并配置.update(数据)
        来源列表.append(文件.stem)
    return 合并配置, 来源列表
