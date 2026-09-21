"""仓库地图 SQLite 读写：表结构与 代码地图 的 nodes/edges **同构**。

同构口径（既有只读消费者 `代码解析支持库.代码地图` 可直接读本库）：

- nodes 列：id/kind/name/qualified_name/file_path/language/start_line/end_line/
  is_exported/signature/docstring
- edges 列：source/target/kind/line

本包在 edges 上**多一列 weight**（「加权有向图」的载体）。额外列不改变既有
SELECT 列表，故 代码地图.查询节点/查询关系 对本库仍可用。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

来源 = "仓库地图"
必需表表 = ("nodes", "edges")
#: 支持库/后端/代码解析支持库/仓库地图/实现/图库.py → parents[5] = 系统工程平台
平台根 = Path(__file__).resolve().parents[5]

建表语句表 = (
    "CREATE TABLE nodes ("
    " id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,"
    " qualified_name TEXT, file_path TEXT, language TEXT,"
    " start_line INTEGER, end_line INTEGER, is_exported INTEGER DEFAULT 0,"
    " signature TEXT, docstring TEXT)",
    "CREATE TABLE edges ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,"
    " target TEXT NOT NULL, kind TEXT NOT NULL, line INTEGER,"
    " weight REAL NOT NULL DEFAULT 1)",
    "CREATE INDEX idx_仓库地图_nodes_路径 ON nodes (file_path, start_line)",
    "CREATE INDEX idx_仓库地图_nodes_名称 ON nodes (name)",
    "CREATE INDEX idx_仓库地图_edges_起点 ON edges (source, kind)",
    "CREATE INDEX idx_仓库地图_edges_终点 ON edges (target, kind)",
)

节点列 = ("id, kind, name, qualified_name, file_path, language, start_line, "
          "end_line, is_exported, signature, docstring")


def 默认库文件(仓库根: str) -> Path:
    """默认落点：<平台根>/工程缓存/仓库地图/<仓名>.db。"""
    仓名 = Path(仓库根).resolve().name or "仓库"
    return 平台根 / "工程缓存" / "仓库地图" / f"{仓名}.db"


def 落点(仓库根: str, 库文件: str) -> Path:
    """库文件参数为空时取默认落点。"""
    return Path(库文件).expanduser() if 库文件 else 默认库文件(仓库根)


def 建库(路径: Path) -> 结果:
    """新建（或整表重建）仓库地图库；返回 结果[连接]。"""
    try:
        路径.parent.mkdir(parents=True, exist_ok=True)
        if 路径.exists():
            路径.unlink()
        连接 = sqlite3.connect(str(路径), timeout=15.0)
        连接.row_factory = sqlite3.Row
        for 语句 in 建表语句表:
            连接.execute(语句)
        连接.commit()
    except (OSError, sqlite3.Error) as 错误:
        return 结果.失败("写入失败", f"仓库地图落盘失败: {错误}", 来源=来源)
    return 结果.成功结果(连接)


def 只读打开(路径: Path) -> 结果:
    """只读打开仓库地图库并校验必需表；返回 结果[连接]。

    用 `只读库URI实参`（mode=ro&immutable=1）：不在库目录留 -shm/-wal side 文件。
    """
    from 公共契约.运行时.数据库URI import 只读库URI实参

    if not 路径.is_file():
        return 结果.失败("文件不存在", f"仓库地图文件不存在: {路径}", 来源=来源)
    try:
        连接 = sqlite3.connect(只读库URI实参(路径), uri=True, timeout=5.0)
        连接.row_factory = sqlite3.Row
        缺表 = [表 for 表 in 必需表表 if not _有表(连接, 表)]
    except sqlite3.Error as 错误:
        return 结果.失败("查询失败", f"仓库地图打开失败: {错误}", 来源=来源)
    if 缺表:
        连接.close()
        return 结果.失败("查询失败", f"仓库地图缺少表: {'、'.join(缺表)}", 来源=来源)
    return 结果.成功结果(连接)


def 关闭(连接: object) -> None:
    """关闭连接（幂等；异常不外抛，避免掩盖真实错误码）。"""
    try:
        if isinstance(连接, sqlite3.Connection):
            连接.close()
    except sqlite3.Error:
        pass


def 写入(连接: sqlite3.Connection, 节点表: list[dict], 边表: list[dict]) -> 结果:
    """一个事务写入全部节点与边；失败整体回滚。"""
    try:
        连接.executemany(
            f"INSERT OR REPLACE INTO nodes ({节点列}) VALUES (:id, :kind, :name, "
            ":qualified_name, :file_path, :language, :start_line, :end_line, "
            ":is_exported, :signature, :docstring)",
            节点表,
        )
        连接.executemany(
            "INSERT INTO edges (source, target, kind, line, weight) "
            "VALUES (:source, :target, :kind, :line, :weight)",
            边表,
        )
        连接.commit()
    except sqlite3.Error as 错误:
        连接.rollback()
        return 结果.失败("写入失败", f"仓库地图写入失败: {错误}", 来源=来源)
    return 结果.成功结果()


def 读节点(连接: sqlite3.Connection) -> list[dict]:
    """按 文件路径、起始行、名称 稳定排序读全部节点。"""
    行表 = 连接.execute(
        f"SELECT {节点列} FROM nodes ORDER BY file_path, start_line, name"
    ).fetchall()
    return [dict(行) for 行 in 行表]


def 读边(连接: sqlite3.Connection) -> list[dict]:
    """读全部边（source/target/kind/line/weight），按起点稳定排序。"""
    行表 = 连接.execute(
        "SELECT source, target, kind, line, weight FROM edges "
        "ORDER BY source, kind, target"
    ).fetchall()
    return [dict(行) for 行 in 行表]


def _有表(连接: sqlite3.Connection, 表名: str) -> bool:
    行 = 连接.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (表名,)
    ).fetchone()
    return 行 is not None
