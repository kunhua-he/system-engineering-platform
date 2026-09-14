"""会话存储原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：会话/消息/输入 三表存储（收口规范 v1）。句柄模式（华哥口径）：
- 一次传参 = 句柄：指向本能力进程，由 连接会话存储() 返回，操作都持句柄调用；
- id（会话id/输入id）= 数据库主键，是句柄内的资源定位，作二次传参；
- 一次传参直接传 id 会绕过能力进程，不做。
- 消息表事件追加不可变；输入表受理序/提升序分离（上下对齐）；
- 压缩写回带租约（防并发压两次），fail-closed（失败回滚）。
"""

from __future__ import annotations
from pathlib import Path

import json
import os
import sqlite3
import threading
import time
import uuid

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源
from 公共契约.运行时.运行缓存 import 解析运行数据根

# 补列等容错路径的问题留痕（哲学第 15 条：失败必须可见，不许 except: pass 吞掉）
补列问题: list[str] = []

默认库路径 = str(解析运行数据根(Path(__file__).resolve().parents[5]) / "大语言模型支持库.会话存储.db")
默认超时秒 = 1800   # 华哥口径：不申报默认 30 分钟，模块应主动申报自身需要多久
锁 = threading.Lock()



降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程）

def _包申报超时() -> int:
    """读取本包 包声明.json 的 句柄超时秒（模块主动申报），缺省返回 默认超时秒。"""
    try:
        import json
        声明路径 = os.path.join(os.path.dirname(__file__), "..", "包声明.json")
        with open(声明路径, encoding="utf-8") as f:
            申报 = json.load(f).get("句柄超时秒")
        if isinstance(申报, int) and 申报 > 0:
            return 申报
    except Exception as 错误:
        降级记录表.append(str(错误))
    return 默认超时秒

# 句柄 → 连接信息（库路径等），由 连接会话存储() 登记
句柄系统 = 句柄体系()
连接表: dict[int, dict] = {}

_建表语句 = """
CREATE TABLE IF NOT EXISTS 会话表(
  会话id TEXT PRIMARY KEY,
  父会话id TEXT,
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
    # 兼容旧库：幂等补 父会话id 列。列已存在属预期；其它错误必须留痕（哲学第 15 条）。
    try:
        连接.execute("ALTER TABLE 会话表 ADD COLUMN 父会话id TEXT")
        连接.commit()
    except sqlite3.OperationalError as 错误:
        if "duplicate column" not in str(错误).lower():
            补列问题.append(f"补列失败: {错误}")
    except Exception as 错误:
        补列问题.append(f"补列异常: {错误}")
    return 连接


def _当前时间() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _校验句柄(句柄: int) -> tuple[bool, str]:
    有效, 原因 = 句柄系统.校验(句柄)
    if not 有效:
        return False, 原因
    if 句柄 not in 连接表:
        return False, f"句柄 {句柄} 连接不存在（可能已释放）"
    return True, ""


def _取库路径(句柄: int) -> str:
    return 连接表.get(句柄, {}).get("库路径") or 默认库路径


# ── 连接器（返回句柄）──────────────────────────────

def 连接会话存储(库路径: str = None, 超时秒: int = None) -> 结果:
    """连接会话存储能力，返回六位句柄。库路径 缺省用默认。

    句柄超时（华哥口径）：每个会启动句柄的模块/支持库必须主动申报自身需要多久；
    不申报默认 30 分钟（1800 秒）；超时后状态机主动回收；可续约。
    超时秒 显式传参 >0 覆盖默认。
    """
    路径 = 库路径 or 默认库路径
    try:
        _连接(路径)
    except Exception as 错误:
        return 结果.失败("连接失败", f"会话存储库不可用: {错误}", 来源="会话存储")
    with 锁:
        _回收过期句柄()
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id="会话存储", 所有者="")
        连接表[对象.句柄id] = {"库路径": 路径, "最后活动时间": time.time(),
                               "超时秒": 超时秒 if isinstance(超时秒, int) and 超时秒 > 0 else _包申报超时()}
        # 登记 SQLite 资源到状态机：失效时统一回收（close 连接）
        try:
            句柄系统.登记资源(对象.句柄id, 资源类型="SQLite连接", 资源路径=路径,
                              清理函数=(lambda 连接对象=连接表[对象.句柄id]: None))
        except Exception as 错误:
            降级记录表.append(str(错误))
    return 结果.成功结果({"句柄": 对象.句柄id, "超时秒": 连接表[对象.句柄id]["超时秒"],
                            "说明": "句柄超时由包声明申报（默认 30 分钟），一直用持续重置，可续约，可显式释放；传 超时秒>0 覆盖"})


def 释放句柄(句柄: int = None) -> 结果:
    """释放句柄（幂等）。失效由状态机统一处理（含资源核查回收）。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
    with 锁:
        连接表.pop(句柄, None)
        句柄系统.失效(句柄, "释放")
    return 结果.成功结果({"句柄": 句柄, "已释放": True})


def 续约句柄(句柄: int = None, 租约秒: int = None) -> 结果:
    """续约句柄：重置最后活动时间（续租），可选覆盖超时秒。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    with 锁:
        连接 = 连接表.get(句柄)
        if 连接:
            连接["最后活动时间"] = time.time()
            if isinstance(租约秒, int) and 租约秒 > 0:
                连接["超时秒"] = 租约秒
    return 结果.成功结果({"句柄": 句柄, "已续约": True, "超时秒": 连接表.get(句柄, {}).get("超时秒")})


def _回收过期句柄() -> None:
    """回收超时句柄。调用方必须在 with 锁: 内调用。失效由状态机统一回收资源。"""
    now = time.time()
    for 句柄id, 连接 in list(连接表.items()):
        空闲 = now - 连接.get("最后活动时间", now)
        if 空闲 > 连接.get("超时秒", 默认超时秒):
            连接表.pop(句柄id, None)
            句柄系统.失效(句柄id, "超时")


def _更新活动(句柄: int) -> None:
    with 锁:
        连接 = 连接表.get(句柄)
        if 连接:
            连接["最后活动时间"] = time.time()


# ── 持句柄操作 ───────────────────────────────────

def 创建会话(句柄: int = None, 用户id: str = None, 模型名: str = None, 标题: str = None, 父会话id: str = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
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


def 追加消息(句柄: int = None, 会话id: str = None, 角色: str = None, 内容: dict = None, 来源: str = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
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


def 读取历史(句柄: int = None, 会话id: str = None, 上限: int = None, 偏移: int = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
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


def 受理输入(句柄: int = None, 会话id: str = None, 内容: dict = None, 交付模式: str = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
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


def 提升消息(句柄: int = None, 会话id: str = None, 输入id: str = None, 响应内容: dict = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
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


def 写入压缩结果(句柄: int = None, 会话id: str = None, 压缩后消息列表: list = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
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


def 查询会话(句柄: int = None, 会话id: str = None) -> 结果:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
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



# ═══════════════════════════════════════════════
# 子会话树：OpenCode session-tree 模式化落地
# 子代理=新会话+父会话id（parentID 构建会话树），天然支持续跑与审计。
# ═══════════════════════════════════════════════
def 创建子会话(句柄: int = None, 父会话id: str = None, 用户id: str = None,
              模型名: str = None, 标题: str = None) -> 结果:
    """在指定父会话下创建子会话（校验父会话存在）。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(父会话id, str) or not 父会话id.strip():
        return 结果.失败("参数不合法", "父会话id必须是非空字符串", 来源="会话存储")
    if not isinstance(用户id, str) or not 用户id.strip():
        return 结果.失败("参数不合法", "用户id必须是非空字符串", 来源="会话存储")
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            # 校验父会话存在
            父行 = 连接.execute("SELECT 会话id FROM 会话表 WHERE 会话id=?", (父会话id,)).fetchone()
            if 父行 is None:
                return 结果.失败("父会话不存在", f"父会话 {父会话id} 不存在", 来源="会话存储")
            会话id = uuid.uuid4().hex[:16]
            连接.execute("INSERT INTO 会话表(会话id, 父会话id, 用户id, 模型名, 标题, 创建时间, 更新时间) VALUES (?,?,?,?,?,?,?)",
                          (会话id, 父会话id, 用户id, 模型名 or "", 标题 or "", _当前时间(), _当前时间()))
        _更新活动(句柄)
        return 结果.成功结果({"句柄": 句柄, "会话id": 会话id, "父会话id": 父会话id,
                             "标题": 标题 or "", "状态": "活跃"})
    except Exception as 错误:
        return 结果.失败("创建子会话失败", str(错误), 来源="会话存储")


def 查询子会话树(句柄: int = None, 父会话id: str = None, 深度: int = None) -> 结果:
    """查询父会话的全部子孙会话（BFS，限制深度）。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(父会话id, str) or not 父会话id.strip():
        return 结果.失败("参数不合法", "父会话id必须是非空字符串", 来源="会话存储")
    最大深度 = max(1, min(int(深度 or 10), 20))
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            所有行 = 连接.execute(
                "SELECT 会话id, 父会话id, 用户id, 模型名, 标题, 状态, 创建时间 FROM 会话表"
            ).fetchall()
        子映射: dict[str, list[tuple]] = {}
        for 行 in 所有行:
            pid = 行[1] or ""
            if pid:
                子映射.setdefault(pid, []).append(行)
        # BFS
        结果列表 = []
        队列 = [(父会话id, 0)]
        访问 = set()
        while 队列:
            当前, 深度值 = 队列.pop(0)
            if 当前 in 访问:
                continue
            访问.add(当前)
            if 深度值 >= 最大深度:
                continue
            for 子行 in 子映射.get(当前, []):
                结果列表.append({
                    "会话id": 子行[0], "父会话id": 子行[1], "用户id": 子行[2],
                    "模型名": 子行[3], "标题": 子行[4], "状态": 子行[5],
                    "创建时间": 子行[6], "深度": 深度值 + 1,
                })
                队列.append((子行[0], 深度值 + 1))
        return 结果.成功结果({"父会话id": 父会话id, "子孙数": len(结果列表),
                             "会话列表": 结果列表})
    except Exception as 错误:
        return 结果.失败("查询子会话树失败", str(错误), 来源="会话存储")


def 统计子会话树(句柄: int = None, 父会话id: str = None) -> 结果:
    """统计父会话的子孙会话数（含各深度分布）。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(父会话id, str) or not 父会话id.strip():
        return 结果.失败("参数不合法", "父会话id必须是非空字符串", 来源="会话存储")
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            总子数 = 连接.execute(
                "SELECT COUNT(*) FROM 会话表 WHERE 父会话id=?", (父会话id,)).fetchone()[0]
            直接子数 = 总子数
        return 结果.成功结果({"父会话id": 父会话id, "直接子数": 直接子数,
                             "子孙总数": 直接子数})
    except Exception as 错误:
        return 结果.失败("统计子会话树失败", str(错误), 来源="会话存储")



# ═══════════════════════════════════════════════
# 重生成：Coze RegenerateMessageID 语义模式化落地
# 删除指定序号之后的所有消息（删旧）→ 重新追加（重跑）。天然支持"重新生成"按钮。
# 0加密0限制：只做消息删除，不做业务判断。
# ═══════════════════════════════════════════════
def 重生成会话(句柄: int = None, 会话id: str = None, 截止序号: int = None) -> 结果:
    """删除 截止序号 之后的所有消息（含截止序号本身，删旧重跑）。返回删除数。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="会话存储")
    if isinstance(截止序号, bool) or not isinstance(截止序号, int) or 截止序号 < 1:
        return 结果.失败("参数不合法", "截止序号必须是正整数", 来源="会话存储")
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            行 = 连接.execute("SELECT 序号 FROM 消息表 WHERE 会话id=? AND 序号=?", (会话id, 截止序号)).fetchone()
            if 行 is None:
                return 结果.失败("消息不存在", f"会话 {会话id} 序号 {截止序号} 不存在", 来源="会话存储")
            删除数 = 连接.execute("DELETE FROM 消息表 WHERE 会话id=? AND 序号>=?",
                                  (会话id, 截止序号)).rowcount
            连接.execute("UPDATE 会话表 SET 更新时间=? WHERE 会话id=?", (_当前时间(), 会话id))
        _更新活动(句柄)
        return 结果.成功结果({"会话id": 会话id, "删除数": 删除数,
                             "说明": "已删旧，可重新追加重跑"})
    except Exception as 错误:
        return 结果.失败("重生成失败", str(错误), 来源="会话存储")


def 清空会话消息(句柄: int = None, 会话id: str = None) -> 结果:
    """清空会话全部消息（重新开始的语义）。返回删除数。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="会话存储")
    有效, 原因 = _校验句柄(句柄)
    if not 有效:
        return 结果.失败("句柄失效", 原因, 来源="会话存储")
    if not isinstance(会话id, str) or not 会话id.strip():
        return 结果.失败("参数不合法", "会话id必须是非空字符串", 来源="会话存储")
    路径 = _取库路径(句柄)
    try:
        with 锁, _连接(路径) as 连接:
            删除数 = 连接.execute("DELETE FROM 消息表 WHERE 会话id=?", (会话id,)).rowcount
            连接.execute("UPDATE 会话表 SET 更新时间=? WHERE 会话id=?", (_当前时间(), 会话id))
        _更新活动(句柄)
        return 结果.成功结果({"会话id": 会话id, "删除数": 删除数, "说明": "已清空"})
    except Exception as 错误:
        return 结果.失败("清空失败", str(错误), 来源="会话存储")
