"""配置读取工具：JSON 配置文件的读取与结构校验（提供者层内部原子件）。

本件只做「读一个 JSON 文件成字典、不合法就 fail-closed 抛 ValueError」，
不解释任何业务语义、不做多层级合并、不追踪来源。
全仓唯一配置读取门面是 `项目适配层/配置适配/`（见其 说明/设计说明.md）；
本件与之的关系是**提供者层内部原子件 vs 项目门面层**，不是两套同功能实现。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
