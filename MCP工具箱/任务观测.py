"""MCP 被动任务观测：只记录时间、关系和结果摘要，不记录提示词或源码。"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _现在() -> str:
    return datetime.now(timezone.utc).isoformat()


def _写入(路径: Path, 记录: dict[str, Any]) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    with 路径.open("a", encoding="utf-8") as 文件:
        文件.write(json.dumps(记录, ensure_ascii=False) + "\n")


def 任务开始(路径: Path, *, 任务id: str, 开工id: str, 角色: str,
            父任务id: str = "", 子代理数: int = 0) -> dict[str, Any]:
    任务id = str(任务id).strip() or uuid.uuid4().hex[:16]
    记录 = {"事件": "任务开始", "任务id": 任务id, "开工id": 开工id,
            "父任务id": 父任务id, "角色": str(角色),
            "子代理数": max(0, int(子代理数)), "时间": _现在(),
            "单调时间": time.monotonic()}
    _写入(路径, 记录)
    return {"成功": True, "任务id": 任务id, "时间": 记录["时间"]}


def 工具事件(路径: Path, *, 任务id: str, 开工id: str, 工具: str,
            开始单调: float, 退出码: int | None = None,
            缓存命中: bool | None = None, 错误码: str = "") -> dict[str, Any]:
    记录 = {"事件": "工具完成", "任务id": 任务id, "开工id": 开工id,
            "工具": str(工具), "时间": _现在(),
            "耗时秒": round(max(0.0, time.monotonic() - 开始单调), 6)}
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
            "开工id": 开工id, "成功": bool(成功), "时间": _现在()}
    if 错误码:
        记录["错误码"] = str(错误码)
    _写入(路径, 记录)
    return {"成功": True, "任务id": task_id}


def 查询任务(路径: Path, 任务id: str) -> dict[str, Any]:
    if not 路径.is_file():
        return {"成功": False, "错误码": "OBSERVATION_NOT_FOUND", "消息": "任务观测不存在"}
    事件表: list[dict[str, Any]] = []
    for 行 in 路径.read_text(encoding="utf-8").splitlines():
        try:
            记录 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if 记录.get("任务id") == 任务id:
            事件表.append(记录)
    if not 事件表:
        return {"成功": False, "错误码": "OBSERVATION_NOT_FOUND", "消息": "任务观测不存在"}
    工具表 = [项 for 项 in 事件表 if 项.get("事件") == "工具完成"]
    return {"成功": True, "任务id": 任务id, "事件数": len(事件表),
            "工具调用数": len(工具表),
            "工具耗时秒": round(sum(float(项.get("耗时秒", 0)) for 项 in 工具表), 6),
            "失败工具数": sum(项.get("退出码", 0) not in (0, None) for 项 in 工具表),
            "事件": 事件表}
