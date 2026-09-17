"""项目文档支持库 · 索引库读写原子能力（进程内实现，不对外暴露）。

库文件位置：`<运行数据根>/项目文档库.db`（经唯一解析器，禁止裸拼 工程缓存）。
检索口径与记忆支持库「仅关键词」同哲学：**默认纯 SQLite + 字符串匹配，
不调用大模型与向量** —— 结构化查文档不该付一次 LLM 调用的代价。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
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
    "CREATE INDEX IF NOT EXISTS 文档索引_项目_时间 ON 文档索引(项目名, 入库时间 DESC);",
    "CREATE INDEX IF NOT EXISTS 块索引_项目_文档 ON 块索引(项目名, 文档相对路径);",
)


def _库路径(库文件: str) -> Path:
    """归一化库文件参数：留空取默认；给值必须是绝对路径（相对路径一律拒绝）。"""
    if 库文件 is None or not str(库文件).strip():
        return 默认库文件
    文本 = str(库文件).strip()
    if not Path(文本).is_absolute():
        raise ValueError(f"库文件必须是绝对路径: {文本}")
    return Path(文本)


def _连接(库文件: str) -> sqlite3.Connection:
    """打开库并确保表齐（幂等）；父目录不存在则创建（运行数据根可能尚未建）。"""
    路径 = _库路径(库文件)
    路径.parent.mkdir(parents=True, exist_ok=True)
    连接 = sqlite3.connect(路径, timeout=10)
    连接.execute("PRAGMA journal_mode=WAL")
    for 语句 in 建表语句:
        连接.execute(语句)
    连接.commit()
    return 连接


def 建索引库(库文件: str = None) -> 结果:
    """初始化项目文档索引库（三表 + 两个高频索引），重复调用保持幂等。

    参数：库文件（绝对路径；留空取运行数据根/项目文档库.db）
    返回：``{库文件, 已初始化, 表清单}``
    """
    try:
        with _连接(库文件) as 连接:
            表清单 = [行[0] for 行 in 连接.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return 结果.成功结果({"库文件": str(_库路径(库文件)), "已初始化": True, "表清单": 表清单})
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="项目文档支持库")
    except sqlite3.Error as 错误:
        return 结果.失败("索引库不可用", f"初始化失败: {错误}", 来源="项目文档支持库")


def 写入索引(项目名: str = None, 文档相对路径: str = None, 块列表: list = None,
            文件修改时间: float = 0, 库文件: str = None) -> 结果:
    """写入或更新一个文档的索引（文档级 + 块级），同项目同路径覆盖更新。

    参数：项目名 / 文档相对路径 / 块列表（切块结果）/ 文件修改时间 / 库文件
    返回：``{项目名, 文档相对路径, 块数, 标题, 段数}``
    """
    if not isinstance(项目名, str) or not 项目名.strip():
        return 结果.失败("参数不合法", "项目名必须是非空文本", 来源="项目文档支持库")
    if not isinstance(文档相对路径, str) or not 文档相对路径.strip():
        return 结果.失败("参数不合法", "文档相对路径必须是非空文本", 来源="项目文档支持库")
    if not isinstance(块列表, list):
        return 结果.失败("参数不合法", "块列表必须是列表", 来源="项目文档支持库")
    规范块 = []
    for 块 in 块列表:
        if not isinstance(块, dict):
            return 结果.失败("参数不合法", "块列表每项必须是对象", 来源="项目文档支持库")
        规范块.append((
            int(块.get("起始行") or 0), int(块.get("结束行") or 0),
            str(块.get("块类型") or "段落"), str(块.get("块文本") or "")))
    标题 = next((t[3].split("\n")[0].lstrip("# ").strip() for t in 规范块 if t[2] == "标题"), "")
    正文块 = [t for t in 规范块 if t[2] not in ("空行",)]
    段数 = len(正文块)
    字节数 = sum(len(t[3].encode("utf-8")) for t in 规范块)
    摘要 = " ".join(t[3].replace("\n", " ") for t in 正文块)[:400]

    try:
        import time
        with _连接(库文件) as 连接:
            连接.execute("DELETE FROM 块索引 WHERE 项目名=? AND 文档相对路径=?", (项目名, 文档相对路径))
            连接.executemany(
                "INSERT INTO 块索引(项目名,文档相对路径,起始行,结束行,块类型,块文本) VALUES(?,?,?,?,?,?)",
                [(项目名, 文档相对路径, s, e, k, t) for s, e, k, t in 规范块])
            连接.execute(
                """INSERT OR REPLACE INTO 文档索引
                   (项目名,文档相对路径,标题,文档类型,内容摘要,段数,字节数,文件修改时间,入库时间)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (项目名, 文档相对路径, 标题, "md", 摘要, 段数, 字节数,
                 float(文件修改时间 or 0), time.time()))
            连接.commit()
        return 结果.成功结果({"项目名": 项目名, "文档相对路径": 文档相对路径,
                            "块数": len(规范块), "标题": 标题, "段数": 段数})
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="项目文档支持库")
    except sqlite3.Error as 错误:
        return 结果.失败("索引库不可用", f"写入失败: {错误}", 来源="项目文档支持库")


def 查询索引(项目名: str = None, 关键词: str = None, 返回条数: int = 20,
            库文件: str = None) -> 结果:
    """按项目名与关键词查询块索引（大小写不敏感子串匹配）。

    多词查询：全命中优先，其次按命中词数降序、行号升序稳定排序。
    参数：项目名 / 关键词（空白分隔多词）/ 返回条数 / 库文件
    返回：``{项目名, 关键词, 命中列表, 命中数, 是否截断}``
    """
    if not isinstance(项目名, str) or not 项目名.strip():
        return 结果.失败("参数不合法", "项目名必须是非空文本", 来源="项目文档支持库")
    if not isinstance(关键词, str) or not 关键词.strip():
        return 结果.失败("参数不合法", "关键词必须是非空文本", 来源="项目文档支持库")
    词表 = [w for w in re.split(r"\s+", 关键词.strip()) if w]
    上限 = max(1, int(返回条数 or 20))
    try:
        with _连接(库文件) as 连接:
            行表 = 连接.execute(
                "SELECT 文档相对路径,起始行,结束行,块类型,块文本 FROM 块索引 WHERE 项目名=?",
                (项目名,)).fetchall()
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="项目文档支持库")
    except sqlite3.Error as 错误:
        return 结果.失败("索引库不可用", f"查询失败: {错误}", 来源="项目文档支持库")

    命中列表 = []
    for 路径, 起始行, 结束行, 块类型, 块文本 in 行表:
        小写 = 块文本.lower()
        命中词 = [w for w in 词表 if w.lower() in 小写]
        if not 命中词:
            continue
        片段 = 块文本.strip().replace("\n", " ")[:180]
        命中列表.append({
            "文档相对路径": 路径, "起始行": 起始行, "结束行": 结束行, "块类型": 块类型,
            "命中词数": len(命中词), "命中次数": sum(小写.count(w.lower()) for w in 命中词),
            "片段": 片段,
        })
    命中列表.sort(key=lambda x: (-x["命中词数"], -x["命中次数"], x["文档相对路径"], x["起始行"]))
    return 结果.成功结果({
        "项目名": 项目名, "关键词": 关键词, "命中列表": 命中列表[:上限],
        "命中数": len(命中列表), "是否截断": len(命中列表) > 上限,
    })
