"""核心快照清单模板：快照目录结构骨架（清单/摘要/激活指针）生成与校验。

模板要素（与 核心治理.py 摘要语义一致）：
- 清单.json：范围、文件表（相对路径+sha256）、文件数、时间；
- 摘要.json：聚合摘要（范围+文件表，支持库.适配层.内容摘要）；
- 当前.json：激活指针（目标快照摘要/栅栏令牌/版本）。

回滚切换不可变旧制品、不恢复源码分支：模板只生成制品骨架与元数据，
激活指针仅记录目标摘要；供核心治理与发布回滚复用。

防御：目标目录已存在文件时拒绝覆盖；范围路径逃逸（绝对/..）拒绝。
校验：三文件存在 / 清单与磁盘一致 / 聚合摘要匹配 → 通过或 快照损坏。
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve()
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.适配层 import 内容摘要

清单文件名 = "清单.json"
摘要文件名 = "摘要.json"
激活指针文件名 = "当前.json"
排除目录名表 = {"__pycache__"}


def _规范化范围路径(路径: str) -> str:
    """校验范围目录相对路径：拒绝绝对路径与 .. 逃逸。"""
    if not 路径 or 路径 in (".", "/", "\\"):
        raise ValueError(f"空或根路径不允许: {路径!r}")
    if 路径.startswith("/") or 路径.startswith("\\") or 路径[1:2] == ":":
        raise ValueError(f"绝对路径不允许: {路径!r}")
    if any(段 in ("..", ".") for 段 in 路径.replace("\\", "/").split("/")):
        raise ValueError(f"路径逃逸不允许: {路径!r}")
    return 路径


def _聚合摘要(范围目录表: list[str], 文件表: dict[str, str]) -> str:
    """聚合摘要：范围 + 全部文件摘要（与核心治理 摘要语义一致）。"""
    return 内容摘要(json.dumps(
        {"范围": [str(项) for 项 in 范围目录表], "文件表": 文件表},
        ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _收集文件表(范围目录表: list[str], 工作目录: Path) -> dict[str, str]:
    """扫描范围目录表全部正式文件：相对快照目录路径 + sha256。"""
    文件表: dict[str, str] = {}
    for 范围路径 in 范围目录表:
        规范路径 = _规范化范围路径(范围路径)
        范围目录 = (工作目录 / 规范路径).resolve()
        if not 范围目录.is_dir():
            raise OSError(f"范围目录不存在: {规范路径}")
        for 文件 in sorted(范围目录.rglob("*")):
            if not 文件.is_file() or any(段 in 排除目录名表 for 段 in 文件.parts):
                continue
            相对路径 = f"{规范路径}/{文件.relative_to(范围目录).as_posix()}"
            文件表[相对路径] = hashlib.sha256(文件.read_bytes()).hexdigest()
    return dict(sorted(文件表.items()))


def 生成快照清单模板(目标目录: Path, 范围目录表: list[str], *,
                   工作目录: Path | None = None, 版本: str = "1.0.0",
                   栅栏令牌: str = "") -> dict[str, Any]:
    """生成核心快照结构骨架；已存在文件拒绝覆盖；路径逃逸拒绝。"""
    工作根 = Path(工作目录) if 工作目录 else 系统根
    目标 = Path(目标目录)
    if 目标.exists() and any(目标.iterdir()):
        return {"成功": False, "错误码": "已存在",
                "消息": f"快照目录已存在，拒绝覆盖: {目标}", "快照目录": str(目标)}
    try:
        文件表 = _收集文件表(范围目录表, 工作根)
    except (OSError, ValueError) as 错误:
        return {"成功": False, "错误码": "参数无效",
                "消息": f"收集范围文件失败: {错误}", "快照目录": str(目标)}
    if not 文件表:
        return {"成功": False, "错误码": "参数无效",
                "消息": "范围目录表内无正式文件", "快照目录": str(目标)}
    摘要 = _聚合摘要(范围目录表, 文件表)
    时间 = datetime.now().isoformat(timespec="seconds")
    清单 = {"类型": "核心快照清单模板", "范围": list(范围目录表),
            "摘要": 摘要, "文件数": len(文件表), "文件表": 文件表, "时间": 时间}
    激活指针 = {"激活快照": str(目标), "目标摘要": 摘要,
               "栅栏令牌": 栅栏令牌 or uuid.uuid4().hex[:16],
               "版本": 版本, "时间": 时间,
               "说明": "回滚切换不可变旧制品，不恢复源码分支"}
    try:
        目标.mkdir(parents=True, exist_ok=True)
        for 相对路径 in 文件表:
            目标文件 = 目标 / 相对路径
            目标文件.parent.mkdir(parents=True, exist_ok=True)
            目标文件.write_bytes((工作根 / 相对路径).read_bytes())
        (目标 / 清单文件名).write_text(
            json.dumps(清单, ensure_ascii=False, indent=2), encoding="utf-8")
        (目标 / 摘要文件名).write_text(
            json.dumps({"摘要": 摘要}, ensure_ascii=False), encoding="utf-8")
        (目标 / 激活指针文件名).write_text(
            json.dumps(激活指针, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as 错误:
        return {"成功": False, "错误码": "快照损坏",
                "消息": f"快照写入失败: {错误}", "快照目录": str(目标)}
    return {"成功": True, "错误码": "", "快照目录": str(目标),
            "摘要": 摘要, "文件数": len(文件表), "消息": "核心快照清单模板已生成"}


def 校验快照模板(快照目录: Path) -> tuple[bool, str]:
    """校验快照结构：三文件存在 / 清单与磁盘一致 / 聚合摘要匹配。"""
    目录 = Path(快照目录)
    for 文件名 in (清单文件名, 摘要文件名, 激活指针文件名):
        if not (目录 / 文件名).is_file():
            return False, f"快照缺少 {文件名}"
    try:
        清单 = json.loads((目录 / 清单文件名).read_text(encoding="utf-8"))
        摘要文件 = json.loads((目录 / 摘要文件名).read_text(encoding="utf-8"))
        激活指针 = json.loads((目录 / 激活指针文件名).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as 错误:
        return False, f"快照元数据损坏: {错误}"
    文件表 = 清单.get("文件表")
    摘要 = 清单.get("摘要")
    if not isinstance(文件表, dict) or not isinstance(摘要, str):
        return False, "快照清单字段缺失"
    磁盘文件表: dict[str, str] = {}
    for 文件 in sorted(目录.rglob("*")):
        if not 文件.is_file():
            continue
        相对路径 = 文件.relative_to(目录).as_posix()
        if 相对路径 in (清单文件名, 摘要文件名, 激活指针文件名):
            continue
        磁盘文件表[相对路径] = hashlib.sha256(文件.read_bytes()).hexdigest()
    if 磁盘文件表 != 文件表:
        return False, "快照内容被篡改（磁盘文件摘要与清单不符）"
    范围 = [str(项) for 项 in 清单.get("范围", [])]
    if _聚合摘要(范围, 磁盘文件表) != 摘要:
        return False, "快照内容被篡改（聚合摘要与清单不符）"
    if 摘要文件.get("摘要") != 摘要 or 激活指针.get("目标摘要") != 摘要:
        return False, "快照元数据与清单摘要不一致"
    return True, "快照结构完整"


__all__ = ["生成快照清单模板", "校验快照模板",
           "清单文件名", "摘要文件名", "激活指针文件名"]
