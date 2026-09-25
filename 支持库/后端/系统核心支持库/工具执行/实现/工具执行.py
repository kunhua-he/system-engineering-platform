"""工具执行原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：工具调用的受理→执行→结果登记（借鉴 Codex dispatch_tool_call 两段式 + 失败标记）。
先登记执行记录（受理），再执行；执行异常不抛给调用方，统一返回 失败 + 错误标记。
只做工具调用编排，不执行业务逻辑。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque

from 公共契约.基础类型.结果类型 import 结果

执行记录表: dict[str, dict] = {}
锁 = threading.Lock()


def 受理工具调用(工具名: str = None, 参数: dict = None, 超时秒: int = None) -> 结果:
    """受理工具调用，返回 执行id。后续可用 执行id 关联结果。"""
    if not isinstance(工具名, str) or not 工具名.strip():
        return 结果.失败("参数不合法", "工具名必须是非空字符串", 来源="工具执行")
    执行id = uuid.uuid4().hex[:16]
    with 锁:
        执行记录表[执行id] = {
            "执行id": 执行id, "工具名": 工具名, "参数": dict(参数 or {}),
            "状态": "已受理", "开始时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "超时秒": 超时秒 or 30, "结果": None, "错误": None,
        }
    return 结果.成功结果({"执行id": 执行id, "工具名": 工具名, "状态": "已受理"})


def 登记执行结果(执行id: str = None, 成功: bool = None, 结果值: dict = None, 错误: str = None) -> 结果:
    """登记执行结果（成功或失败，失败带错误标记）。"""
    if not isinstance(执行id, str) or not 执行id.strip():
        return 结果.失败("参数不合法", "执行id必须是非空字符串", 来源="工具执行")
    with 锁:
        记录 = 执行记录表.get(执行id)
        if 记录 is None:
            return 结果.失败("执行不存在", f"执行id {执行id} 未受理或已清理", 来源="工具执行")
        记录["状态"] = "成功" if 成功 else "失败"
        记录["结果"] = dict(结果值 or {})
        记录["错误"] = 错误 or (None if 成功 else "未知错误")
        记录["结束时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return 结果.成功结果({"执行id": 执行id, "状态": 记录["状态"]})


def 查询执行结果(执行id: str = None) -> 结果:
    """查询执行结果。返回 {执行id, 状态, 结果, 错误}。"""
    if not isinstance(执行id, str) or not 执行id.strip():
        return 结果.失败("参数不合法", "执行id必须是非空字符串", 来源="工具执行")
    with 锁:
        记录 = 执行记录表.get(执行id)
    if 记录 is None:
        return 结果.失败("执行不存在", f"执行id {执行id} 不存在", 来源="工具执行")
    return 结果.成功结果({
        "执行id": 执行id, "工具名": 记录["工具名"], "状态": 记录["状态"],
        "结果": 记录["结果"], "错误": 记录["错误"],
        "开始时间": 记录["开始时间"], "结束时间": 记录.get("结束时间", ""),
    })


def 清理执行记录(执行id: str = None) -> 结果:
    """清理执行记录（幂等）。"""
    if not isinstance(执行id, str) or not 执行id.strip():
        return 结果.失败("参数不合法", "执行id必须是非空字符串", 来源="工具执行")
    with 锁:
        存在 = 执行记录表.pop(执行id, None)
    return 结果.成功结果({"执行id": 执行id, "已清理": 存在 is not None})



# ═══════════════════════════════════════════════
# 认领投递：Hermes claim_completion_delivery 模式化落地
# SQLite 落库（重启不丢）+ 认领（原子取出）+ 超时补投（重启恢复）。
# 0加密0限制：负载原文存取，脱敏由业务端自理。
# ═══════════════════════════════════════════════
import atexit as _atexit
import os as _os
from pathlib import Path as _Path
from 公共契约.运行时.运行缓存 import 解析运行数据根 as _解析运行数据根
from 公共契约.运行时.导入前缀 import 取系统根
from 公共契约.运行时.数据库连接 import 打开

投递默认库路径 = str(_解析运行数据根(取系统根(__file__)) / "认领投递.db")

# ---- 建连工厂缓存槽（照抄 嵌入缓存.py:27-29 / :36-49 / :55-74 的正确写法）----
# 为什么必须缓存：调用点写的是 `with 锁, _投递连接(路径) as 连接:`，而
# sqlite3.Connection 的 `with` 只承担事务（commit/rollback）语义、不是关闭器；
# 每次新建连接会严格 1:1 泄漏 fd（要等 __del__ 被 GC 触发才释放）。
# 改为工厂内部缓存后，4 个调用点源码一行都不用动，`with 连接:` 语义不变。
_投递缓存连接 = None
_投递缓存路径 = None
_投递缓存锁 = threading.RLock()  # 独立于模块级 锁（不可重入，调用点已持有）
# 关闭/切换连接时的异常留痕（不阻断主流程）。上限照对照件 `模型连接器.py:64`（1000 条）。
投递降级记录表上限 = 1000
投递降级记录表: deque[str] = deque(maxlen=投递降级记录表上限)


def 投递降级记录摘要() -> dict:
    """投递降级记录表的有界只读视图（供诊断/测试；不注册为能力，故不进 `__all__`）。

    收口前本表是无界 list 且全仓 0 读取方（只写不读的死登记）：本函数是唯一读取入口。
    """
    return {
        "在册条数": len(投递降级记录表),
        "上限": 投递降级记录表上限,
        "最近记录": list(投递降级记录表),
    }


def _关闭投递连接() -> None:
    """进程退出时关闭缓存的投递连接，避免泄漏资源。"""
    global _投递缓存连接, _投递缓存路径
    with _投递缓存锁:
        if _投递缓存连接 is None:
            return
        try:
            _投递缓存连接.close()
        finally:
            _投递缓存连接 = None
            _投递缓存路径 = None


_atexit.register(_关闭投递连接)


def _投递连接(库路径: str):
    """按 库路径 复用模块级缓存连接：同路径命中直接返回；换路径先关旧再建新。

    连接缓存在模块级 锁 内被跨线程使用，故 check_same_thread=False。
    首次为某路径建连时建表 + 建索引。
    """
    global _投递缓存连接, _投递缓存路径
    目标 = str(库路径)
    if _投递缓存连接 is not None and _投递缓存路径 == 目标:
        return _投递缓存连接
    with _投递缓存锁:
        if _投递缓存连接 is not None and _投递缓存路径 == 目标:
            return _投递缓存连接
        if _投递缓存连接 is not None:
            try:
                _投递缓存连接.close()
            except Exception as 错误:
                投递降级记录表.append(str(错误))
            finally:
                _投递缓存连接 = None
                _投递缓存路径 = None
        _os.makedirs(_os.path.dirname(目标), exist_ok=True)
        # 转调 `公共契约/运行时/数据库连接.py`，原参数 timeout=5、check_same_thread=False → 读路径档
        # `打开(..., 跨线程=True)`：连接在模块级 锁 内跨线程复用；不建目录、不切 WAL，语义与原直连等价。
        连接 = 打开(目标, 5, 跨线程=True)
        连接.execute("""CREATE TABLE IF NOT EXISTS 投递表 (
        投递id TEXT PRIMARY KEY,
        队列名 TEXT NOT NULL,
        负载 TEXT NOT NULL,
        状态 TEXT DEFAULT '待认领',
        认领者 TEXT,
        认领时间 TEXT,
        完成时间 TEXT,
        结果 TEXT,
        创建时间 TEXT NOT NULL
    )""")
        连接.execute("CREATE INDEX IF NOT EXISTS idx_投递_队列 ON 投递表(队列名, 状态, 创建时间)")
        连接.commit()
        _投递缓存连接 = 连接
        _投递缓存路径 = 目标
        return 连接


def 登记投递(*, 队列名: str = None, 负载: dict = None, 库路径: str = None,
           开工ID: str | None = None) -> 结果:
    """登记一条投递（落 SQLite，重启不丢）。返回 投递id。"""
    if not isinstance(队列名, str) or not 队列名.strip():
        return 结果.失败("参数不合法", "队列名必须是非空字符串", 来源="工具执行")
    if not isinstance(负载, dict):
        return 结果.失败("参数不合法", "负载必须是字典型", 来源="工具执行")
    投递id = uuid.uuid4().hex[:16]
    路径 = 库路径 or 投递默认库路径
    try:
        with 锁, _投递连接(路径) as 连接:
            连接.execute("INSERT INTO 投递表 VALUES (?,?,?,?,?,?,?,?,?)",
                          (投递id, 队列名, json.dumps(负载, ensure_ascii=False), "待认领",
                           None, None, None, None,
                           time.strftime("%Y-%m-%d %H:%M:%S")))
        return 结果.成功结果({"投递id": 投递id, "队列名": 队列名, "状态": "待认领"})
    except Exception as 错误:
        return 结果.失败("登记投递失败", str(错误), 来源="工具执行")


def 认领投递(*, 队列名: str = None, 认领者: str = None, 库路径: str = None) -> 结果:
    """原子认领最早一条待认领投递。返回 {投递id, 负载}；无则 无待认领。"""
    if not isinstance(队列名, str) or not 队列名.strip():
        return 结果.失败("参数不合法", "队列名必须是非空字符串", 来源="工具执行")
    路径 = 库路径 or 投递默认库路径
    if not _os.path.isfile(路径):
        return 结果.成功结果({"认领": False, "原因": "队列为空"})
    try:
        with 锁, _投递连接(路径) as 连接:
            行 = 连接.execute(
                "SELECT 投递id, 负载 FROM 投递表 WHERE 队列名=? AND 状态='待认领' "
                "ORDER BY rowid ASC LIMIT 1",
                (队列名,)).fetchone()
            if 行 is None:
                return 结果.成功结果({"认领": False, "原因": "队列为空"})
            连接.execute("UPDATE 投递表 SET 状态='已认领', 认领者=?, 认领时间=? WHERE 投递id=?",
                          (认领者 or "匿名", time.strftime("%Y-%m-%d %H:%M:%S"), 行[0]))
        return 结果.成功结果({"认领": True, "投递id": 行[0], "负载": json.loads(行[1]),
                             "认领者": 认领者 or "匿名"})
    except Exception as 错误:
        return 结果.失败("认领投递失败", str(错误), 来源="工具执行")


def 完成投递(*, 投递id: str = None, 成功: bool = None, 结果值: dict = None,
             库路径: str = None, 开工ID: str | None = None) -> 结果:
    """投递完成登记（成功/失败）。"""
    if not isinstance(投递id, str) or not 投递id.strip():
        return 结果.失败("参数不合法", "投递id必须是非空字符串", 来源="工具执行")
    路径 = 库路径 or 投递默认库路径
    if not _os.path.isfile(路径):
        return 结果.失败("投递不存在", f"投递 {投递id} 不存在", 来源="工具执行")
    try:
        with 锁, _投递连接(路径) as 连接:
            行 = 连接.execute("SELECT 状态 FROM 投递表 WHERE 投递id=?", (投递id,)).fetchone()
            if 行 is None:
                return 结果.失败("投递不存在", f"投递 {投递id} 不存在", 来源="工具执行")
            新状态 = "已完成" if 成功 else "已失败"
            连接.execute("UPDATE 投递表 SET 状态=?, 完成时间=?, 结果=? WHERE 投递id=?",
                          (新状态, time.strftime("%Y-%m-%d %H:%M:%S"),
                           json.dumps(结果值 or {}, ensure_ascii=False), 投递id))
        return 结果.成功结果({"投递id": 投递id, "状态": 新状态})
    except Exception as 错误:
        return 结果.失败("完成投递失败", str(错误), 来源="工具执行")


def 补投超时(*, 队列名: str = None, 超时秒: int = None, 库路径: str = None) -> 结果:
    """扫描已认领但超时未完成的投递，状态改回待认领（重启补投语义）。"""
    if not isinstance(队列名, str) or not 队列名.strip():
        return 结果.失败("参数不合法", "队列名必须是非空字符串", 来源="工具执行")
    路径 = 库路径 or 投递默认库路径
    if not _os.path.isfile(路径):
        return 结果.成功结果({"补投数": 0, "投递id列表": []})
    阈值秒 = max(0, int(超时秒 if 超时秒 is not None else 60))
    try:
        with 锁, _投递连接(路径) as 连接:
            截止 = time.time() - 阈值秒
            行们 = 连接.execute(
                "SELECT 投递id FROM 投递表 WHERE 队列名=? AND 状态='已认领' "
                "AND 认领时间 IS NOT NULL",
                (队列名,)).fetchall()
            重投列表 = []
            for (投递id,) in 行们:
                认领行 = 连接.execute("SELECT 认领时间 FROM 投递表 WHERE 投递id=?", (投递id,)).fetchone()
                try:
                    认领时间戳 = time.mktime(time.strptime(认领行[0], "%Y-%m-%d %H:%M:%S"))
                except Exception as 错误:
                    # 允许忽略，但留痕（哲学第 3 条 2 项）：解析失败即跳过该投递，
                    # 无痕会让它永久卡在「已认领」。清理可不阻断，但不能不记录。
                    投递降级记录表.append(f"补投超时.认领时间解析失败 投递id={投递id}: {错误}")
                    continue
                if 认领时间戳 <= 截止:
                    连接.execute("UPDATE 投递表 SET 状态='待认领', 认领者=NULL, 认领时间=NULL WHERE 投递id=?",
                                  (投递id,))
                    重投列表.append(投递id)
        return 结果.成功结果({"补投数": len(重投列表), "投递id列表": 重投列表})
    except Exception as 错误:
        return 结果.失败("补投超时失败", str(错误), 来源="工具执行")
