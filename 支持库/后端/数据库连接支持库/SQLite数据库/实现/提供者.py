"""SQLite 数据库提供者：真实文件数据库连接/查询/事务/关闭。

只使用 Python 标准库 sqlite3；每次公开能力自包含连接生命周期，
连接在 finally 中关闭，不向调用方暴露连接对象、游标或线程。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

来源 = "SQLite数据库提供者"
错误码_参数不合法 = "参数不合法"
错误码_提供者不可用 = "提供者不可用"
错误码_连接失败 = "连接失败"
错误码_查询失败 = "查询失败"
错误码_事务失败 = "事务失败"


def _失败(错误码: str, 说明: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 说明, 来源=来源, 可重试=可重试)


def _校验路径(数据库路径: Any) -> str | None:
    if not isinstance(数据库路径, str) or not 数据库路径.strip():
        return None
    return str(Path(数据库路径).expanduser())


def _校验超时(超时秒: Any) -> str | None:
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return "超时秒必须是正数"
    return None


def _打开(数据库路径: str, 超时秒: float) -> sqlite3.Connection:
    路径 = Path(数据库路径)
    路径.parent.mkdir(parents=True, exist_ok=True)
    连接对象 = sqlite3.connect(str(路径), timeout=float(超时秒))
    连接对象.execute("PRAGMA busy_timeout = 5000")
    连接对象.execute("PRAGMA journal_mode = WAL")
    连接对象.execute("PRAGMA synchronous = NORMAL")
    return 连接对象


def 连接(数据库路径: str, 超时秒: float = 10) -> 结果:
    """真实打开 SQLite 数据库并完成基础连接探针，随后关闭连接。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        连接对象.execute("SELECT 1").fetchone()
        return 结果.成功结果({"已连接": True, "数据库路径": 路径})
    except sqlite3.Error as 错误:
        return _失败(错误码_连接失败, f"SQLite 数据库连接失败：{错误}", 可重试=True)
    finally:
        if 连接对象 is not None:
            连接对象.close()


def 查询(数据库路径: str, SQL: str, 参数: list | tuple | None = None,
         超时秒: float = 30) -> 结果:
    """执行只读查询，返回列名到值的行列表。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if not isinstance(SQL, str) or not SQL.strip():
        return _失败(错误码_参数不合法, "SQL 必须是非空文本")
    if 参数 is not None and not isinstance(参数, (list, tuple)):
        return _失败(错误码_参数不合法, "参数必须是列表或元组")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        游标 = 连接对象.execute(SQL, tuple(参数 or ()))
        列名表 = [描述[0] for 描述 in (游标.description or [])]
        行列表 = [dict(zip(列名表, 行)) for 行 in 游标.fetchall()]
        return 结果.成功结果({"行列表": 行列表})
    except sqlite3.Error as 错误:
        return _失败(错误码_查询失败, f"SQLite 查询失败：{错误}")
    finally:
        if 连接对象 is not None:
            连接对象.close()


def 事务执行(数据库路径: str, SQL列表: list, 超时秒: float = 30) -> 结果:
    """在一个真实事务内执行 SQL 列表；任一失败全部回滚。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    if not isinstance(SQL列表, list) or not SQL列表:
        return _失败(错误码_参数不合法, "SQL列表 必须是非空列表")
    if any(not isinstance(SQL, str) or not SQL.strip() for SQL in SQL列表):
        return _失败(错误码_参数不合法, "SQL列表 中每项必须是非空文本")
    连接对象 = None
    try:
        连接对象 = _打开(路径, float(超时秒))
        连接对象.execute("BEGIN IMMEDIATE")
        for SQL in SQL列表:
            连接对象.execute(SQL)
        连接对象.commit()
        return 结果.成功结果({"已提交": True, "执行数": len(SQL列表)})
    except sqlite3.Error as 错误:
        if 连接对象 is not None:
            连接对象.rollback()
        return _失败(错误码_事务失败, f"SQLite 事务失败，已回滚：{错误}")
    finally:
        if 连接对象 is not None:
            连接对象.close()


def 关闭(数据库路径: str, 超时秒: float = 5) -> 结果:
    """关闭能力：连接每次调用结束即释放，返回真实关闭语义。"""
    路径 = _校验路径(数据库路径)
    if 路径 is None:
        return _失败(错误码_参数不合法, "数据库路径必须是非空文本")
    if (问题 := _校验超时(超时秒)):
        return _失败(错误码_参数不合法, 问题)
    return 结果.成功结果({"已关闭": True, "说明": "SQLite 连接随能力调用结束自动释放"})


__all__ = ["连接", "查询", "事务执行", "关闭"]
