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
        创建时间 TEXT NOT NULL,
        中断原因 TEXT,
        中断状态 TEXT DEFAULT '正常'
    )""")
    连接.execute("CREATE INDEX IF NOT EXISTS idx_检查点_会话 ON 检查点(会话id, 创建时间)")
    连接.commit()
    # 兼容旧库：幂等补 中断 列（已有则忽略）
    try:
        连接.execute("ALTER TABLE 检查点 ADD COLUMN 中断原因 TEXT")
        连接.execute("ALTER TABLE 检查点 ADD COLUMN 中断状态 TEXT DEFAULT '正常'")
        连接.commit()
    except Exception:
        pass
    return 连接


def 保存检查点(会话id: str = None, 状态快照: dict = None, 版本: str = None, 库路径: str = None, 中断原因: str = None) -> 结果:
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
            连接.execute("INSERT INTO 检查点 VALUES (?,?,?,?,?,?,?)",
                          (检查点id, 会话id, 快照文本, 版本 or "1.0.0",
                           time.strftime("%Y-%m-%d %H:%M:%S"),
                           中断原因 or "", "中断" if 中断原因 else "正常"))
        返回值 = {"检查点id": 检查点id, "会话id": 会话id, "版本": 版本 or "1.0.0"}
        if 库路径:
            返回值["库路径"] = 路径
        return 结果.成功结果(返回值)
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



# ═══════════════════════════════════════════════
# 中断-续跑：Coze checkpoint 中断恢复机制模式化落地
# 中断（登记中断，带中断原因/中断id）→ 外部动作（授权/审批/人工确认）→ 续跑（带中断id校验恢复）。
# 0加密0限制：状态快照/中断原因原文存取，业务端自理敏感处理。
# ═══════════════════════════════════════════════
def 登记中断(会话id: str = None, 状态快照: dict = None, 中断原因: str = None,
           版本: str = None, 库路径: str = None) -> 结果:
    """登记会话中断：保存检查点+中断原因，返回中断id（Coze InterruptID 语义）。"""
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="检查点恢复")
    if not isinstance(状态快照, dict):
        return 结果.失败("参数不合法", "状态快照必须是字典型", 来源="检查点恢复")
    if not isinstance(中断原因, str) or not 中断原因.strip():
        return 结果.失败("参数不合法", "中断原因不能为空", 来源="检查点恢复")
    结果1 = 保存检查点(会话id=会话id, 状态快照=状态快照, 版本=版本, 库路径=库路径, 中断原因=中断原因)
    if not 结果1.成功:
        return 结果1
    检查点id = 结果1.值["检查点id"]
    return 结果.成功结果({
        "中断id": 检查点id, "会话id": 会话id, "中断原因": 中断原因,
        "状态": "已中断", "待外部动作": True,
    })


def 续跑检查点(会话id: str = None, 中断id: str = None, 库路径: str = None) -> 结果:
    """带中断id续跑：校验中断存在 → 恢复状态快照 → 标记已续跑。"""
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="检查点恢复")
    if not isinstance(中断id, str) or not 中断id.strip():
        return 结果.失败("参数不合法", "中断id不能为空", 来源="检查点恢复")
    路径 = 库路径 or 默认库路径
    if not os.path.isfile(路径):
        return 结果.失败("中断不存在", f"会话 {会话id} 无中断记录", 来源="检查点恢复")
    try:
        with 锁, _连接(路径) as 连接:
            行 = 连接.execute(
                "SELECT 检查点id, 状态快照, 版本, 创建时间, 中断原因, 中断状态 "
                "FROM 检查点 WHERE 会话id=? AND 检查点id=? AND 中断状态='中断'",
                (会话id, 中断id)).fetchone()
            if 行 is None:
                return 结果.失败("中断不存在或已续跑",
                                 f"会话 {会话id} 中断 {中断id} 不存在或已续跑", 来源="检查点恢复")
            # 标记已续跑（原子，幂等：只有中断状态才更新）
            连接.execute("UPDATE 检查点 SET 中断状态='已续跑' WHERE 检查点id=?", (中断id,))
        return 结果.成功结果({
            "中断id": 行[0], "已恢复": True, "状态快照": json.loads(行[1]),
            "版本": 行[2], "创建时间": 行[3], "中断原因": 行[4],
            "状态": "已续跑", "待外部动作": False,
        })
    except Exception as 错误:
        return 结果.失败("续跑失败", str(错误), 来源="检查点恢复")


def 查询中断(会话id: str = None, 库路径: str = None) -> 结果:
    """查询会话当前未续跑的中断（外部动作完成后据此续跑）。"""
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="检查点恢复")
    路径 = 库路径 or 默认库路径
    if not os.path.isfile(路径):
        return 结果.成功结果({"会话id": 会话id, "有中断": False, "中断列表": []})
    try:
        with 锁, _连接(路径) as 连接:
            行们 = 连接.execute(
                "SELECT 检查点id, 中断原因, 版本, 创建时间 FROM 检查点 "
                "WHERE 会话id=? AND 中断状态='中断' ORDER BY 创建时间 DESC",
                (会话id,)).fetchall()
        return 结果.成功结果({
            "会话id": 会话id, "有中断": bool(行们), "中断数": len(行们),
            "中断列表": [{"中断id": r[0], "中断原因": r[1], "版本": r[2], "创建时间": r[3]} for r in 行们],
        })
    except Exception as 错误:
        return 结果.失败("查询中断失败", str(错误), 来源="检查点恢复")
