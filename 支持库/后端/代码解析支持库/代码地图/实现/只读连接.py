"""代码地图只读连接：只读打开代码地图 SQLite，不写库、不在索引目录建 side 文件。

代码地图是外部 CLI 产出的索引，对底座而言是**只读外部资料**：

1. 一律用 `mode=ro&immutable=1` URI 打开。实测（2026-09-15）WAL 库上用 `mode=ro`
   会在索引目录里生成 `codegraph.db-shm`（32768 字节）与 `codegraph.db-wal`，
   等于向别人的索引目录写盘；`immutable=1` 不建锁、不建 side 文件、不加锁。
2. 不缓存连接：每次调用新建、finally 关闭，避免句柄泄漏与跨调用脏状态。

只依赖 Python 标准库（sqlite3）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

来源 = "代码地图"
必需表表 = ("nodes", "edges")


def 只读URI(路径: Path) -> str:
    """代码地图只读 URI：绝对路径 as_uri()（自动百分号转义）+ 只读不可变参数。"""
    return 路径.resolve().as_uri() + "?mode=ro&immutable=1"


def 打开代码地图(代码地图路径: str) -> 结果:
    """只读打开代码地图并校验必需表；返回 结果[连接]。"""
    路径 = Path(str(代码地图路径))
    if not 路径.is_file():
        return 结果.失败("文件不存在", f"代码地图文件不存在: {路径}", 来源=来源)
    try:
        连接 = sqlite3.connect(只读URI(路径), uri=True, timeout=5.0)
        连接.row_factory = sqlite3.Row
        缺表 = [表 for 表 in 必需表表 if not _有表(连接, 表)]
    except sqlite3.Error as 错误:
        return 结果.失败("查询失败", f"代码地图打开失败: {错误}", 来源=来源)
    if 缺表:
        连接.close()
        return 结果.失败("查询失败", f"代码地图缺少表: {'、'.join(缺表)}", 来源=来源)
    return 结果.成功结果(连接)


def 关闭代码地图(连接: object) -> None:
    """关闭连接（幂等；异常不外抛，避免掩盖真实错误码）。"""
    try:
        if isinstance(连接, sqlite3.Connection):
            连接.close()
    except sqlite3.Error:
        pass


def _有表(连接: sqlite3.Connection, 表名: str) -> bool:
    行 = 连接.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (表名,)
    ).fetchone()
    return 行 is not None
