"""支持库开发协作工具集：需求登记、复用搜索（供主协调接线）。

支持库开发门面工具，全部为纯函数，统一返回 结果 结构（成功/错误码/值）：
- 登记需求：写入 工程缓存/需求登记/{work_id}.json，快照结构复用
  平台控制面/需求登记.py 语义（需求id/版本/状态/确认状态/创建时间），
  并报告复用决策。
- 复用搜索：扫描 支持库/适配层/*提供者/能力定义.json 与
  支持库/后端/*/能力定义.json，返回已有能力候选并标记可复用状态。

能力占用已迁至同目录 `能力占用.py`（数据库 `占用租约` 表，原子互斥 + 心跳 + 过期回收 +
收口释放），不再用 `工程缓存/能力占用/*.json` 那套无释放的永久锁。
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

参数不合法 = "参数不合法"
登记失败 = "登记失败"
错误码表 = (参数不合法, 登记失败)

_标识正则 = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff-]+$")


def _结果(成功: bool, 错误码: str = "", 值: Any = None) -> dict[str, Any]:
    return {"成功": 成功, "错误码": 错误码, "值": 值}


def _标识(文本: Any, 名称: str, 允许点: bool = False) -> str | None:
    值 = str(文本).strip()
    正则 = _标识正则 if not 允许点 else re.compile(r"^[A-Za-z0-9_.\u4e00-\u9fff-]+$")
    if not 值 or len(值) > 200 or not 正则.fullmatch(值) or ".." in 值:
        return None
    return 值


def _原子写(json路径: Path, 数据: dict[str, Any]) -> None:
    json路径.parent.mkdir(parents=True, exist_ok=True)
    临时路径 = json路径.with_suffix(json路径.suffix + ".tmp")
    with open(临时路径, "w", encoding="utf-8") as 文件:
        json.dump(数据, 文件, ensure_ascii=False, indent=1)
        文件.flush()
        os.fsync(文件.fileno())
    os.replace(临时路径, json路径)


def 登记需求(工程缓存根: Path, *, 能力id: str, 说明: str, 来源任务: str,
            work_id: str, 项目根: Path | None = None) -> dict[str, Any]:
    """登记支持库开发需求，返回需求快照（结构对齐平台控制面需求登记语义）。"""
    能力id = _标识(能力id, "能力id", 允许点=True)
    来源任务 = _标识(来源任务, "来源任务", 允许点=True)
    work_id = _标识(work_id, "work_id")
    说明 = str(说明).strip()
    if 能力id is None or 来源任务 is None or work_id is None or not 说明:
        return _结果(False, 参数不合法, {"消息": "能力id/说明/来源任务/work_id 均不能为空且格式必须合法"})
    需求id = uuid.uuid4().hex[:16]
    快照 = {
        "需求id": 需求id, "版本": "1", "目标": 说明, "能力id": 能力id,
        "来源任务": 来源任务, "验收结果": [],
        "创建时间": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if 项目根 is not None and (Path(项目根) / "平台控制面" / "需求登记.py").is_file():
        复用决策 = "复用平台控制面需求登记语义：快照结构对齐（需求id/版本/状态/确认状态/创建时间）"
    else:
        复用决策 = "平台控制面需求登记契约缺失，独立写入工程缓存（结构仍对齐平台语义）"
    记录 = {**快照, "状态": "待确认", "确认状态": "未确认", "复用决策": 复用决策}
    try:
        _原子写(Path(工程缓存根) / "需求登记" / f"{work_id}.json", 记录)
    except OSError as 异常:
        return _结果(False, 登记失败, {"消息": f"需求登记写入失败: {异常}"})
    return _结果(True, "", {**快照, "确认状态": "未确认", "复用决策": 复用决策,
                            "文件": str(Path(工程缓存根) / "需求登记" / f"{work_id}.json")})


def _能力定义表(项目根: Path) -> list[dict[str, Any]]:
    记录表: list[dict[str, Any]] = []
    for 根目录 in (Path(项目根) / "支持库" / "适配层", Path(项目根) / "支持库" / "后端"):
        if not 根目录.is_dir():
            continue
        for 路径 in 根目录.rglob("能力定义.json"):
            try:
                数据 = json.loads(路径.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(数据, dict):
                continue
            包id = str(数据.get("包id", ""))
            包说明 = str(数据.get("说明", ""))
            for 能力 in 数据.get("能力列表", []):
                if not isinstance(能力, dict):
                    continue
                能力id = str(能力.get("能力id", ""))
                if not 能力id:
                    continue
                记录表.append({
                    "能力id": 能力id,
                    "中文名称": str(能力.get("中文名称", "")),
                    "说明": str(能力.get("说明", 包说明)),
                    "包id": 包id,
                    "包路径": str(路径.parent),
                })
    return 记录表


def 复用搜索(项目根: Path, 关键词: str) -> dict[str, Any]:
    """扫描支持库能力定义，返回已有能力候选并标记 已存在可复用/无现成。"""
    关键词 = str(关键词).strip()
    if not 关键词:
        return _结果(False, 参数不合法, {"消息": "关键词不能为空"})
    目标 = 关键词.lower()
    候选表 = [
        项 for 项 in _能力定义表(项目根)
        if 目标 in json.dumps(
            {键: 项[键] for 键 in ("能力id", "中文名称", "说明", "包id")},
            ensure_ascii=False).lower()
    ]
    候选表.sort(key=lambda 项: (项["能力id"], 项["包id"]))
    状态 = "已存在可复用" if 候选表 else "无现成"
    return _结果(True, "", {"关键词": 关键词, "状态": 状态, "候选": 候选表})
