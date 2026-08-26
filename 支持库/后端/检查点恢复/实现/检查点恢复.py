"""检查点恢复原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：会话检查点的保存/恢复（借鉴 DeepSeek fail-closed 检查点语义，保持原子）。
检查点 = {会话id, 状态快照(dict), 版本, 时间戳}，存 SQLite（默认 工程缓存/检查点.db）。
保存后返回检查点id；恢复时按 会话id 取最新检查点。
只做存取，不做业务；失败不伪绿。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid

from 公共契约.基础类型.结果类型 import 结果

默认库路径 = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "工程缓存", "检查点.db")
锁 = __import__("threading").Lock()


def _连接(库路径: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(库路径), exist_ok=True)
    连接 = sqlite3.connect(库路径, timeout=5)
    连接.execute("""CREATE TABLE IF NOT EXISTS 检查点 (
        检查点id TEXT PRIMARY KEY,
        会话id TEXT NOT NULL,
        状态快照 TEXT NOT NULL,
        版本 TEXT DEFAULT '1.0.0',
        创建时间 TEXT NOT NULL
    )""")
    连接.execute("CREATE INDEX IF NOT EXISTS idx_检查点_会话 ON 检查点(会话id, 创建时间)")
    连接.commit()
    return 连接


def 保存检查点(会话id: str = None, 状态快照: dict = None, 版本: str = None, 库路径: str = None) -> 结果:
    """保存会话检查点。返回 {检查点id, 会话id, 版本}。"""
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="检查点恢复")
    if not isinstance(状态快照, dict):
        return 结果.失败("参数不合法", "状态快照必须是字典型", 来源="检查点恢复")
    检查点id = uuid.uuid4().hex[:16]
    路径 = 库路径 or 默认库路径
    快照文本 = json.dumps(状态快照, ensure_ascii=False)
    try:
        with 锁, _连接(路径) as 连接:
            连接.execute("INSERT INTO 检查点 VALUES (?,?,?,?,?)",
                         (检查点id, 会话id, 快照文本, 版本 or "1.0.0",
                          time.strftime("%Y-%m-%d %H:%M:%S")))
        return 结果.成功结果({"检查点id": 检查点id, "会话id": 会话id, "版本": 版本 or "1.0.0"})
    except Exception as 错误:
        return 结果.失败("保存检查点失败", str(错误), 来源="检查点恢复")


def 恢复检查点(会话id: str = None, 库路径: str = None) -> 结果:
    """恢复会话最新检查点。返回 {检查点id, 状态快照, 版本, 创建时间}。"""
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="检查点恢复")
    路径 = 库路径 or 默认库路径
    if not os.path.isfile(路径):
        return 结果.成功结果({"检查点id": "", "已找到": False, "状态快照": None})
    try:
        with 锁, _连接(路径) as 连接:
            行 = 连接.execute(
                "SELECT 检查点id, 状态快照, 版本, 创建时间 FROM 检查点 "
                "WHERE 会话id=? ORDER BY 创建时间 DESC, 检查点id DESC LIMIT 1",
                (会话id,)).fetchone()
        if 行 is None:
            return 结果.成功结果({"检查点id": "", "已找到": False, "状态快照": None})
        return 结果.成功结果({
            "检查点id": 行[0], "已找到": True, "状态快照": json.loads(行[1]),
            "版本": 行[2], "创建时间": 行[3],
        })
    except Exception as 错误:
        return 结果.失败("恢复检查点失败", str(错误), 来源="检查点恢复")
