"""配置合并：固定覆盖顺序的配置合并器。

覆盖顺序（固定）：支持库默认配置 → 项目默认配置 → 当前环境配置
→ 外部提供者配置 → 运行入口显式覆盖。每一步记录配置来源，最终
产出合并配置 + 来源追踪表。禁止覆盖顺序不固定。
"""

from __future__ import annotations

from typing import Any

from 项目适配层.配置适配.配置读取 import 配置读取结果


def 合并配置(
    支持库默认: dict[str, Any] | None = None,
    项目默认: dict[str, Any] | None = None,
    环境配置: dict[str, Any] | None = None,
    提供者配置: dict[str, Any] | None = None,
    显式覆盖: dict[str, Any] | None = None,
) -> 配置读取结果:
    """按固定顺序合并五层配置；返回合并结果与来源追踪。

    显式覆盖层必须明确标记，禁止与项目默认混淆。
    """
    结果 = 配置读取结果()
    层级表 = [
        ("支持库默认配置", 支持库默认 or {}),
        ("项目默认配置", 项目默认 or {}),
        ("当前环境配置", 环境配置 or {}),
        ("外部提供者配置", 提供者配置 or {}),
        ("运行入口显式覆盖", 显式覆盖 or {}),
    ]
    合并表: dict[str, Any] = {}
    来源表: dict[str, str] = {}
    for 层级名, 配置 in 层级表:
        if not isinstance(配置, dict):
            结果.问题列表.append(f"{层级名} 必须是字典")
            return 结果
        for 名称, 值 in 配置.items():
            合并表[名称] = 值
            来源表[名称] = 层级名
    结果.配置 = 合并表
    结果.来源表 = 来源表
    结果.成功 = True
    return 结果


def 解析环境配置(环境名称: str, 项目配置目录) -> dict[str, Any]:
    """从项目配置目录读取指定环境的配置（如 开发配置.json/发布配置.json）。

    环境名称映射：开发→开发配置.json，发布→发布配置.json，否则 环境名+配置.json。
    """
    from pathlib import Path

    配置目录 = Path(项目配置目录)
    文件名 = f"{环境名称}配置.json"
    路径 = 配置目录 / 文件名
    if not 路径.is_file():
        return {}
    from 项目适配层.配置适配.配置读取 import 读取JSON配置
    return 读取JSON配置(路径)
