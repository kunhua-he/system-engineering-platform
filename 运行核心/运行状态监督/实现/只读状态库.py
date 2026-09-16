"""只读状态库探查：结构版本读取与结构问题枚举（不建库、不迁移、不写盘）。

分工（第 2 条 1 项 分层与归属固定）：
- `运行核心/权威状态.py`：结构版本口径（`状态结构版本` / `目标版本`）、迁移序列表、
  **结构校验规则表与逐项判定实现**（`_校验版本结构` / `_校验表存在` / `_校验列`）的唯一出处；
- 本模块：只做「只读连接 + 按规则表逐项调用唯一判定 + 结果归一」，
  不重写一行「哪些表/哪些列必需、完整性怎么判」的分支。

为什么借一个**未初始化**的校验器实例：`权威状态.__init__` 会建库并执行结构迁移（写盘），
与「只读铁律」冲突；而上述三个判定实现只吃 `连接` 参数、只读类级 `校验规则表`，
不需要任何实例状态。故 `object.__new__` 绕过 `__init__`（对象不进 `_活动状态实例`，
`__del__` 全程 `getattr` 兜底），判定口径仍只有一份。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from 运行核心.权威状态 import 权威状态, 版本元组

库文件名 = "权威状态.db"
结构版本键 = "结构版本"


def 库文件路径(存储目录: Path) -> Path:
    """权威状态库文件路径（目录下取 权威状态.db）。"""
    return Path(存储目录) / 库文件名


def 安全版本元组(版本: Any) -> tuple[int, ...] | None:
    """版本 → 比较元组；非法版本返回 None（禁止字符串字典序比较，交给调用方判不一致）。"""
    try:
        return 版本元组(str(版本))
    except (TypeError, ValueError):
        return None


def 只读连接(库文件: Path) -> sqlite3.Connection:
    """打开只读连接：URI `mode=ro`，不建库、不迁移、不写盘（`as_uri` 负责路径转义）。"""
    return sqlite3.connect(Path(库文件).resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)


def 借校验器() -> 权威状态:
    """借未初始化的权威状态实例：只用它的 校验规则表 与判定实现，不持有任何连接/状态。"""
    return object.__new__(权威状态)


def 读库中结构版本(连接: sqlite3.Connection) -> str:
    """读 元信息.结构版本；表不存在视为「无版本记录」（空串），其余 sqlite 错误照原样上抛。"""
    try:
        行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键=?", (结构版本键,)).fetchone()
    except sqlite3.OperationalError as 错误:
        if "no such table" in str(错误):
            return ""
        raise
    return "" if 行 is None or 行[0] is None else str(行[0])


def _判定(调用) -> str:
    """执行一次唯一判定实现：RuntimeError = 判定结论原文（问题）；其余异常照原样上抛。"""
    try:
        调用()
    except RuntimeError as 错误:
        return str(错误)
    return ""


def 枚举结构问题(连接: sqlite3.Connection, 目标版本: str) -> list[str]:
    """按 `权威状态.校验规则表` 逐项调用唯一判定实现，收集全部原文明细（版本升序）。"""
    校验器 = 借校验器()
    目标元组 = 安全版本元组(目标版本)
    问题列表: list[str] = []
    for 规则版本 in sorted(校验器.校验规则表, key=版本元组):
        if 目标元组 is not None and (安全版本元组(规则版本) or (0,)) > 目标元组:
            continue
        规则 = 校验器.校验规则表[规则版本]
        for 表 in 规则.get("表", []):
            消息 = _判定(lambda 表名=表: 校验器._校验表存在(连接, 表名))
            if 消息:
                问题列表.append(消息)
        for 表, 列 in 规则.get("列", []):
            消息 = _判定(lambda 表名=表, 列名=列: 校验器._校验列(连接, 表名, 列名))
            if 消息:
                问题列表.append(消息)
    return 问题列表


def 校验完整性(连接: sqlite3.Connection, 目标版本: str) -> list[str]:
    """调唯一判定（含 `PRAGMA integrity_check` 返回值判定）复核；返回仍存在的问题（空=通过）。"""
    校验器 = 借校验器()
    消息 = _判定(lambda: 校验器._校验版本结构(连接, 目标版本))
    return [消息] if 消息 else []


def 探查(库文件: Path, 目标版本: str) -> tuple[str, list[str]]:
    """只读探查一个状态库：返回 (库中结构版本, 问题列表)；读取类异常照原样上抛给能力层。"""
    连接 = 只读连接(库文件)
    try:
        库中结构版本 = 读库中结构版本(连接)
        问题列表 = 枚举结构问题(连接, 目标版本)
        if not 问题列表:
            问题列表 = 校验完整性(连接, 目标版本)
        return 库中结构版本, 问题列表
    finally:
        连接.close()
