"""公开能力目录：只读取声明，不导入实现。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _读取声明(路径: Path) -> dict[str, Any] | None:
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return 数据 if isinstance(数据, dict) else None


def _能力记录(声明: dict[str, Any]) -> list[dict[str, Any]]:
    包id = str(声明.get("包id", ""))
    包名 = str(声明.get("中文名称", 声明.get("名称", "")))
    类型 = str(声明.get("类型", ""))
    说明 = str(声明.get("说明", ""))
    记录表: list[dict[str, Any]] = []
    for 能力 in 声明.get("提供能力", 声明.get("能力", [])):
        if isinstance(能力, dict):
            能力id = str(能力.get("能力id", ""))
            名称 = str(能力.get("中文名称", 能力.get("名称", 能力id)))
            能力说明 = str(能力.get("说明", 说明))
            参数 = 能力.get("参数", [])
            返回 = 能力.get("返回", "")
            错误码 = 能力.get("错误码", [])
        else:
            能力id = str(能力)
            名称 = 能力id.rsplit(".", 1)[-1]
            能力说明 = 说明
            参数, 返回, 错误码 = [], "", []
        if 能力id:
            记录表.append({
                "能力id": 能力id, "中文名称": 名称, "说明": 能力说明,
                "包id": 包id, "包名称": 包名, "类型": 类型,
                "参数": 参数, "返回": 返回, "错误码": 错误码,
            })
    return 记录表


def _全部能力(项目根: Path) -> list[dict[str, Any]]:
    结果: list[dict[str, Any]] = []
    for 根目录 in (项目根 / "支持库", 项目根 / "模块库"):
        if not 根目录.is_dir():
            continue
        for 路径 in 根目录.rglob("包声明.json"):
            声明 = _读取声明(路径)
            if 声明 is not None:
                结果.extend(_能力记录(声明))
    return sorted(结果, key=lambda 项: (项["能力id"], 项["包id"]))


def 搜索公开能力(项目根: Path, 关键词: str, 限制: int = 20) -> list[dict[str, Any]]:
    """按公开声明检索能力，不加载实现源码。"""
    关键词 = 关键词.strip().lower()
    候选 = _全部能力(项目根)
    if not 关键词:
        return 候选[: max(1, min(限制, 100))]
    return [
        项 for 项 in 候选
        if 关键词 in json.dumps(项, ensure_ascii=False).lower()
    ][: max(1, min(限制, 100))]


def 读取公开能力(项目根: Path, 能力id: str) -> dict[str, Any] | None:
    for 记录 in _全部能力(项目根):
        if 记录["能力id"] == 能力id:
            return 记录
    return None
