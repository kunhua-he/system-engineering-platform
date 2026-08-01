"""提供者配置读取：读取提供者配置并合并到统一配置体系。

提供者配置只存外部适配层/提供者配置/；读取后按能力id返回配置段。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from 支持库.适配层.配置读取.配置读取工具 import 读取JSON配置


def 读取提供者配置(配置目录: Path | None = None) -> dict[str, Any]:
    """读取提供者配置目录（默认 外部适配层/提供者配置/）。"""
    配置目录 = 配置目录 or Path(__file__).resolve().parents[1] / "提供者配置"
    配置文件 = 配置目录 / "提供者配置.json"
    if not 配置文件.is_file():
        return {}
    return 读取JSON配置(配置文件)


def 获取能力配置(配置: dict[str, Any], 能力id: str) -> dict[str, Any]:
    """获取某能力对应的提供者配置段。"""
    return dict(配置.get(能力id, {}))
