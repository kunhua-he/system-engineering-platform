"""MCP 被动任务观测：只记录时间、关系和结果摘要，不记录提示词或源码。"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from 公共契约.运行时.有界IO import (
    默认JSONL文件上限字节, 默认JSONL读取上限字节, 默认JSONL读取上限记录,
    追加JSONL, 读取JSONL,
)

允许阶段 = {"探索", "开发", "子代理", "测试", "等待", "合并", "收口"}


def _现在() -> str:
    return datetime.now(timezone.utc).isoformat()


def _写入(路径: Path, 记录: dict[str, Any]) -> None:
    追加JSONL(路径, 记录, 最大文件字节数=默认JSONL文件上限字节)


def 任务开始(路径: Path, *, 任务id: str, 开工id: str, 角色: str,
            父任务id: str = "", 子代理数: int = 0) -> dict[str, Any]:
    任务id = str(任务id).strip() or uuid.uuid4().hex[:16]
    记录 = {"事件": "任务开始", "任务id": 任务id, "开工id": 开工id,
            "父任务id": 父任务id, "角色": str(角色),
            "子代理数": max(0, int(子代理数)), "时间": _现在(),
            "单调时间": time.monotonic(), "时间戳": time.time()}
    _写入(路径, 记录)
    return {"成功": True, "任务id": 任务id, "时间": 记录["时间"]}


def 工具事件(路径: Path, *, 任务id: str, 开工id: str, 工具: str,
            开始单调: float, 退出码: int | None = None,
            缓存命中: bool | None = None, 错误码: str = "") -> dict[str, Any]:
    记录 = {"事件": "工具完成", "任务id": 任务id, "开工id": 开工id,
            "工具": str(工具), "时间": _现在(),
            "耗时秒": round(max(0.0, time.monotonic() - 开始单调), 6),
            "时间戳": time.time()}
    if 退出码 is not None:
        记录["退出码"] = int(退出码)
    if 缓存命中 is not None:
        记录["缓存命中"] = bool(缓存命中)
    if 错误码:
        记录["错误码"] = str(错误码)
    _写入(路径, 记录)
    return 记录


def 任务结束(路径: Path, *, 任务id: str, 开工id: str, 成功: bool,
            错误码: str = "") -> dict[str, Any]:
    task_id = str(任务id)
    记录 = {"事件": "任务结束", "任务id": task_id,
            "开工id": 开工id, "成功": bool(成功), "时间": _现在(),
            "时间戳": time.time()}
    if 错误码:
        记录["错误码"] = str(错误码)
    _写入(路径, 记录)
    return {"成功": True, "任务id": task_id}


def 查询任务(路径: Path, 任务id: str, 开工id: str = "") -> dict[str, Any]:
    if not 路径.is_file():
        return {"成功": False, "错误码": "OBSERVATION_NOT_FOUND", "消息": "任务观测不存在"}
    事件表: list[dict[str, Any]] = []
    全部事件, 是否截断 = 读取JSONL(
        路径, 最大字节数=默认JSONL读取上限字节,
        最大记录数=默认JSONL读取上限记录,
    )
    for 记录 in 全部事件:
        if 记录.get("任务id") == 任务id and (not 开工id or 记录.get("开工id") == 开工id):
            事件表.append(记录)
    if not 事件表:
        return {"成功": False, "错误码": "OBSERVATION_NOT_FOUND", "消息": "任务观测不存在"}
    工具表 = [项 for 项 in 事件表 if 项.get("事件") == "工具完成"]
    return {"成功": True, "任务id": 任务id, "事件数": len(事件表),
            "工具调用数": len(工具表),
            "工具耗时秒": round(sum(float(项.get("耗时秒", 0)) for 项 in 工具表), 6),
            "失败工具数": sum(项.get("退出码", 0) not in (0, None) for 项 in 工具表),
            "事件": 事件表, "查询是否截断": 是否截断}


def 阶段记录(路径: Path, *, 任务id: str, 开工id: str, 阶段: str,
            状态: str, 阶段id: str = "", 说明: str = "") -> dict[str, Any]:
    if 阶段 not in 允许阶段:
        raise ValueError(f"未知阶段：{阶段}")
    if 状态 not in {"开始", "结束"}:
        raise ValueError("阶段状态必须是开始或结束")
    阶段id = 阶段id.strip() or f"{阶段}-{uuid.uuid4().hex[:8]}"
    记录 = {"事件": f"阶段{状态}", "任务id": 任务id, "开工id": 开工id,
            "阶段": 阶段, "阶段id": 阶段id, "时间": _现在(),
            "时间戳": time.time(), "说明": str(说明)[:300]}
    _写入(路径, 记录)
    return {"成功": True, "任务id": 任务id, "阶段": 阶段,
            "阶段id": 阶段id, "状态": 状态}


def _区间并集长度(区间表: list[tuple[float, float]]) -> float:
    if not 区间表:
        return 0.0
    合并: list[list[float]] = []
    for 开始, 结束 in sorted(区间表):
        if not 合并 or 开始 > 合并[-1][1]:
            合并.append([开始, 结束])
        else:
            合并[-1][1] = max(合并[-1][1], 结束)
    return sum(结束 - 开始 for 开始, 结束 in 合并)


def 生成效率报告(路径: Path, 任务id: str) -> dict[str, Any]:
    查询 = 查询任务(路径, 任务id)
    if not 查询.get("成功"):
        return 查询
    事件表 = 查询["事件"]
    开始表: dict[str, dict[str, Any]] = {}
    阶段区间: dict[str, list[tuple[float, float]]] = {阶段: [] for 阶段 in 允许阶段}
    for 事件 in 事件表:
        if 事件.get("事件") == "阶段开始":
            开始表[str(事件.get("阶段id"))] = 事件
        elif 事件.get("事件") == "阶段结束":
            开始 = 开始表.pop(str(事件.get("阶段id")), None)
            if 开始 and 事件.get("时间戳", 0) >= 开始.get("时间戳", 0):
                阶段区间[str(事件["阶段"])].append((float(开始["时间戳"]), float(事件["时间戳"])))
    时间戳表 = [float(项["时间戳"]) for 项 in 事件表 if "时间戳" in 项]
    总时长 = max(时间戳表) - min(时间戳表) if len(时间戳表) >= 2 else 0.0
    全部区间 = [区间 for 区间列表 in 阶段区间.values() for 区间 in 区间列表]
    阶段耗时 = {阶段: round(_区间并集长度(区间), 3) for 阶段, 区间 in 阶段区间.items()}
    已分类 = _区间并集长度(全部区间)
    排序 = sorted(阶段耗时.items(), key=lambda 项: 项[1], reverse=True)
    return {"成功": True, "任务id": 任务id, "墙钟总时长秒": round(总时长, 3),
            "阶段耗时秒": 阶段耗时, "工具耗时秒": 查询["工具耗时秒"],
            "未分类间隔秒": round(max(0.0, 总时长 - 已分类), 3),
            "最大耗时阶段": 排序[0][0] if 排序 and 排序[0][1] > 0 else "未标注",
            "未闭合阶段数": len(开始表),
            "建议": "优先优化最大耗时阶段；未分类间隔过大时补充阶段标注，不得主观归因。"}
