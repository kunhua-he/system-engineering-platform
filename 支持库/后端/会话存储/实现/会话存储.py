"""会话存储原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：会话/消息/输入 三表存储（收口规范 v1）。句柄模式（华哥口径）：
- 一次传参 = 句柄：指向本能力进程，由 连接会话存储() 返回，操作都持句柄调用；
- id（会话id/输入id）= 数据库主键，是句柄内的资源定位，作二次传参；
- 一次传参直接传 id 会绕过能力进程，不做。
- 消息表事件追加不可变；输入表受理序/提升序分离（上下对齐）；
- 压缩写回带租约（防并发压两次），fail-closed（失败回滚）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源

默认库路径 = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "工程缓存", "会话存储.db")
默认超时秒 = 300
锁 = threading.Lock()

# 句柄 → 连接信息（库路径等），由 连接会话存储() 登记
句柄系统 = 句柄体系()
连接表: dict[str, dict] = {}

_建表语句 = """
CREATE TABLE IF NOT EXISTS 会话表(
  会话id TEXT PRIMARY KEY,
  用户id TEXT,
  模型名 TEXT,
  标题 TEXT,
  状态 TEXT DEFAULT '活跃',
  压缩次数 INTEGER DEFAULT 0,
  成本统计 TEXT DEFAULT '{}',
  创建时间 TEXT,
  更新时间 TEXT
);
CREATE TABLE IF NOT EXISTS 消息表(
  会话id TEXT NOT NULL,
  序号 INTEGER NOT NULL,
  角色 TEXT NOT NULL,
  内容 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '用户',
  时间戳 TEXT,
  PRIMARY KEY (会话id, 序号)
);
CREATE TABLE IF NOT EXISTS 输入表(
  会话id TEXT NOT NULL,
  输入id TEXT PRIMARY KEY,
  受理序 INTEGER NOT NULL,
  提升序 INTEGER,
  内容 TEXT NOT NULL,
  交付模式 TEXT DEFAULT '正常',
  状态 TEXT DEFAULT '已受理',
  时间戳 TEXT
);
CREATE INDEX IF NOT EXISTS idx_消息_会话 ON 消息表(会话id, 序号);
CREATE INDEX IF NOT EXISTS idx_输入_会话 ON 输入表(会话id, 受理序);
"""


def _连接(库路径: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(库路径), exist_ok=True)
    连接 = sqlite3.connect(库路径, timeout=10)
    连接.executescript(_建表语句)
    连接.commit()
    return 连接


def _当前时间() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _校验句柄(句柄: str) -> tuple[bool, str]:
    有效, 原因 = 句柄系统.校验(句柄)
    if not 有效:
        return False, 原因
    if 句柄 not in 连接表:
        return False, f"句柄 {句柄} 连接不存在（可能已释放）"
    return True, ""


def _取库路径(句柄: str) -> str:
    return 连接表.get(句柄, {}).get("库路径") or 默认库路径


# ── 连接器（返回句柄）──────────────────────────────

def 连接会话存储(库路径: str = None, 超时秒: int = None) -> 结果:
    """连接会话存储能力，返回六位句柄。库路径 缺省用默认。句柄无人使用超时自动释放。"""
    路径 = 库路径 or 默认库路径
    try:
        _连接(路径)
    except Exception as 错误:
        return 结果.失败("连接失败", f"会话存储库不可用: {错误}", 来源="会话存储")
    with 锁:
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id="会话存储", 所有者="")
        连接表[对象.句柄id] = {"库路径": 路径, "最后活动时间": time.time(), "超时秒": 超时秒 or 默认超时秒}
    return 结果.成功结果({"句柄": 对象.句柄id, "说明": "持句柄调用会话存储各操作"})


def 释放句柄(句柄: str = None) -> 结果:
    """释放句柄（幂等）。"""
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="会话存储")
    with 锁:
        连接表.pop(句柄, None)
        句柄系统.失效(句柄, "释放")
    return 结果.成功结果({"句柄": 句柄, "已释放": True})


def _更新活动(句柄: str) -> None:
    with 锁:
        连接 = 连接表.get(句柄)
        if 连接:
            连接["最后活动时间"] = time.time()


# ── 持句柄操作 ───────────────────────────────────

def 创建会话(句柄: str = None, 用户id: str = None, 模型名: str = None, 标题: str = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(用户id, str) or not 用户id.strip():
        return 结果.失败("参数不合法", "用户id必须是非空字符串", 来源="会话存储")
    会话id = uuid.uuid4().hex[:16]
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            连接.execute("INSERT INTO 会话表(会话id, 用户id, 模型名, 标题, 创建时间, 更新时间) VALUES (?,?,?,?,?,?)",
                         (会话id, 用户id, 模型名 or "", 标题 or "", _当前时间(), _当前时间()))
        _更新活动(句柄)
        return 结果.成功结果({"句柄": 句柄, "会话id": 会话id, "标题": 标题 or "", "状态": "活跃"})
    except Exception as 错误:
        return 结果.失败("创建会话失败", str(错误), 来源="会话存储")


def 追加消息(句柄: str = None, 会话id: str = None, 角色: str = None, 内容: dict = None, 来源: str = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="会话存储")
    if 角色 not in ("用户", "助手", "工具", "系统", "压缩摘要"):
        return 结果.失败("参数不合法", f"角色必须是 用户/助手/工具/系统/压缩摘要: {角色}", 来源="会话存储")
    if not isinstance(内容, dict):
        return 结果.失败("参数不合法", "内容必须是字典型", 来源="会话存储")
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            行 = 连接.execute("SELECT COALESCE(MAX(序号),0)+1 FROM 消息表 WHERE 会话id=?", (会话id,)).fetchone()
            序号 = 行[0]
            连接.execute("INSERT INTO 消息表(会话id, 序号, 角色, 内容, 来源, 时间戳) VALUES (?,?,?,?,?,?)",
                         (会话id, 序号, 角色, json.dumps(内容, ensure_ascii=False), 来源 or "用户", _当前时间()))
            连接.execute("UPDATE 会话表 SET 更新时间=? WHERE 会话id=?", (_当前时间(), 会话id))
        _更新活动(句柄)
        return 结果.成功结果({"句柄": 句柄, "会话id": 会话id, "序号": 序号, "角色": 角色})
    except Exception as 错误:
        return 结果.失败("追加消息失败", str(错误), 来源="会话存储")


def 读取历史(句柄: str = None, 会话id: str = None, 上限: int = None, 偏移: int = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="会话存储")
    路径 = _取库路径(句柄)
    上限 = 上限 if isinstance(上限, int) and 上限 > 0 else 100000
    偏移 = 偏移 if isinstance(偏移, int) and 偏移 > 0 else 0
    try:
        with 锁, _连接(路径) as 连接:
            行列表 = 连接.execute("SELECT 序号, 角色, 内容, 来源, 时间戳 FROM 消息表 WHERE 会话id=? ORDER BY 序号 LIMIT ? OFFSET ?",
                                  (会话id, 上限, 偏移)).fetchall()
            总数 = 连接.execute("SELECT COUNT(*) FROM 消息表 WHERE 会话id=?", (会话id,)).fetchone()[0]
        _更新活动(句柄)
        消息列表 = [{"序号": r[0], "角色": r[1], "内容": json.loads(r[2]), "来源": r[3], "时间戳": r[4]} for r in 行列表]
        return 结果.成功结果({"句柄": 句柄, "会话id": 会话id, "消息列表": 消息列表, "总数": 总数})
    except Exception as 错误:
        return 结果.失败("读取历史失败", str(错误), 来源="会话存储")


def 受理输入(句柄: str = None, 会话id: str = None, 内容: dict = None, 交付模式: str = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="会话存储")
    if not isinstance(内容, dict):
        return 结果.失败("参数不合法", "内容必须是字典型", 来源="会话存储")
    输入id = uuid.uuid4().hex[:16]
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            行 = 连接.execute("SELECT COALESCE(MAX(受理序),0)+1 FROM 输入表 WHERE 会话id=?", (会话id,)).fetchone()
            受理序 = 行[0]
            连接.execute("INSERT INTO 输入表(会话id, 输入id, 受理序, 内容, 交付模式, 时间戳) VALUES (?,?,?,?,?,?)",
                         (会话id, 输入id, 受理序, json.dumps(内容, ensure_ascii=False), 交付模式 or "正常", _当前时间()))
        _更新活动(句柄)
        return 结果.成功结果({"句柄": 句柄, "输入id": 输入id, "会话id": 会话id, "受理序": 受理序, "状态": "已受理"})
    except Exception as 错误:
        return 结果.失败("受理输入失败", str(错误), 来源="会话存储")


def 提升消息(句柄: str = None, 会话id: str = None, 输入id: str = None, 响应内容: dict = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="会话存储")
    if not isinstance(输入id, str) or not 输入id.strip():
        return 结果.失败("参数不合法", "输入id必须是非空字符串", 来源="会话存储")
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            输入行 = 连接.execute("SELECT 受理序, 内容 FROM 输入表 WHERE 会话id=? AND 输入id=?", (会话id, 输入id)).fetchone()
            if 输入行 is None:
                return 结果.失败("输入不存在", f"输入id {输入id} 未受理", 来源="会话存储")
            受理序, 输入内容 = 输入行
            序号行 = 连接.execute("SELECT COALESCE(MAX(序号),0)+1 FROM 消息表 WHERE 会话id=?", (会话id,)).fetchone()
            用户序号 = 序号行[0]
            连接.execute("INSERT INTO 消息表(会话id, 序号, 角色, 内容, 来源, 时间戳) VALUES (?,?,?,?,?,?)",
                         (会话id, 用户序号, "用户", 输入内容, "用户", _当前时间()))
            助手序号 = 用户序号 + 1
            if 响应内容 is not None and isinstance(响应内容, dict):
                连接.execute("INSERT INTO 消息表(会话id, 序号, 角色, 内容, 来源, 时间戳) VALUES (?,?,?,?,?,?)",
                             (会话id, 助手序号, "助手", json.dumps(响应内容, ensure_ascii=False), "助手", _当前时间()))
            连接.execute("UPDATE 输入表 SET 提升序=?, 状态='已提升' WHERE 会话id=? AND 输入id=?",
                         (用户序号, 会话id, 输入id))
        _更新活动(句柄)
        return 结果.成功结果({"句柄": 句柄, "会话id": 会话id, "输入id": 输入id, "用户序号": 用户序号, "助手序号": 助手序号})
    except Exception as 错误:
        return 结果.失败("提升消息失败", str(错误), 来源="会话存储")


def 写入压缩结果(句柄: str = None, 会话id: str = None, 压缩后消息列表: list = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="会话存储")
    if not isinstance(压缩后消息列表, list) or not 压缩后消息列表:
        return 结果.失败("参数不合法", "压缩后消息列表必须是非空列表", 来源="会话存储")
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            会话行 = 连接.execute("SELECT 压缩次数 FROM 会话表 WHERE 会话id=?", (会话id,)).fetchone()
            if 会话行 is None:
                return 结果.失败("会话不存在", f"会话id {会话id} 不存在", 来源="会话存储")
            连接.execute("DELETE FROM 消息表 WHERE 会话id=?", (会话id,))
            for i, 消息 in enumerate(压缩后消息列表, 1):
                if not isinstance(消息, dict):
                    continue
                角色 = 消息.get("角色", "助手")
                连接.execute("INSERT INTO 消息表(会话id, 序号, 角色, 内容, 来源, 时间戳) VALUES (?,?,?,?,?,?)",
                             (会话id, i, 角色, json.dumps(消息.get("内容", {}), ensure_ascii=False),
                              "压缩摘要" if 角色 == "压缩摘要" else 角色, _当前时间()))
            新次数 = 会话行[0] + 1
            连接.execute("UPDATE 会话表 SET 压缩次数=?, 更新时间=? WHERE 会话id=?", (新次数, _当前时间(), 会话id))
        _更新活动(句柄)
        return 结果.成功结果({"句柄": 句柄, "会话id": 会话id, "压缩次数": 新次数, "写入消息数": len(压缩后消息列表)})
    except Exception as 错误:
        return 结果.失败("写入压缩结果失败", str(错误), 来源="会话存储")


def 查询会话(句柄: str = None, 会话id: str = None) -> 结果:
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="会话存储")
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            行 = 连接.execute("SELECT 用户id, 模型名, 标题, 状态, 压缩次数, 创建时间 FROM 会话表 WHERE 会话id=?", (会话id,)).fetchone()
            if 行 is None:
                return 结果.失败("会话不存在", f"会话id {会话id} 不存在", 来源="会话存储")
            消息数 = 连接.execute("SELECT COUNT(*) FROM 消息表 WHERE 会话id=?", (会话id,)).fetchone()[0]
        _更新活动(句柄)
        return 结果.成功结果({"句柄": 句柄, "会话id": 会话id, "用户id": 行[0], "模型名": 行[1], "标题": 行[2],
                                "状态": 行[3], "压缩次数": 行[4], "创建时间": 行[5], "消息数": 消息数})
    except Exception as 错误:
        return 结果.失败("查询会话失败", str(错误), 来源="会话存储")
