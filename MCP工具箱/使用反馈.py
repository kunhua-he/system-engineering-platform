"""MCP 使用反馈：按开工标识追加记录，供后续升级统计。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from 公共契约.运行时.有界IO import (
    默认JSONL文件上限字节, 默认JSONL读取上限字节, 默认JSONL读取上限记录,
    追加JSONL, 读取JSONL,
)


def _脱敏(文本: str) -> str:
    文本 = 文本[:2000]
    文本 = re.sub(r"\b(sk-|ghp_)[A-Za-z0-9_-]{8,}\b", "[已脱敏]", 文本)
    文本 = re.sub(r"(?i)(password|token|secret|密钥|密码)\s*[:=]\s*\S+", r"\1=[已脱敏]", 文本)
    return 文本


def 写入反馈(
    路径: Path, *, 开工id: str, 任务: str, 角色: str, 总结: str,
    不满意: str, 多余: str, 缺失: str, 升级建议: str,
) -> dict[str, Any]:
    if not 开工id:
        raise ValueError("尚未调用 project_context，不能提交反馈")
    字段表 = {
        "总结": 总结, "不满意": 不满意, "多余": 多余,
        "缺失": 缺失, "升级建议": 升级建议,
    }
    if any(not str(值).strip() for 值 in 字段表.values()):
        raise ValueError("反馈五个字段必须填写；没有问题时明确填写“无”")
    记录 = {
        "开工id": 开工id, "任务": _脱敏(任务), "角色": 角色,
        "时间": datetime.now(timezone.utc).isoformat(),
        **{键: _脱敏(str(值).strip()) for 键, 值 in 字段表.items()},
    }
    追加JSONL(
        路径, 记录, 最大文件字节数=默认JSONL文件上限字节,
    )
    return {"成功": True, "开工id": 开工id, "反馈门禁": "已满足"}


def 查询反馈状态(路径: Path, 开工id: str) -> dict[str, Any]:
    if not 开工id:
        return {"已反馈": False, "开工id": 开工id}
    记录列表, 是否截断 = 读取JSONL(
        路径, 最大字节数=默认JSONL读取上限字节,
        最大记录数=默认JSONL读取上限记录,
    )
    for 记录 in reversed(记录列表):
        if 记录.get("开工id") == 开工id:
            return {"已反馈": True, "开工id": 开工id, "反馈": 记录,
                    "查询是否截断": 是否截断}
    return {"已反馈": False, "开工id": 开工id, "查询是否截断": 是否截断}


def 读取反馈列表(
    路径: Path, *, 开工id: str = "", 任务: str = "", 数量: int = 20,
) -> dict[str, Any]:
    if not 路径.is_file():
        return {"数量": 0, "反馈列表": [], "升级候选": []}
    反馈源, 是否截断 = 读取JSONL(
        路径, 最大字节数=默认JSONL读取上限字节,
        最大记录数=默认JSONL读取上限记录,
    )
    反馈表: list[dict[str, Any]] = []
    for 记录 in reversed(反馈源):
        if 开工id and 记录.get("开工id") != 开工id:
            continue
        if 任务 and 任务 not in str(记录.get("任务", "")):
            continue
        反馈表.append(记录)
        if len(反馈表) >= max(1, min(数量, 100)):
            break
    升级候选 = []
    for 记录 in 反馈表:
        for 字段 in ("不满意", "多余", "缺失", "升级建议"):
            内容 = str(记录.get(字段, "")).strip()
            if 内容 and 内容 != "无":
                升级候选.append({
                    "开工id": 记录.get("开工id"), "任务": 记录.get("任务"),
                    "角色": 记录.get("角色"), "类别": 字段, "内容": 内容,
                })
    return {"数量": len(反馈表), "反馈列表": 反馈表, "升级候选": 升级候选,
            "查询是否截断": 是否截断}
