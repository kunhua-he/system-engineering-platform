"""子代理临时上下文：按开工id隔离，过期后自动清理，不进入长期记忆。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


def _安全标识(开工id: str) -> str:
    标识 = re.sub(r"[^A-Za-z0-9_-]", "", str(开工id))
    if not 标识 or len(标识) > 64:
        raise ValueError("开工id无效")
    return 标识


def _文件路径(目录: Path, 开工id: str) -> Path:
    return 目录 / f"{_安全标识(开工id)}.json"


def 写入临时上下文(
    目录: Path, *, 开工id: str, 父任务: str, 角色: str,
    允许目录: list[str], 记忆查询: list[str], 事实: list[str],
    验证计划: list[list[str]], 有效秒数: int = 7200,
) -> dict[str, Any]:
    if not str(父任务).strip() or not str(角色).strip():
        raise ValueError("父任务和角色不能为空")
    有效秒数 = max(300, min(int(有效秒数), 86400))
    目录.mkdir(parents=True, exist_ok=True)
    记录 = {
        "开工id": _安全标识(开工id), "父任务": str(父任务).strip(),
        "角色": str(角色).strip(), "允许目录": [str(项) for 项 in 允许目录],
        "定向记忆查询": [str(项) for 项 in 记忆查询 if str(项).strip()],
        "已确认事实": [str(项) for 项 in 事实 if str(项).strip()],
        "验证计划": [[str(项) for 项 in 命令] for 命令 in 验证计划],
        "创建时间": time.time(), "过期时间": time.time() + 有效秒数,
    }
    路径 = _文件路径(目录, 开工id)
    临时路径 = 路径.with_suffix(".json.tmp")
    临时路径.write_text(json.dumps(记录, ensure_ascii=False, indent=2), encoding="utf-8")
    临时路径.replace(路径)
    return {"成功": True, "开工id": 记录["开工id"], "过期秒数": 有效秒数}


def 读取临时上下文(目录: Path, 开工id: str) -> dict[str, Any]:
    路径 = _文件路径(目录, 开工id)
    if not 路径.is_file():
        return {"成功": False, "错误码": "TEMPORARY_CONTEXT_NOT_FOUND", "消息": "临时上下文不存在"}
    try:
        记录 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 异常:
        return {"成功": False, "错误码": "TEMPORARY_CONTEXT_INVALID", "消息": str(异常)}
    if float(记录.get("过期时间", 0)) <= time.time():
        路径.unlink(missing_ok=True)
        return {"成功": False, "错误码": "TEMPORARY_CONTEXT_EXPIRED", "消息": "临时上下文已过期"}
    记录["剩余秒数"] = max(0, int(记录["过期时间"] - time.time()))
    记录["成功"] = True
    return 记录


def 清理临时上下文(目录: Path, 开工id: str) -> dict[str, Any]:
    路径 = _文件路径(目录, 开工id)
    是否存在 = 路径.exists()
    路径.unlink(missing_ok=True)
    return {"成功": True, "开工id": _安全标识(开工id), "已清理": 是否存在}


def 清理过期上下文(目录: Path) -> int:
    if not 目录.is_dir():
        return 0
    数量 = 0
    当前时间 = time.time()
    for 路径 in 目录.glob("*.json"):
        try:
            if float(json.loads(路径.read_text(encoding="utf-8")).get("过期时间", 0)) <= 当前时间:
                路径.unlink(missing_ok=True)
                数量 += 1
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            路径.unlink(missing_ok=True)
            数量 += 1
    return 数量
