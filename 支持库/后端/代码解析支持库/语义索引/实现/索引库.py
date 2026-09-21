"""语义索引的 SQLite 落点：建表、写入、读取、向量相似度与关键词精排打分。

职责边界（为什么单独成文件）：
- 本文件只管「块怎么落库、怎么读回来、怎么算分」，**不碰嵌入模型也不碰切块**；
  嵌入句柄与缓存归 `实现/嵌入.py`，目录遍历与切块归 `实现/切块.py`。
- 全部函数只接受已打开的连接，连接生命周期由调用方（`实现/语义索引.py`）收口，
  避免同一库被两处各建一套连接。

关键词精排口径（为什么不是纯向量）：
- 向量召回宽、关键词精排严。符号名（如 `正则搜索`）在自然语言向量里会被稀释，
  但对代码检索来说符号命中是强证据；故分数 = 向量分 * 0.7 + 关键词分 * 0.3，
  且完全无关键词命中时关键词分不参与抬分（不造假命中）。
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

建表语句表 = [
    """CREATE TABLE IF NOT EXISTS 代码块(
        块id INTEGER PRIMARY KEY AUTOINCREMENT,
        文件路径 TEXT NOT NULL,
        起始行 INTEGER NOT NULL,
        结束行 INTEGER NOT NULL,
        块类型 TEXT NOT NULL,
        块文本 TEXT NOT NULL,
        块摘要 TEXT NOT NULL,
        向量 TEXT NOT NULL,
        模型名 TEXT NOT NULL DEFAULT '',
        写入时间 TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS 代码块_文件 ON 代码块(文件路径)",
    "CREATE INDEX IF NOT EXISTS 代码块_摘要 ON 代码块(块摘要)",
]

向量权重 = 0.7
关键词权重 = 0.3


def 打开库(库文件: str) -> sqlite3.Connection:
    """打开（并按需创建）索引库，建表幂等。"""
    目标 = Path(库文件).expanduser()
    目标.parent.mkdir(parents=True, exist_ok=True)
    连接 = sqlite3.connect(str(目标), timeout=15)
    连接.row_factory = sqlite3.Row
    for 语句 in 建表语句表:
        连接.execute(语句)
    连接.commit()
    return 连接


def 清空索引(连接: sqlite3.Connection) -> None:
    """重建索引前清空旧块（同一库文件重复索引不残留旧行）。"""
    连接.execute("DELETE FROM 代码块")
    连接.commit()


def 写块批(连接: sqlite3.Connection, 记录列表: list[dict], 写入时间: str) -> int:
    """按批写入块记录（单事务）；返回写入条数。"""
    if not 记录列表:
        return 0
    行列表 = [
        (记录["文件路径"], int(记录["起始行"]), int(记录["结束行"]), 记录["块类型"],
         记录["块文本"], 记录["块摘要"], json.dumps(记录["向量"], ensure_ascii=False),
         记录.get("模型名", ""), 写入时间)
        for 记录 in 记录列表
    ]
    with 连接:
        连接.executemany(
            "INSERT INTO 代码块(文件路径, 起始行, 结束行, 块类型, 块文本, 块摘要, 向量, 模型名, 写入时间)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 行列表)
    return len(行列表)


def 读全部块(连接: sqlite3.Connection) -> list[dict]:
    """读出全部块（含向量），按 文件路径 + 起始行 稳定排序。"""
    行集 = 连接.execute(
        "SELECT 文件路径, 起始行, 结束行, 块类型, 块文本, 块摘要, 向量 FROM 代码块"
        " ORDER BY 文件路径, 起始行, 块id").fetchall()
    块列表 = []
    for 行 in 行集:
        try:
            向量 = json.loads(行["向量"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(向量, list) or not 向量:
            continue
        块列表.append({"文件路径": 行["文件路径"], "起始行": 行["起始行"], "结束行": 行["结束行"],
                       "块类型": 行["块类型"], "块文本": 行["块文本"], "块摘要": 行["块摘要"],
                       "向量": 向量})
    return 块列表


def 块总数(连接: sqlite3.Connection) -> int:
    行 = 连接.execute("SELECT COUNT(*) FROM 代码块").fetchone()
    return int(行[0]) if 行 else 0


def 余弦相似度(左向量: list, 右向量: list) -> float:
    """余弦相似度；任一向量零模长返回 0.0（不抛异常、不造假）。"""
    if len(左向量) != len(右向量):
        return 0.0
    点积 = sum(左值 * 右值 for 左值, 右值 in zip(左向量, 右向量))
    左模 = math.sqrt(sum(值 * 值 for 值 in 左向量))
    右模 = math.sqrt(sum(值 * 值 for 值 in 右向量))
    if 左模 == 0 or 右模 == 0:
        return 0.0
    return 点积 / (左模 * 右模)


def _词元表(查询: str) -> list[str]:
    """把查询拆成检索词元：空白切分 + 中文滑窗双字词；去重保序。"""
    词元列表: list[str] = []
    for 片段 in 查询.replace("\n", " ").split():
        片段 = 片段.strip("，。、；：（）()[]{}\"'`")
        if not 片段:
            continue
        if 片段 not in 词元列表:
            词元列表.append(片段)
        if len(片段) >= 2:
            for 序号 in range(len(片段) - 1):
                双字 = 片段[序号:序号 + 2]
                if 双字 not in 词元列表:
                    词元列表.append(双字)
    return 词元列表


def 关键词分数(查询: str, 块文本: str) -> float:
    """关键词／符号命中率：命中词元数 / 词元总数（0.0~1.0）。

    完全无命中时返回 0.0 —— 调用方据此**不抬分**，避免把「向量碰巧相近」
    当成关键词命中。
    """
    词元列表 = _词元表(查询)
    if not 词元列表 or not 块文本:
        return 0.0
    命中数 = sum(1 for 词元 in 词元列表 if 词元 in 块文本)
    return 命中数 / len(词元列表)


def 综合分数(向量分数: float, 词分数: float) -> float:
    """向量分与关键词分的加权综合（召回宽、精排严的量化口径）。"""
    return 向量权重 * 向量分数 + 关键词权重 * 词分数


def 截取片段(块文本: str, 上限: int = 200) -> str:
    """候选片段：压平空白并截断，只作展示，不作事实来源。"""
    压平 = " ".join(块文本.split())
    return 压平[:上限] + ("…" if len(压平) > 上限 else "")


__all__ = [
    "打开库", "清空索引", "写块批", "读全部块", "块总数",
    "余弦相似度", "关键词分数", "综合分数", "截取片段",
]
