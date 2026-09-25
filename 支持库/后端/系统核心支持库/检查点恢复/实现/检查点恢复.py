"""检查点恢复原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：会话检查点的保存/恢复（借鉴 DeepSeek fail-closed 检查点语义，保持原子）。
检查点 = {会话id, 状态快照(dict), 版本, 时间戳}，存 SQLite（默认 工程缓存/检查点.db）。
保存后返回检查点id；恢复时按 会话id 取最新检查点。
只做存取，不做业务；失败不伪绿。
"""

from __future__ import annotations
from pathlib import Path

import atexit
import json
import os
import sqlite3
import time
import uuid

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.运行缓存 import 解析运行数据根
from 公共契约.运行时.导入前缀 import 取系统根
from 公共契约.运行时.数据库连接 import 打开可写

默认库路径 = str(解析运行数据根(取系统根(__file__)) / "检查点.db")
锁 = __import__("threading").Lock()
# 补列等容错路径的问题留痕（哲学第 3 条 2 项：失败必须可见，不许 except: pass 吞掉）
补列问题: list[str] = []
# 连接关闭等容错路径的问题留痕（同上：不许静默）
连接问题: list[str] = []

# ── 建连层：模块级缓存连接，调用点一行不改（照 嵌入缓存.py:27-74）──────────────
# 为什么必须收敛到这里：sqlite3.Connection 的 `with` 是**事务**上下文（__exit__ 只
# commit/rollback），不是关闭器 —— 原实现每次调用都新建连接且永不 close，fd 只能等
# GC（严格 1:1 泄漏）。改为「按 库路径 缓存连接」后：
#   · 调用点 `with 锁, _连接(路径) as 连接:` 形态与事务语义完全不变（退出即 commit、
#     异常即 rollback），因此本模块 10 个调用点一行都不用改；
#   · 连接由本层持有，进程内 fd 不再随调用次数增长，进程退出由 atexit 收口。
# 三条护栏：① 换库路径先关旧连接（检查点库/任务库各自独立一槽，互不干扰）；
# ② 记录缓存所属进程 id，fork 出的子进程不复用父进程连接（sqlite 连接跨进程不安全）;
# ③ 缓存库文件被外部删除或**被替换**（换 inode，如从备份恢复覆盖）时重开，
#    绝不把连接挂在旧 inode 上读到过期数据（原实现每次新建连接，本护栏保持等价语义）。
_缓存锁 = __import__("threading").RLock()
_检查点缓存连接: sqlite3.Connection | None = None
_检查点缓存路径: str | None = None
_检查点缓存进程id: int | None = None
_检查点缓存标识: tuple[int, int] | None = None


def _关闭并记录(连接, 场景: str) -> None:
    """尽力关闭连接；失败只留痕不抛出（哲学第 3 条 2 项）。"""
    if 连接 is None:
        return
    try:
        连接.close()
    except Exception as 错误:
        连接问题.append(f"{场景}关闭失败: {错误}")


def _库文件标识(库路径: str):
    """库文件身份 (设备号, inode)；文件不存在返回 None。

    只比身份不比 mtime：本进程自己的写入也会改 mtime，比 mtime 会让缓存每次都失效。
    """
    try:
        文件状态 = os.stat(库路径)
    except OSError:
        return None
    return (文件状态.st_dev, 文件状态.st_ino)


def _关闭检查点缓存连接() -> None:
    """关闭检查点库缓存连接并复位缓存槽（调用方必须持有 _缓存锁）。"""
    global _检查点缓存连接, _检查点缓存路径, _检查点缓存进程id, _检查点缓存标识
    try:
        _关闭并记录(_检查点缓存连接, "检查点库旧连接")
    finally:
        _检查点缓存连接 = None
        _检查点缓存路径 = None
        _检查点缓存进程id = None
        _检查点缓存标识 = None


def _连接(库路径: str) -> sqlite3.Connection:
    """取检查点库连接（按 库路径 缓存复用；命中即返回，不新建、不泄漏）。"""
    global _检查点缓存连接, _检查点缓存路径, _检查点缓存进程id, _检查点缓存标识
    with _缓存锁:
        当前标识 = _库文件标识(库路径)
        if (_检查点缓存连接 is not None and 库路径 == _检查点缓存路径
                and _检查点缓存进程id == os.getpid()
                and 当前标识 is not None and 当前标识 == _检查点缓存标识):
            return _检查点缓存连接
        _关闭检查点缓存连接()
        os.makedirs(os.path.dirname(库路径), exist_ok=True)
        # 转调 `公共契约/运行时/数据库连接.py`，原参数 timeout=5、check_same_thread=False → 写路径档
        # `打开可写(..., 跨线程=True)`（此处建表建索引，属初始化写路径）
        连接 = 打开可写(库路径, 5, 跨线程=True)
        try:
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
        except Exception:
            # 建连/建表失败不留半开连接（哲学第 3 条 2 项：不留脏状态，原异常照抛）
            _关闭并记录(连接, "检查点库建连失败")
            raise
        # 兼容旧库：幂等补 中断 列。列已存在属预期；**其它错误必须留痕**（哲学第 3 条 2 项，不静默）。
        try:
            连接.execute("ALTER TABLE 检查点 ADD COLUMN 中断原因 TEXT")
            连接.execute("ALTER TABLE 检查点 ADD COLUMN 中断状态 TEXT DEFAULT '正常'")
            连接.commit()
        except sqlite3.OperationalError as 错误:
            if "duplicate column" not in str(错误).lower():
                补列问题.append(f"补列失败: {错误}")
        except Exception as 错误:
            补列问题.append(f"补列异常: {错误}")
        _检查点缓存连接 = 连接
        _检查点缓存路径 = 库路径
        _检查点缓存进程id = os.getpid()
        _检查点缓存标识 = _库文件标识(库路径)
        return _检查点缓存连接


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
           版本: str = None, 库路径: str = None, 开工ID: str | None = None) -> 结果:
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


# ═══════════════════════════════════════════════
# 任务状态机：OpenClaw 任务注册表 + DeepSeek 可续跑合并模式化落地
# queued→running→terminal（已完成/失败），SQLite 落库重启不丢，支持多worker并发与断点续跑。
# 0加密0限制：任务数据原文存取，脱敏由业务端自理。
# ═══════════════════════════════════════════════
import os as _os

任务默认库路径 = str(解析运行数据根(取系统根(__file__)) / "任务状态机.db")

# 任务库建连层缓存（与检查点库各自独立一槽，两库互不干扰；护栏同 _连接）
_任务缓存连接: sqlite3.Connection | None = None
_任务缓存路径: str | None = None
_任务缓存进程id: int | None = None
_任务缓存标识: tuple[int, int] | None = None


def _关闭任务缓存连接() -> None:
    """关闭任务库缓存连接并复位缓存槽（调用方必须持有 _缓存锁）。"""
    global _任务缓存连接, _任务缓存路径, _任务缓存进程id, _任务缓存标识
    try:
        _关闭并记录(_任务缓存连接, "任务库旧连接")
    finally:
        _任务缓存连接 = None
        _任务缓存路径 = None
        _任务缓存进程id = None
        _任务缓存标识 = None


def _任务连接(库路径: str) -> sqlite3.Connection:
    """取任务状态机库连接（按 库路径 缓存复用；命中即返回，不新建、不泄漏）。"""
    global _任务缓存连接, _任务缓存路径, _任务缓存进程id, _任务缓存标识
    with _缓存锁:
        当前标识 = _库文件标识(库路径)
        if (_任务缓存连接 is not None and 库路径 == _任务缓存路径
                and _任务缓存进程id == _os.getpid()
                and 当前标识 is not None and 当前标识 == _任务缓存标识):
            return _任务缓存连接
        _关闭任务缓存连接()
        _os.makedirs(_os.path.dirname(库路径), exist_ok=True)
        # 转调 `公共契约/运行时/数据库连接.py`，原参数 timeout=5、check_same_thread=False → 写路径档
        # `打开可写(..., 跨线程=True)`（此处建表建索引，属初始化写路径）
        连接 = 打开可写(库路径, 5, 跨线程=True)
        try:
            连接.execute("""CREATE TABLE IF NOT EXISTS 任务表 (
        任务id TEXT PRIMARY KEY,
        任务名 TEXT NOT NULL,
        归属人 TEXT,
        状态 TEXT DEFAULT '排队',
        执行者 TEXT,
        结果 TEXT,
        错误 TEXT,
        创建时间 TEXT NOT NULL,
        更新时间 TEXT NOT NULL
    )""")
            连接.execute("CREATE INDEX IF NOT EXISTS idx_任务_归属 ON 任务表(归属人, 状态)")
            连接.commit()
        except Exception:
            _关闭并记录(连接, "任务库建连失败")
            raise
        _任务缓存连接 = 连接
        _任务缓存路径 = 库路径
        _任务缓存进程id = _os.getpid()
        _任务缓存标识 = _库文件标识(库路径)
        return _任务缓存连接


def 创建任务(*, 任务名: str = None, 归属人: str = None, 库路径: str = None,
           开工ID: str | None = None) -> 结果:
    """创建任务（状态=排队）。返回 任务id。"""
    if not isinstance(任务名, str) or not 任务名.strip():
        return 结果.失败("参数不合法", "任务名必须是非空字符串", 来源="检查点恢复")
    任务id = uuid.uuid4().hex[:16]
    路径 = 库路径 or 任务默认库路径
    try:
        with 锁, _任务连接(路径) as 连接:
            连接.execute("INSERT INTO 任务表 VALUES (?,?,?,?,?,?,?,?,?)",
                          (任务id, 任务名, 归属人 or "", "排队", None, None, None,
                           time.strftime("%Y-%m-%d %H:%M:%S"),
                           time.strftime("%Y-%m-%d %H:%M:%S")))
        return 结果.成功结果({"任务id": 任务id, "任务名": 任务名, "状态": "排队"})
    except Exception as 错误:
        return 结果.失败("创建任务失败", str(错误), 来源="检查点恢复")


def 领取任务(*, 任务id: str = None, 执行者: str = None, 库路径: str = None,
           开工ID: str | None = None) -> 结果:
    """领取任务（排队→运行中）。仅排队态可领（幂等保护）。"""
    if not isinstance(任务id, str) or not 任务id.strip():
        return 结果.失败("参数不合法", "任务id必须是非空字符串", 来源="检查点恢复")
    路径 = 库路径 or 任务默认库路径
    if not _os.path.isfile(路径):
        return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
    try:
        with 锁, _任务连接(路径) as 连接:
            行 = 连接.execute("SELECT 状态 FROM 任务表 WHERE 任务id=?", (任务id,)).fetchone()
            if 行 is None:
                return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
            if 行[0] != "排队":
                return 结果.成功结果({"领取": False, "任务id": 任务id, "原因": f"当前状态={行[0]}（仅排队可领）"})
            连接.execute("UPDATE 任务表 SET 状态='运行中', 执行者=?, 更新时间=? WHERE 任务id=?",
                          (执行者 or "匿名", time.strftime("%Y-%m-%d %H:%M:%S"), 任务id))
        return 结果.成功结果({"领取": True, "任务id": 任务id, "状态": "运行中", "执行者": 执行者 or "匿名"})
    except Exception as 错误:
        return 结果.失败("领取任务失败", str(错误), 来源="检查点恢复")


def 完成任务(*, 任务id: str = None, 成功: bool = None, 结果值: dict = None,
             库路径: str = None, 开工ID: str | None = None) -> 结果:
    """完成任务（运行中→已完成/失败，终态）。"""
    if not isinstance(任务id, str) or not 任务id.strip():
        return 结果.失败("参数不合法", "任务id必须是非空字符串", 来源="检查点恢复")
    路径 = 库路径 or 任务默认库路径
    if not _os.path.isfile(路径):
        return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
    try:
        with 锁, _任务连接(路径) as 连接:
            行 = 连接.execute("SELECT 状态 FROM 任务表 WHERE 任务id=?", (任务id,)).fetchone()
            if 行 is None:
                return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
            if 行[0] not in ("运行中", "排队"):
                return 结果.成功结果({"完成": False, "任务id": 任务id, "原因": f"当前状态={行[0]}（终态不可改）"})
            新状态 = "已完成" if 成功 else "已失败"
            连接.execute("UPDATE 任务表 SET 状态=?, 结果=?, 错误=?, 更新时间=? WHERE 任务id=?",
                          (新状态, json.dumps(结果值 or {}, ensure_ascii=False),
                           "" if 成功 else "执行失败",
                           time.strftime("%Y-%m-%d %H:%M:%S"), 任务id))
        return 结果.成功结果({"完成": True, "任务id": 任务id, "状态": 新状态})
    except Exception as 错误:
        return 结果.失败("完成任务失败", str(错误), 来源="检查点恢复")


def 查询任务(*, 任务id: str = None, 归属人: str = None, 库路径: str = None) -> 结果:
    """查询任务状态（按任务id 或 归属人列表）。"""
    路径 = 库路径 or 任务默认库路径
    if not _os.path.isfile(路径):
        return 结果.成功结果({"命中": 0, "任务列表": []})
    try:
        with 锁, _任务连接(路径) as 连接:
            if 任务id:
                行 = 连接.execute(
                    "SELECT 任务id, 任务名, 归属人, 状态, 执行者, 结果, 错误, 创建时间 FROM 任务表 WHERE 任务id=?",
                    (任务id,)).fetchone()
                if 行 is None:
                    return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
                return 结果.成功结果({"命中": 1, "任务列表": [{
                    "任务id": 行[0], "任务名": 行[1], "归属人": 行[2], "状态": 行[3],
                    "执行者": 行[4], "结果": json.loads(行[5]) if 行[5] else None,
                    "错误": 行[6], "创建时间": 行[7],
                }]})
            if 归属人:
                行们 = 连接.execute(
                    "SELECT 任务id, 任务名, 归属人, 状态, 执行者, 创建时间 FROM 任务表 WHERE 归属人=? ORDER BY rowid DESC LIMIT 50",
                    (归属人,)).fetchall()
                return 结果.成功结果({"命中": len(行们), "任务列表": [
                    {"任务id": r[0], "任务名": r[1], "归属人": r[2], "状态": r[3],
                     "执行者": r[4], "创建时间": r[5]} for r in 行们
                ]})
            return 结果.失败("参数不合法", "任务id 或 归属人 至少传一个", 来源="检查点恢复")
    except Exception as 错误:
        return 结果.失败("查询任务失败", str(错误), 来源="检查点恢复")


def 续跑任务(*, 任务id: str = None, 执行者: str = None, 库路径: str = None) -> 结果:
    """续跑任务（已失败→排队，DeepSeek cold resume 语义）。"""
    if not isinstance(任务id, str) or not 任务id.strip():
        return 结果.失败("参数不合法", "任务id必须是非空字符串", 来源="检查点恢复")
    路径 = 库路径 or 任务默认库路径
    if not _os.path.isfile(路径):
        return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
    try:
        with 锁, _任务连接(路径) as 连接:
            行 = 连接.execute("SELECT 状态 FROM 任务表 WHERE 任务id=?", (任务id,)).fetchone()
            if 行 is None:
                return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
            if 行[0] not in ("已失败", "已完成"):
                return 结果.成功结果({"续跑": False, "任务id": 任务id, "原因": f"当前状态={行[0]}（仅终态可续跑）"})
            连接.execute("UPDATE 任务表 SET 状态='排队', 执行者=NULL, 结果=NULL, 错误=NULL, 更新时间=? WHERE 任务id=?",
                          (time.strftime("%Y-%m-%d %H:%M:%S"), 任务id))
        return 结果.成功结果({"续跑": True, "任务id": 任务id, "状态": "排队", "说明": "已重新排队"})
    except Exception as 错误:
        return 结果.失败("续跑任务失败", str(错误), 来源="检查点恢复")


def 超时重排队(*, 任务id: str = None, 超时秒: int = None, 库路径: str = None) -> 结果:
    """运行中超时→排队（worker 崩溃恢复语义）。"""
    if not isinstance(任务id, str) or not 任务id.strip():
        return 结果.失败("参数不合法", "任务id必须是非空字符串", 来源="检查点恢复")
    路径 = 库路径 or 任务默认库路径
    if not _os.path.isfile(路径):
        return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
    阈值秒 = max(0, int(超时秒 if 超时秒 is not None else 60))
    try:
        with 锁, _任务连接(路径) as 连接:
            行 = 连接.execute(
                "SELECT 状态, 更新时间 FROM 任务表 WHERE 任务id=?", (任务id,)).fetchone()
            if 行 is None:
                return 结果.失败("任务不存在", f"任务 {任务id} 不存在", 来源="检查点恢复")
            if 行[0] != "运行中":
                return 结果.成功结果({"重排队": False, "任务id": 任务id, "原因": f"当前状态={行[0]}（仅运行中可超时重排队）"})
            更新时间戳 = time.mktime(time.strptime(行[1], "%Y-%m-%d %H:%M:%S"))
            if time.time() - 更新时间戳 < 阈值秒:
                return 结果.成功结果({"重排队": False, "任务id": 任务id, "原因": "未超时"})
            连接.execute("UPDATE 任务表 SET 状态='排队', 执行者=NULL, 更新时间=? WHERE 任务id=?",
                          (time.strftime("%Y-%m-%d %H:%M:%S"), 任务id))
        return 结果.成功结果({"重排队": True, "任务id": 任务id, "状态": "排队", "说明": "超时已重排队"})
    except Exception as 错误:
        return 结果.失败("超时重排队失败", str(错误), 来源="检查点恢复")


def 关闭连接() -> None:
    """关闭检查点库与任务库的缓存连接（幂等，可重复调用）。

    连接不再随每次调用新建/丢弃，而由本模块建连层持有，因此需要一个显式收口入口：
    长驻进程优雅退出、测试收尾、验证探针计数前调用它，即可确认零残留 fd。
    进程退出时由 atexit 自动调用一次。
    """
    with _缓存锁:
        _关闭检查点缓存连接()
        _关闭任务缓存连接()


atexit.register(关闭连接)
