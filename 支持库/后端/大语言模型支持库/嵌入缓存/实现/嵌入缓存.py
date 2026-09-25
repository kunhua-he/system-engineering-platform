"""嵌入缓存原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：文本嵌入向量的缓存读写。缓存键 = 文本哈希 + 模型名 + 提供者。
存储：SQLite（缓存表），路径由 配置契约/配置契约.json 提供，默认 工程缓存/大语言模型支持库.嵌入缓存.db。
策略：查询命中直接返回缓存向量；未命中返回 缓存未命中，由调用方决定是否重新嵌入后 存储嵌入。
边界：只做缓存读写，不调用任何嵌入模型；嵌入生成是调用方/提供者职责。
全部能力返回统一结果（成功/值/错误码/错误说明）；参数非法返回 参数不合法。
"""

from __future__ import annotations

import atexit
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.运行缓存 import 解析运行缓存根, 解析运行数据根
from 公共契约.运行时.导入前缀 import 取系统根
from 公共契约.运行时.数据库连接 import 打开可写

# ---- 默认配置（可由 配置契约 覆盖）----
默认缓存目录 = 解析运行缓存根(取系统根(__file__))
默认数据库路径 = 解析运行数据根(取系统根(__file__)) / "大语言模型支持库.嵌入缓存.db"

_连接: sqlite3.Connection | None = None
_连接路径: Path | None = None
_连接锁 = threading.RLock()



降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程）


def _关闭连接() -> None:
    """进程退出时关闭内部 SQLite 连接，避免泄漏资源。"""
    global _连接, _连接路径
    with _连接锁:
        if _连接 is None:
            return
        try:
            _连接.close()
        finally:
            _连接 = None
            _连接路径 = None


atexit.register(_关闭连接)

def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="嵌入缓存")


def _取连接(数据库路径: str | Path | None = None) -> sqlite3.Connection:
    global _连接, _连接路径
    目标 = Path(数据库路径) if 数据库路径 else 默认数据库路径
    if _连接 is not None and _连接路径 == 目标:
        return _连接
    if _连接 is not None:
        try:
            _连接.close()
        except Exception as 错误:
            降级记录表.append(str(错误))
    目标.parent.mkdir(parents=True, exist_ok=True)
    # 转调 `公共契约/运行时/数据库连接.py`，原参数 timeout=10、check_same_thread=False → 写路径档
    # `打开可写(..., 跨线程=True)`（此处建表，属初始化写路径）
    _连接 = 打开可写(str(目标), 10, 跨线程=True)
    _连接.execute(
        "CREATE TABLE IF NOT EXISTS 嵌入缓存 ("
        " 缓存键 TEXT PRIMARY KEY, 文本哈希 TEXT NOT NULL, 模型名 TEXT NOT NULL,"
        " 提供者 TEXT NOT NULL, 向量 TEXT NOT NULL, 创建时间 TEXT NOT NULL)"
    )
    _连接.commit()
    _连接路径 = 目标
    return _连接


def _缓存键(文本: str, 模型名: str, 提供者: str) -> str:
    摘要 = hashlib.sha256(文本.encode("utf-8")).hexdigest()
    return f"{提供者}|{模型名}|{摘要}"


def 查询嵌入(文本: str = None, 模型名: str = None, 提供者: str = None, 数据库路径: str = None) -> 结果:
    """按 文本+模型名+提供者 查询缓存嵌入向量。命中返回 {值=向量列表}；未命中返回 缓存未命中。"""
    if not isinstance(文本, str) or not 文本.strip():
        return _失败("参数不合法", "文本必须是非空字符串")
    if not isinstance(模型名, str) or not 模型名.strip():
        return _失败("参数不合法", "模型名必须是非空字符串")
    if not isinstance(提供者, str) or not 提供者.strip():
        return _失败("参数不合法", "提供者必须是非空字符串")
    try:
        with _连接锁:
            连接 = _取连接(数据库路径)
            键 = _缓存键(文本, 模型名, 提供者)
            行 = 连接.execute(
                "SELECT 向量 FROM 嵌入缓存 WHERE 缓存键 = ?", (键,)
            ).fetchone()
            if 行 is None:
                return 结果.成功结果({"命中": False, "向量": None})
            向量 = json.loads(行[0])
            return 结果.成功结果({"命中": True, "向量": 向量})
    except sqlite3.Error as 错误:
        return _失败("缓存查询失败", f"查询嵌入缓存失败: {错误}")


def 存储嵌入(文本: str = None, 向量: list = None, 模型名: str = None, 提供者: str = None, 数据库路径: str = None) -> 结果:
    """存储一条嵌入缓存。已存在同键则覆盖（同文本同模型同提供者的向量更新）。"""
    if not isinstance(文本, str) or not 文本.strip():
        return _失败("参数不合法", "文本必须是非空字符串")
    if not isinstance(向量, list):
        return _失败("参数不合法", "向量必须是列表")
    if not isinstance(模型名, str) or not 模型名.strip():
        return _失败("参数不合法", "模型名必须是非空字符串")
    if not isinstance(提供者, str) or not 提供者.strip():
        return _失败("参数不合法", "提供者必须是非空字符串")
    try:
        with _连接锁:
            连接 = _取连接(数据库路径)
            键 = _缓存键(文本, 模型名, 提供者)
            连接.execute(
                "INSERT OR REPLACE INTO 嵌入缓存 (缓存键, 文本哈希, 模型名, 提供者, 向量, 创建时间)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (键, hashlib.sha256(文本.encode("utf-8")).hexdigest(), 模型名, 提供者,
                 json.dumps(向量, ensure_ascii=False), __import__("datetime").datetime.now().isoformat()),
            )
            连接.commit()
            return 结果.成功结果({"已存储": True, "缓存键": 键})
    except sqlite3.Error as 错误:
        return _失败("缓存写入失败", f"写入嵌入缓存失败: {错误}")


def 统计缓存(数据库路径: str = None) -> 结果:
    """返回缓存条目总数。"""
    try:
        with _连接锁:
            连接 = _取连接(数据库路径)
            行 = 连接.execute("SELECT COUNT(*) FROM 嵌入缓存").fetchone()
            return 结果.成功结果({"缓存数": 行[0] if 行 else 0})
    except sqlite3.Error as 错误:
        return _失败("缓存查询失败", f"统计嵌入缓存失败: {错误}")


def 清空缓存(数据库路径: str = None) -> 结果:
    """清空全部缓存条目（只删缓存表数据，不动业务数据）。"""
    try:
        with _连接锁:
            连接 = _取连接(数据库路径)
            连接.execute("DELETE FROM 嵌入缓存")
            连接.commit()
            return 结果.成功结果({"已清空": True})
    except sqlite3.Error as 错误:
        return _失败("缓存写入失败", f"清空嵌入缓存失败: {错误}")
