"""项目文档支持库 · 索引库连接层（进程内共用，不对外暴露）。

**为什么单独成文件**：`索引库.py` 与 `未命中词.py` 共用同一个 SQLite 库文件，
若两边互相 import 会形成循环（实测：`ImportError: cannot import name '_连接'
from partially initialized module`）。把「库路径解析 + 连接 + 建表」这三件事
抽到本文件后，依赖是单向的：

    索引库.py ──┐
                ├──> 库连接.py
    未命中词.py ─┘

**口径**：库文件位置 = `<运行数据根>/项目文档库.db`（经唯一解析器，
禁止裸拼 `工程缓存`）。检索口径与记忆支持库「仅关键词」同哲学：
**默认纯 SQLite + 字符串匹配，不调用大模型与向量**。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from 公共契约.运行时.运行缓存 import 解析运行数据根

系统根 = Path(__file__).resolve().parents[4]
默认库文件 = 解析运行数据根(系统根) / "项目文档库.db"

建表语句 = (
    """CREATE TABLE IF NOT EXISTS 项目登记(
       项目名 TEXT PRIMARY KEY, 项目根目录 TEXT NOT NULL, 文档根相对路径 TEXT NOT NULL,
       规范文件 TEXT NOT NULL, 登记时间 TEXT NOT NULL, 更新时间 REAL NOT NULL);""",
    """CREATE TABLE IF NOT EXISTS 文档索引(
       项目名 TEXT NOT NULL, 文档相对路径 TEXT NOT NULL, 标题 TEXT NOT NULL,
       文档类型 TEXT NOT NULL, 内容摘要 TEXT NOT NULL, 段数 INTEGER NOT NULL,
       字节数 INTEGER NOT NULL, 文件修改时间 REAL NOT NULL, 入库时间 REAL NOT NULL,
       PRIMARY KEY(项目名, 文档相对路径));""",
    """CREATE TABLE IF NOT EXISTS 块索引(
       块id INTEGER PRIMARY KEY AUTOINCREMENT, 项目名 TEXT NOT NULL, 文档相对路径 TEXT NOT NULL,
       起始行 INTEGER NOT NULL, 结束行 INTEGER NOT NULL, 块类型 TEXT NOT NULL, 块文本 TEXT NOT NULL);""",
    # 未命中词表：与其余三表同库（不新建库文件），随第一次使用惰性建齐
    """CREATE TABLE IF NOT EXISTS 未命中词(
       项目名 TEXT NOT NULL, 原始词 TEXT NOT NULL, 建议词 TEXT NOT NULL,
       命中次数 INTEGER NOT NULL DEFAULT 0, 登记时间 REAL NOT NULL, 更新时间 REAL NOT NULL,
       PRIMARY KEY(项目名, 原始词));""",
    "CREATE INDEX IF NOT EXISTS 文档索引_项目_时间 ON 文档索引(项目名, 入库时间 DESC);",
    "CREATE INDEX IF NOT EXISTS 块索引_项目_文档 ON 块索引(项目名, 文档相对路径);",
    "CREATE INDEX IF NOT EXISTS 未命中词_项目_命中 ON 未命中词(项目名, 命中次数 DESC);",
)


def _库路径(库文件: str) -> Path:
    """归一化库文件参数：留空取默认；给值必须是绝对路径（相对路径一律拒绝）。"""
    if 库文件 is None or not str(库文件).strip():
        return 默认库文件
    文本 = str(库文件).strip()
    if not Path(文本).is_absolute():
        raise ValueError(f"库文件必须是绝对路径: {文本}")
    return Path(文本)


class _自动关闭连接(sqlite3.Connection):
    """`with` 退出时**真关闭**的连接（标准库 `with sqlite3.connect()` 只提交事务、不关连接）。

    ## 为什么必须有它（2026-09-20 实测的真 bug，不是设计取舍）
    全仓 15 处都写成 `with _连接(库文件) as 连接:`，但 `with` 原生 sqlite3.Connection
    **只做事务提交/回滚，不释放文件句柄**（实测：`with c:` 之后 `c.execute('SELECT 1')`
    仍可用）。⇒ 每调用一次泄漏一个 FD，WAL 模式下每个连接还额外占 -wal / -shm。

    现场证据：40007 常驻网关对 `工程缓存/运行数据/项目文档库.db` 持有 **123 个句柄**，
    进程总 FD 342 撞上 `launchctl maxfiles=256` 后，所有库操作稳定失败
    `索引库不可用：unable to open database file`，同时 `审计/安全审计.jsonl`
    也报 `Too many open files` —— 而磁盘、权限、直连写入全部正常。

    修在**唯一连接入口**而非逐个调用点：调用点不改一个字，也不会出现
    「有的地方关了、有的没关」的第二条腿。
    """

    def __exit__(self, 异常类型, 异常, 回溯) -> bool:  # type: ignore[override]
        结果 = super().__exit__(异常类型, 异常, 回溯)
        self.close()          # 关键：标准库不做这一步
        return 结果


def _连接(库文件: str) -> sqlite3.Connection:
    """打开库并确保表齐（幂等）；父目录不存在则创建（运行数据根可能尚未建）。

    返回 `_自动关闭连接`：调用方照旧 `with _连接(...) as 连接:` 即自动回收句柄。
    """
    路径 = _库路径(库文件)
    路径.parent.mkdir(parents=True, exist_ok=True)
    连接 = sqlite3.connect(路径, timeout=10, factory=_自动关闭连接)
    连接.execute("PRAGMA journal_mode=WAL")
    连接.execute("PRAGMA busy_timeout=10000")
    for 语句 in 建表语句:
        连接.execute(语句)
    连接.commit()
    return 连接
