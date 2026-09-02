"""跨进程权威状态：sqlite3（WAL+事务）统一状态存储。

持久化：句柄/租约/资源版本/事务/结构化锁/进程身份/回收证据/激活引用计数。
多进程看到同一份状态；读取不阻塞；提交只持有资源级短锁；全部操作幂等。

结构迁移规则（总补修）：
- 全新初始化和旧库升级是两个明确流程，结构版本只在全部迁移成功并校验后更新。
- 固定迁移序列表驱动，版本比较用元组，禁止字符串字典序。
- 迁移失败回滚并保留旧版本，写结构化失败证据，禁止半迁移伪装成功。
- 支持：全新空库 / 真实旧库升级 / 中断迁移恢复 / 错误历史状态（假升级）补列 /
  重复迁移幂等 / 多进程并发迁移（BEGIN IMMEDIATE 串行化）。

栅栏令牌规则（总补修）：
- 每次成功授予写锁时在同一原子事务内递增资源代数，签发后永不回退/复用。
- 数据版本只在成功提交后递增；令牌与版本是两个独立概念。
- 提交必须同时验证 版本 + 令牌 + 锁所有权（事务id/进程身份键/项目/所有者）。

锁所有权结构化（总补修）：锁记录保存 操作id/事务id/进程身份键/项目id/
所有者/栅栏令牌/获取时间/租约截止，不再拼接字符串猜测所有权。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from 运行核心.进程身份 import 创建进程身份

状态结构版本 = "1.2.0"  # 1.1.0：栅栏令牌列；1.2.0：结构化锁表+租约/句柄/事务进程身份键+迁移器重构

# 稳定错误码：底层异常一律转换为以下稳定枚举，不得把 Exception 文本直接返回用户/Agent
稳定错误码 = {
    "资源不存在": "RESOURCE_NOT_FOUND",
    "版本冲突": "VERSION_CONFLICT",
    "旧令牌提交": "STALE_FENCE_TOKEN",
    "令牌不匹配": "FENCE_TOKEN_MISMATCH",
    "锁所有权不匹配": "LOCK_OWNERSHIP_MISMATCH",
    "租约过期": "LEASE_EXPIRED",
    "锁获取超时": "LOCK_TIMEOUT",
    "权限不足": "PERMISSION_DENIED",
    "重复能力": "DUPLICATE_CAPABILITY",
    "签名失效": "SIGNATURE_INVALID",
    "未签名": "NOT_SIGNED",
    "已撤销": "REVOKED",
    "内容变化": "CONTENT_CHANGED",
    "参数不合法": "INVALID_PARAMETER",
    "迁移失败": "MIGRATION_FAILED",
    "数据库损坏": "DATABASE_CORRUPT",
    "内部错误": "INTERNAL_ERROR",
}


def 异常转错误码(异常: Exception) -> tuple[str, str]:
    """底层异常 → 稳定错误码 + 稳定描述（不暴露 Exception 文本）。"""
    if isinstance(异常, sqlite3.OperationalError):
        return 稳定错误码["内部错误"], "数据库操作失败"
    if isinstance(异常, (FileNotFoundError, IsADirectoryError, PermissionError, OSError)):
        return 稳定错误码["内部错误"], "文件系统访问失败"
    if isinstance(异常, ValueError):
        return 稳定错误码["参数不合法"], "参数格式错误"
    if isinstance(异常, KeyError):
        return 稳定错误码["参数不合法"], "缺少必需字段"
    return 稳定错误码["内部错误"], "内部错误"


def 版本元组(版本: str) -> tuple[int, ...]:
    """版本字符串 → 比较元组（禁止字符串字典序比较）。"""
    return tuple(int(段) for 段 in 版本.split("."))


# 固定迁移序列表：(目标版本, 迁移函数名)；顺序执行，版本只增不减
迁移序列表 = [
    ("1.0.0", "_迁移到100"),
    ("1.1.0", "_迁移到110"),
    ("1.2.0", "_迁移到120"),
]


class 权威状态:
    """权威状态存储（sqlite3 WAL）。"""

    # 类属性（子类可覆盖扩展）：目标结构版本 / 迁移序列表 / 结构校验规则表
    目标版本 = 状态结构版本
    迁移序列表 = [
        ("1.0.0", "_迁移到100"),
        ("1.1.0", "_迁移到110"),
        ("1.2.0", "_迁移到120"),
    ]
    校验规则表 = {
        "1.0.0": {"表": ["元信息", "句柄", "租约", "资源版本", "事务", "锁", "进程", "回收证据", "引用计数"]},
        "1.1.0": {"列": [("资源版本", "栅栏令牌"), ("事务", "基础令牌")]},
        "1.2.0": {"列": [("锁", "进程身份键"), ("锁", "栅栏令牌"), ("租约", "进程身份键"),
                          ("句柄", "进程身份键"), ("事务", "进程身份键")]},
    }

    def __init__(self, 存储目录: Path, *, 项目id: str = "", 所有者: str = "") -> None:
        self.存储目录 = Path(存储目录)
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.数据库路径 = self.存储目录 / "权威状态.db"
        self.项目id = 项目id
        self.身份 = 创建进程身份(项目id=项目id, 所有者=所有者)
        self._本地锁 = threading.Lock()
        self._连接锁 = threading.RLock()
        self._连接表: dict[int, sqlite3.Connection] = {}
        self._连接线程表: dict[int, threading.Thread] = {}
        self._初始化()

    # ---- 连接管理（每线程独立 + 死线程回收） ----
    def _连接(self) -> sqlite3.Connection:
        """返回当前线程的独立连接；连接回收只能在显式维护点执行。"""
        线程id = threading.get_ident()
        当前线程 = threading.current_thread()
        with self._连接锁:
            原线程 = self._连接线程表.get(线程id)
            if 原线程 is not None and 原线程 is not 当前线程:
                # 操作系统可复用已退出线程的 id；此时旧连接已无调用者。
                self._连接表[线程id].close()
                del self._连接表[线程id]
                del self._连接线程表[线程id]
            if 线程id not in self._连接表:
                连接 = sqlite3.connect(
                    str(self.数据库路径), timeout=10, check_same_thread=False)
                # busy_timeout 必须先于 WAL/写操作设置，否则并发下 PRAGMA 立即 locked
                连接.execute("PRAGMA busy_timeout=5000")  # 写竞争自动等待（WAL）
                连接.execute("PRAGMA journal_mode=WAL")
                连接.execute("PRAGMA synchronous=NORMAL")
                self._连接表[线程id] = 连接
                self._连接线程表[线程id] = 当前线程
            return self._连接表[线程id]

    def _清理死连接(self) -> None:
        """显式回收已结束线程的连接；普通读取路径不得调用本方法。"""
        with self._连接锁:
            for 线程id, 线程 in list(self._连接线程表.items()):
                if not 线程.is_alive():
                    self._连接表[线程id].close()
                    del self._连接表[线程id]
                    del self._连接线程表[线程id]

    # ---- 结构迁移器（初始化/迁移分离） ----
    def _初始化(self) -> None:
        """打开数据库并执行结构迁移；数据库损坏时自动从备份恢复后再初始化。"""
        with self._本地锁:
            try:
                # 迁移脚本包含历史 DDL；旧版本 SQLite 的 executescript 可能在
                # 并发进程间短暂暴露中间 schema。对可恢复的 schema 竞态重试，
                # 其它迁移错误仍立即失败，避免吞掉真实损坏。
                for 次数 in range(4):
                    try:
                        self._迁移结构()
                        break
                    except RuntimeError as 错误:
                        文本 = str(错误)
                        可恢复 = ("no such table" in 文本 or "database is locked" in 文本
                                  or "database table is locked" in 文本)
                        if not 可恢复 or 次数 == 3:
                            raise
                        time.sleep(0.05 * (次数 + 1))
            except sqlite3.DatabaseError:
                # 数据库损坏：自动恢复（损坏恢复内部重新校验结构后再允许运行）
                成功, 消息 = self.损坏恢复()
                if not 成功:
                    raise RuntimeError(
                        f"权威状态数据库损坏且自动恢复失败: {消息}")
                self._迁移结构()
            self._注册进程()

    def _迁移结构(self) -> None:
        """结构迁移主入口：BEGIN IMMEDIATE 串行化 + 固定迁移序列表。

        支持：全新空库、真实旧库升级、中断迁移恢复、假升级错误历史补列、
        重复迁移幂等、多进程并发迁移。
        """
        连接 = self._连接()
        with 连接:
            # 串行化：并发迁移只允许一个进程执行，其余等待后看到新版本跳过
            连接.execute("BEGIN IMMEDIATE")
            try:
                # 元信息表是版本记录的载体，任何迁移前必须存在（幂等）
                连接.execute("CREATE TABLE IF NOT EXISTS 元信息(键 TEXT PRIMARY KEY, 值 TEXT)")
                行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()
                当前版本 = 行[0] if 行 else "0.0.0"
                目标版本 = self.目标版本
                目标元组 = 版本元组(目标版本)
                # 假升级检测：元信息已写高版本但列缺失（错误历史状态）→ 重新执行到目标
                需要补列 = 当前版本 == 目标版本 and not self._校验当前结构(连接)
                if 需要补列:
                    当前版本 = "0.0.0"  # 按序重放，幂等 ALTER 补齐缺失列
                for 目标, 函数名 in self.迁移序列表:
                    目标_元组 = 版本元组(目标)
                    if 版本元组(当前版本) < 目标_元组:
                        try:
                            getattr(self, 函数名)(连接)
                            self._校验版本结构(连接, 目标)
                        except Exception as 错误:
                            # 迁移失败：回滚部分迁移 + 保留旧版本 + 写持久失败证据
                            # （证据必须单独提交，禁止随回滚丢失——任务信三.3）
                            连接.rollback()
                            连接.execute(
                                "INSERT OR REPLACE INTO 元信息(键, 值) VALUES('迁移失败', ?)",
                                (json.dumps({"版本": 当前版本, "目标": 目标,
                                             "错误": str(错误), "时间": time.strftime("%Y-%m-%d %H:%M:%S")},
                                            ensure_ascii=False),))
                            连接.commit()
                            raise RuntimeError(
                                f"结构迁移失败 {当前版本}→{目标}: {错误}（已回滚，版本保持 {当前版本}）")
                        连接.execute("INSERT OR REPLACE INTO 元信息(键, 值) VALUES('结构版本', ?)", (目标,))
                # for 循环后兜底：版本匹配但结构不完整的错误历史状态无法修复时失败
                if 需要补列 and 当前版本 == "0.0.0" and 版本元组(状态结构版本) < 版本元组("1.0.0"):
                    raise RuntimeError(f"结构校验失败: 版本 {目标版本} 但表结构不完整")
                连接.execute("DELETE FROM 元信息 WHERE 键='迁移失败'")
            except Exception:
                连接.rollback()
                raise

    def _校验当前结构(self, 连接: sqlite3.Connection) -> bool:
        """当前版本完整结构校验（列齐全才认为版本真实）。"""
        try:
            self._校验版本结构(连接, self.目标版本)
            return True
        except RuntimeError:
            return False

    def _校验版本结构(self, 连接: sqlite3.Connection, 版本: str) -> None:
        """按 校验规则表 校验指定版本要求的表、列与完整性；不满足抛 RuntimeError。

        规则表按版本号升序执行所有 <= 目标版本的规则，子类可扩展规则表。
        """
        目标元组 = 版本元组(版本)
        for 规则版本 in sorted(self.校验规则表, key=版本元组):
            if 版本元组(规则版本) > 目标元组:
                continue
            规则 = self.校验规则表[规则版本]
            for 表 in 规则.get("表", []):
                self._校验表存在(连接, 表)
            for 表, 列 in 规则.get("列", []):
                self._校验列(连接, 表, 列)
        # 完整性检查必须读取返回值并判断 ok
        结果 = 连接.execute("PRAGMA integrity_check").fetchone()
        if not 结果 or 结果[0] != "ok":
            raise RuntimeError(f"数据库完整性检查失败: {结果}")

    def _校验表存在(self, 连接: sqlite3.Connection, 表: str) -> None:
        行 = 连接.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (表,)).fetchone()
        if 行 is None:
            raise RuntimeError(f"缺少必需表: {表}")

    def _校验列(self, 连接: sqlite3.Connection, 表: str, 列: str) -> None:
        列表 = {行[1] for 行 in 连接.execute(f"PRAGMA table_info({表})").fetchall()}
        if 列 not in 列表:
            raise RuntimeError(f"缺少必需列: {表}.{列}")

    def _迁移到100(self, 连接: sqlite3.Connection) -> None:
        """1.0.0：建全部基础表（无栅栏列；对旧库 CREATE IF NOT EXISTS 幂等）。"""
        连接.executescript("""
            CREATE TABLE IF NOT EXISTS 元信息(键 TEXT PRIMARY KEY, 值 TEXT);
            CREATE TABLE IF NOT EXISTS 句柄(
                句柄id TEXT PRIMARY KEY, 句柄类型 TEXT, 资源id TEXT,
                项目id TEXT, 所有者 TEXT, 状态 TEXT, 版本 TEXT,
                创建时间 TEXT, 失效时间 TEXT, 失效原因 TEXT);
            CREATE TABLE IF NOT EXISTS 租约(
                租约id TEXT PRIMARY KEY, 资源id TEXT, 项目id TEXT, 所有者 TEXT,
                句柄id TEXT, 空闲超时秒 REAL, 硬截止时间 REAL, 最后心跳 REAL,
                已回收 INTEGER);
            CREATE TABLE IF NOT EXISTS 资源版本(
                资源id TEXT PRIMARY KEY, 版本 TEXT, 值 TEXT, 摘要 TEXT,
                更新时间 TEXT);
            CREATE TABLE IF NOT EXISTS 事务(
                事务id TEXT PRIMARY KEY, 资源id TEXT, 句柄id TEXT, 基础版本 TEXT,
                状态 TEXT, 结果 TEXT, 新版本 TEXT, 创建时间 TEXT, 提交时间 TEXT);
            CREATE TABLE IF NOT EXISTS 锁(
                资源id TEXT PRIMARY KEY, 持有者 TEXT, 锁时间 TEXT);
            CREATE TABLE IF NOT EXISTS 进程(
                身份键 TEXT PRIMARY KEY, 进程id INTEGER, 启动指纹 TEXT,
                项目id TEXT, 所有者 TEXT, 实例id TEXT, 最后心跳 REAL);
            CREATE TABLE IF NOT EXISTS 回收证据(
                证据id TEXT PRIMARY KEY, 句柄id TEXT, 资源id TEXT, 类型 TEXT,
                失效原因 TEXT, 时间 TEXT, 版本 TEXT);
            CREATE TABLE IF NOT EXISTS 引用计数(
                引用键 TEXT PRIMARY KEY, 包id TEXT, 版本 TEXT, 计数 INTEGER);
        """)

    def _迁移到110(self, 连接: sqlite3.Connection) -> None:
        """1.1.0：资源版本/事务 增加栅栏令牌列（幂等：只补缺失列，明确识别重复列）。"""
        self._补列(连接, "资源版本", "栅栏令牌", "INTEGER DEFAULT 0")
        self._补列(连接, "事务", "基础令牌", "TEXT DEFAULT '0'")

    def _迁移到120(self, 连接: sqlite3.Connection) -> None:
        """1.2.0：结构化锁表 + 租约/句柄/事务 增加进程身份键列 + 旧锁数据迁移。"""
        for 表, 列, 定义 in (("租约", "进程身份键", "TEXT DEFAULT ''"),
                          ("句柄", "进程身份键", "TEXT DEFAULT ''"),
                          ("事务", "进程身份键", "TEXT DEFAULT ''")):
            self._补列(连接, 表, 列, 定义)
        # 锁表重建为结构化（保留旧数据，不删除）
        锁列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(锁)").fetchall()}
        if "操作id" not in 锁列:
            连接.execute("ALTER TABLE 锁 RENAME TO 锁旧表")
            连接.executescript("""
                CREATE TABLE 锁(
                    资源id TEXT PRIMARY KEY, 操作id TEXT DEFAULT '',
                    事务id TEXT DEFAULT '', 进程身份键 TEXT DEFAULT '',
                    项目id TEXT DEFAULT '', 所有者 TEXT DEFAULT '',
                    栅栏令牌 INTEGER DEFAULT 0, 获取时间 REAL DEFAULT 0,
                    租约截止 REAL DEFAULT 0);
                INSERT INTO 锁(资源id, 操作id, 事务id, 进程身份键, 获取时间)
                    SELECT 资源id,
                           CASE WHEN 持有者 LIKE '事务_%' THEN ''
                                WHEN 持有者 LIKE '%:%' THEN
                                     SUBSTR(持有者, 1, INSTR(持有者, ':') - 1)
                                ELSE 持有者 END,
                           CASE WHEN 持有者 LIKE '事务_%' THEN
                                     SUBSTR(持有者, 7) ELSE '' END,
                           CASE WHEN 持有者 LIKE '%:%' THEN
                                     SUBSTR(持有者, INSTR(持有者, ':') + 1) ELSE '' END,
                           CAST(0 AS REAL) FROM 锁旧表;
                DROP TABLE 锁旧表;
            """)

    def _补列(self, 连接: sqlite3.Connection, 表: str, 列: str, 定义: str) -> None:
        """幂等补列：只有明确识别为重复列（duplicate column）才继续。"""
        列表 = {行[1] for 行 in 连接.execute(f"PRAGMA table_info({表})").fetchall()}
        if 列 in 列表:
            return
        连接.execute(f"ALTER TABLE {表} ADD COLUMN {列} {定义}")

    def _注册进程(self) -> None:
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT OR REPLACE INTO 进程(身份键, 进程id, 启动指纹, 项目id, 所有者, 实例id, 最后心跳) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (self.身份.身份键(), self.身份.进程id, self.身份.启动指纹,
                 self.身份.项目id, self.身份.所有者, self.身份.实例id, self.身份.最后心跳))

    def 刷新心跳(self) -> None:
        """当前进程心跳（进程存活判定依据）。"""
        from 运行核心.进程身份 import 心跳
        心跳(self.身份)
        连接 = self._连接()
        with 连接:
            连接.execute("UPDATE 进程 SET 最后心跳=? WHERE 身份键=?",
                         (self.身份.最后心跳, self.身份.身份键()))

    # ---- 句柄 ----
    def 保存句柄(self, *, 句柄id: int, 句柄类型: str, 资源id: str,
                 项目id: str, 所有者: str, 状态: str, 版本: str,
                 进程身份键: str = "") -> None:
        连接 = self._连接()
        with 连接:
            # 显式列名：迁移库列序与完整建表不同（ALTER 追加列在列尾），禁止依赖列序
            连接.execute(
                "INSERT OR REPLACE INTO 句柄(句柄id, 句柄类型, 资源id, 项目id, 所有者, "
                "状态, 版本, 创建时间, 失效时间, 失效原因, 进程身份键) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (句柄id, 句柄类型, 资源id, 项目id, 所有者, 状态, 版本,
                 time.strftime("%Y-%m-%d %H:%M:%S"), "", "", 进程身份键))

    def 读取句柄(self, 句柄id: int) -> dict[str, Any] | None:
        连接 = self._连接()
        行 = 连接.execute(
            "SELECT 句柄id, 句柄类型, 资源id, 项目id, 所有者, 状态, 版本, 创建时间, 失效时间, 失效原因, 进程身份键 "
            "FROM 句柄 WHERE 句柄id=?", (句柄id,)).fetchone()
        if 行 is None:
            return None
        return {
            "句柄id": 行[0], "句柄类型": 行[1], "资源id": 行[2], "项目id": 行[3],
            "所有者": 行[4], "状态": 行[5], "版本": 行[6], "创建时间": 行[7],
            "失效时间": 行[8], "失效原因": 行[9], "进程身份键": 行[10],
        }

    def 全部句柄(self, *, 仅有效: bool = False) -> list[dict[str, Any]]:
        """读取句柄账本快照，供服务重启恢复；默认包含已失效记录。"""
        连接 = self._连接()
        条件 = " WHERE 状态='有效'" if 仅有效 else ""
        结果 = []
        for 行 in 连接.execute(
            "SELECT 句柄id, 句柄类型, 资源id, 项目id, 所有者, 状态, 版本, 创建时间, 失效时间, 失效原因, 进程身份键 "
            f"FROM 句柄{条件} ORDER BY 句柄id"
        ):
            结果.append({"句柄id": 行[0], "句柄类型": 行[1], "资源id": 行[2],
                         "项目id": 行[3], "所有者": 行[4], "状态": 行[5],
                         "版本": 行[6], "创建时间": 行[7], "失效时间": 行[8],
                         "失效原因": 行[9], "进程身份键": 行[10]})
        return 结果

    def 失效句柄(self, 句柄id: int, 原因: str) -> bool:
        连接 = self._连接()
        with 连接:
            游标 = 连接.execute(
                "UPDATE 句柄 SET 状态='已失效', 失效时间=?, 失效原因=? WHERE 句柄id=? AND 状态='有效'",
                (time.strftime("%Y-%m-%d %H:%M:%S"), 原因, 句柄id))
            return 游标.rowcount > 0

    def 失效句柄并记录证据(self, *, 句柄id: int, 资源id: str,
                         类型: str, 原因: str, 版本: str) -> bool:
        """在同一 SQLite 事务内更新句柄终态并写入回收证据。"""
        连接 = self._连接()
        时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        with 连接:
            游标 = 连接.execute(
                "UPDATE 句柄 SET 状态='已失效', 失效时间=?, 失效原因=? "
                "WHERE 句柄id=? AND 状态='有效'", (时间, 原因, 句柄id))
            if 游标.rowcount == 0:
                return False
            连接.execute(
                "INSERT INTO 回收证据(证据id, 句柄id, 资源id, 类型, 失效原因, 时间, 版本) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:16], 句柄id, 资源id, 类型, 原因, 时间, 版本))
            return True

    def 活跃句柄数(self) -> int:
        连接 = self._连接()
        return 连接.execute("SELECT COUNT(*) FROM 句柄 WHERE 状态='有效'").fetchone()[0]

    # ---- 租约 ----
    def 保存租约(self, *, 租约id: str, 资源id: str, 项目id: str, 所有者: str,
                 句柄id: int, 空闲超时秒: float, 硬截止时间: float, 最后心跳: float,
                 进程身份键: str = "") -> None:
        连接 = self._连接()
        with 连接:
            # 显式列名：迁移库列序与完整建表不同（进程身份键 追加在列尾）
            连接.execute(
                "INSERT OR REPLACE INTO 租约(租约id, 资源id, 项目id, 所有者, 句柄id, "
                "空闲超时秒, 硬截止时间, 最后心跳, 已回收, 进程身份键) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (租约id, 资源id, 项目id, 所有者, 句柄id, 空闲超时秒, 硬截止时间, 最后心跳, 进程身份键))

    def 保存句柄与租约(self, *, 句柄id: int, 句柄类型: str, 资源id: str,
                      项目id: str, 所有者: str, 状态: str, 版本: str,
                      租约id: str, 空闲超时秒: float, 硬截止时间: float,
                      最后心跳: float, 进程身份键: str = "") -> None:
        """句柄与租约在同一 SQLite 事务中提交；任一失败整体回滚。

        解决 创建 时先存句柄再存租约、中途失败留下“有效句柄而无租约”的
        半成品问题；进程身份键同时写入两侧，死亡进程清理可匹配。
        """
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT OR REPLACE INTO 句柄(句柄id, 句柄类型, 资源id, 项目id, 所有者, "
                "状态, 版本, 创建时间, 失效时间, 失效原因, 进程身份键) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (句柄id, 句柄类型, 资源id, 项目id, 所有者, 状态, 版本,
                 time.strftime("%Y-%m-%d %H:%M:%S"), "", "", 进程身份键))
            连接.execute(
                "INSERT OR REPLACE INTO 租约(租约id, 资源id, 项目id, 所有者, 句柄id, "
                "空闲超时秒, 硬截止时间, 最后心跳, 已回收, 进程身份键) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (租约id, 资源id, 项目id, 所有者, 句柄id, 空闲超时秒, 硬截止时间, 最后心跳, 进程身份键))

    def 租约心跳(self, 租约id: str, 心跳时间: float) -> bool:
        连接 = self._连接()
        with 连接:
            游标 = 连接.execute(
                "UPDATE 租约 SET 最后心跳=? WHERE 租约id=? AND 已回收=0", (心跳时间, 租约id))
            return 游标.rowcount > 0

    def 读取租约(self, 句柄id: int) -> dict[str, Any] | None:
        """读取句柄对应的未回收租约，供句柄服务跨进程恢复。"""
        连接 = self._连接()
        行 = 连接.execute(
            "SELECT 租约id, 资源id, 项目id, 所有者, 句柄id, 空闲超时秒, 硬截止时间, 最后心跳, 已回收, 进程身份键 "
            "FROM 租约 WHERE 句柄id=? ORDER BY 最后心跳 DESC LIMIT 1", (句柄id,)
        ).fetchone()
        if 行 is None:
            return None
        return {"租约id": 行[0], "资源id": 行[1], "项目id": 行[2], "所有者": 行[3],
                "句柄id": 行[4], "空闲超时秒": 行[5], "硬截止时间": 行[6],
                "最后心跳": 行[7], "已回收": bool(行[8]), "进程身份键": 行[9]}

    def 续租租约(self, 租约id: str, *, 硬截止时间: float, 最后心跳: float,
                 当前时间: float | None = None) -> bool:
        """原子续租；已回收或已过硬截止的租约不可复活。"""
        当前时间 = time.time() if 当前时间 is None else 当前时间
        连接 = self._连接()
        with 连接:
            游标 = 连接.execute(
                "UPDATE 租约 SET 硬截止时间=?, 最后心跳=? "
                "WHERE 租约id=? AND 已回收=0 AND 硬截止时间>?",
                (硬截止时间, 最后心跳, 租约id, 当前时间),
            )
            return 游标.rowcount > 0

    def 回收租约(self, 租约id: str, 原因: str) -> bool:
        连接 = self._连接()
        时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        with 连接:
            游标 = 连接.execute(
                "UPDATE 租约 SET 已回收=1 WHERE 租约id=? AND 已回收=0", (租约id,))
            if 游标.rowcount == 0:
                return False
            行 = 连接.execute(
                "SELECT 句柄id, 资源id FROM 租约 WHERE 租约id=?", (租约id,)
            ).fetchone()
            if 行 and 行[0]:
                # 必须复用当前连接完成句柄终态和回收证据写入；调用
                # 失效句柄() 会打开第二个连接，破坏租约事务原子性。
                句柄游标 = 连接.execute(
                    "UPDATE 句柄 SET 状态='已失效', 失效时间=?, 失效原因=? "
                    "WHERE 句柄id=? AND 状态='有效'",
                    (时间, 原因, 行[0]),
                )
                if 句柄游标.rowcount:
                    句柄行 = 连接.execute(
                        "SELECT 句柄类型, 版本 FROM 句柄 WHERE 句柄id=?", (行[0],)
                    ).fetchone()
                    连接.execute(
                        "INSERT INTO 回收证据(证据id, 句柄id, 资源id, 类型, 失效原因, 时间, 版本) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (uuid.uuid4().hex[:16], 行[0], 行[1],
                         句柄行[0] if 句柄行 else "", 原因, 时间,
                         句柄行[1] if 句柄行 else ""),
                    )
            return True

    def 扫描过期租约(self) -> list[str]:
        """空闲超时/硬截止过期的租约（幂等回收）。"""
        连接 = self._连接()
        现在 = time.time()
        过期列表 = []
        for 行 in 连接.execute(
                "SELECT 租约id FROM 租约 WHERE 已回收=0 AND "
                "(硬截止时间 < ? OR (空闲超时秒 > 0 AND ? - 最后心跳 > 空闲超时秒))",
                (现在, 现在)):
            过期列表.append(行[0])
        for 租约id in 过期列表:
            self.回收租约(租约id, "空闲超时或硬截止")
        return 过期列表

    # ---- 资源版本 ----
    def 读取资源(self, 资源id: str) -> dict[str, Any] | None:
        连接 = self._连接()
        行 = 连接.execute(
            "SELECT 资源id, 版本, 值, 摘要, 更新时间, 栅栏令牌 FROM 资源版本 WHERE 资源id=?",
            (资源id,)).fetchone()
        if 行 is None:
            return None
        return {"资源id": 行[0], "版本": 行[1], "值": json.loads(行[2]), "摘要": 行[3],
                "更新时间": 行[4], "栅栏令牌": 行[5]}

    def 全部资源版本(self) -> list[dict[str, Any]]:
        """全部资源当前版本（崩溃恢复重建快照用）。"""
        连接 = self._连接()
        结果表 = []
        for 行 in 连接.execute(
                "SELECT 资源id, 版本, 值, 摘要, 更新时间, 栅栏令牌 FROM 资源版本"):
            结果表.append({"资源id": 行[0], "版本": 行[1], "值": json.loads(行[2]), "摘要": 行[3],
                          "更新时间": 行[4], "栅栏令牌": 行[5]})
        return 结果表

    def 初始化资源(self, 资源id: str, 初始值: Any = None) -> None:
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT OR IGNORE INTO 资源版本(资源id, 版本, 值, 摘要, 更新时间, 栅栏令牌) "
                "VALUES(?, '0', ?, '', '', 0)",
                (资源id, json.dumps(初始值, ensure_ascii=False)))

    def 提交资源(self, *, 资源id: str, 期望版本: str, 期望令牌: str,
                 事务id: str = "", 进程身份键: str = "",
                 项目id: str = "", 所有者: str = "",
                 新值: Any, 新摘要: str) -> tuple[bool, str]:
        """原子 CAS 提交：同一事务内校验 锁所有权 + 版本 + 令牌，条件更新。

        拒绝：版本不匹配、旧栅栏令牌、锁不属于该事务/进程、项目或所有者不匹配。
        写入使用单条条件 UPDATE（WHERE 资源id AND 版本 AND 栅栏令牌），无 SELECT 后无条件 UPDATE 竞态。
        """
        进程身份键 = 进程身份键 or self.身份.身份键()
        连接 = self._连接()
        with 连接:
            锁行 = 连接.execute(
                "SELECT 事务id, 进程身份键, 项目id, 所有者, 栅栏令牌 FROM 锁 WHERE 资源id=?",
                (资源id,)).fetchone()
            if 锁行 is None:
                return False, "锁不存在: 提交必须持有资源锁"
            if 锁行[0] and 锁行[0] != 事务id:
                return False, f"锁所有权不匹配: 锁属事务 {锁行[0]}，请求 {事务id}"
            if 锁行[1] and 锁行[1] != 进程身份键:
                return False, f"锁所有权不匹配: 锁属进程 {锁行[1]}，请求 {进程身份键}"
            if 锁行[2] and 锁行[2] != 项目id:
                return False, f"跨项目提交被拒绝: 锁属 {锁行[2]}，请求 {项目id}"
            if 锁行[3] and 锁行[3] != 所有者:
                return False, f"跨所有者提交被拒绝: 锁属 {锁行[3]}，请求 {所有者}"
            资源行 = 连接.execute(
                "SELECT 版本, 栅栏令牌 FROM 资源版本 WHERE 资源id=?", (资源id,)).fetchone()
            if 资源行 is None:
                return False, "资源不存在"
            if str(资源行[0]) != str(期望版本):
                return False, f"版本冲突: 期望 {期望版本}，当前 {资源行[0]}"
            if str(资源行[1]) != str(期望令牌) or str(锁行[4]) != str(期望令牌):
                return False, "旧令牌提交: 栅栏令牌已变化，提交被拒绝"
            新版本 = str(int(资源行[0]) + 1)
            游标 = 连接.execute(
                "UPDATE 资源版本 SET 版本=?, 值=?, 摘要=?, 更新时间=? "
                "WHERE 资源id=? AND 版本=? AND 栅栏令牌=?",
                (新版本, json.dumps(新值, ensure_ascii=False), 新摘要,
                 time.strftime("%Y-%m-%d %H:%M:%S"), 资源id, 期望版本, 期望令牌))
            if 游标.rowcount != 1:
                return False, "并发提交冲突"
            return True, 新版本

    # ---- 事务 ----
    def 创建事务(self, *, 事务id: str, 资源id: str, 句柄id: str, 基础版本: str,
                 基础令牌: str = "0", 进程身份键: str = "") -> None:
        连接 = self._连接()
        with 连接:
            # 显式列名：迁移库列序与完整建表不同（基础令牌/进程身份键 追加在列尾）
            连接.execute(
                "INSERT OR REPLACE INTO 事务(事务id, 资源id, 句柄id, 基础版本, 基础令牌, "
                "状态, 结果, 新版本, 创建时间, 提交时间, 进程身份键) "
                "VALUES(?, ?, ?, ?, ?, '进行中', '', '', ?, '', ?)",
                (事务id, 资源id, 句柄id, 基础版本, 基础令牌,
                 time.strftime("%Y-%m-%d %H:%M:%S"), 进程身份键))

    def 完成事务(self, *, 事务id: str, 成功: bool, 新版本: str = "") -> None:
        连接 = self._连接()
        with 连接:
            连接.execute(
                "UPDATE 事务 SET 状态=?, 结果=?, 新版本=?, 提交时间=? WHERE 事务id=?",
                ("成功" if 成功 else "失败", "完成", 新版本,
                 time.strftime("%Y-%m-%d %H:%M:%S"), 事务id))

    def 进行中事务(self) -> list[dict[str, Any]]:
        连接 = self._连接()
        结果表 = []
        # 显式列名：迁移库列序与完整建表不同，禁止 SELECT * + 位置索引
        for 行 in 连接.execute(
                "SELECT 事务id, 资源id, 句柄id, 基础版本, 基础令牌, 状态, 结果, "
                "新版本, 创建时间, 提交时间, 进程身份键 FROM 事务 WHERE 状态='进行中'"):
            结果表.append({
                "事务id": 行[0], "资源id": 行[1], "句柄id": 行[2], "基础版本": 行[3],
                "基础令牌": 行[4], "状态": 行[5], "结果": 行[6], "新版本": 行[7],
                "创建时间": 行[8], "提交时间": 行[9], "进程身份键": 行[10],
            })
        return 结果表

    # ---- 结构化锁（栅栏令牌在锁授予时签发） ----
    def 获取锁(self, 资源id: str, *, 操作id: str = "", 事务id: str = "",
               进程身份键: str = "", 项目id: str = "", 所有者: str = "",
               超时秒: float = 3.0, 租约秒: float = 0.0) -> tuple[bool, str, int]:
        """原子抢锁 + 递增栅栏令牌；返回 (成功, 说明, 新令牌)。

        令牌在锁授予时原子递增，永不回退（释放/失败/崩溃都不回退）。
        锁等待有明确超时、退避与总耗时，禁止无限自旋。
        """
        进程身份键 = 进程身份键 or self.身份.身份键()
        截止 = time.time() + 超时秒
        退避 = 0.005
        while True:
            连接 = self._连接()
            with 连接:
                行 = 连接.execute("SELECT 资源id FROM 锁 WHERE 资源id=?", (资源id,)).fetchone()
                if 行 is None:
                    令牌行 = 连接.execute(
                        "SELECT 栅栏令牌 FROM 资源版本 WHERE 资源id=?", (资源id,)).fetchone()
                    if 令牌行 is None:
                        return False, "资源不存在: 无法授锁", 0
                    游标 = 连接.execute(
                        "INSERT OR IGNORE INTO 锁(资源id, 操作id, 事务id, 进程身份键, "
                        "项目id, 所有者, 栅栏令牌, 获取时间, 租约截止) "
                        "VALUES(?, ?, ?, ?, ?, ?, 0, ?, ?)",
                        (资源id, 操作id, 事务id, 进程身份键, 项目id, 所有者,
                         time.time(), time.time() + 租约秒 if 租约秒 > 0 else 0.0))
                    if 游标.rowcount > 0:
                        # 同一原子事务内递增令牌（签发后不回退）
                        连接.execute("UPDATE 资源版本 SET 栅栏令牌=栅栏令牌+1 WHERE 资源id=?", (资源id,))
                        新令牌 = 连接.execute(
                            "SELECT 栅栏令牌 FROM 资源版本 WHERE 资源id=?", (资源id,)).fetchone()[0]
                        连接.execute("UPDATE 锁 SET 栅栏令牌=? WHERE 资源id=?", (新令牌, 资源id))
                        return True, "锁已获取", 新令牌
            if time.time() > 截止:
                return False, f"锁获取超时: 资源 {资源id} 被占用", 0
            time.sleep(退避)
            退避 = min(退避 * 2, 0.1)  # 指数退避，有界

    def 续期锁(self, 资源id: str, *, 操作id: str = "", 事务id: str = "",
               进程身份键: str = "", 令牌: int = 0, 租约秒: float = 10.0) -> bool:
        """锁租约续期：校验操作/事务/进程身份/令牌后才允许续期。"""
        进程身份键 = 进程身份键 or self.身份.身份键()
        连接 = self._连接()
        with 连接:
            游标 = 连接.execute(
                "UPDATE 锁 SET 租约截止=? WHERE 资源id=? AND 事务id=? AND 进程身份键=? AND 栅栏令牌=?",
                (time.time() + 租约秒, 资源id, 事务id, 进程身份键, 令牌))
            return 游标.rowcount > 0

    def 释放锁(self, 资源id: str, *, 操作id: str = "", 事务id: str = "",
               进程身份键: str = "", 令牌: int = 0) -> bool:
        """释放锁：错误进程/错误事务/错误令牌不能释放他人的锁。"""
        进程身份键 = 进程身份键 or self.身份.身份键()
        条件表 = ["资源id=?"]
        参数表: list[Any] = [资源id]
        for 列, 值 in (("事务id", 事务id), ("进程身份键", 进程身份键)):
            if 值:
                条件表.append(f"{列}=?")
                参数表.append(值)
        if 令牌:
            条件表.append("栅栏令牌=?")
            参数表.append(令牌)
        连接 = self._连接()
        with 连接:
            游标 = 连接.execute(f"DELETE FROM 锁 WHERE {' AND '.join(条件表)}", 参数表)
            return 游标.rowcount > 0

    def 锁持有者(self, 资源id: str) -> dict[str, Any]:
        """结构化锁信息（不再拼接字符串）。"""
        连接 = self._连接()
        行 = 连接.execute(
            "SELECT 操作id, 事务id, 进程身份键, 项目id, 所有者, 栅栏令牌, 获取时间, 租约截止 "
            "FROM 锁 WHERE 资源id=?", (资源id,)).fetchone()
        if 行 is None:
            return {}
        return {"操作id": 行[0], "事务id": 行[1], "进程身份键": 行[2], "项目id": 行[3],
                "所有者": 行[4], "栅栏令牌": 行[5], "获取时间": 行[6], "租约截止": 行[7]}

    # ---- 回收证据 ----
    def 记录回收证据(self, *, 句柄id: int, 资源id: str, 类型: str, 原因: str, 版本: str) -> None:
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT INTO 回收证据(证据id, 句柄id, 资源id, 类型, 失效原因, 时间, 版本) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:16], 句柄id, 资源id, 类型, 原因,
                 time.strftime("%Y-%m-%d %H:%M:%S"), 版本))

    def 查询回收证据(self, 资源id: str = "") -> list[dict[str, Any]]:
        连接 = self._连接()
        条件 = "WHERE 资源id=?" if 资源id else ""
        参数 = (资源id,) if 资源id else ()
        结果表 = []
        for 行 in 连接.execute(
                f"SELECT 句柄id, 资源id, 类型, 失效原因, 时间, 版本 FROM 回收证据 {条件}", 参数):
            结果表.append({"句柄id": 行[0], "资源id": 行[1], "类型": 行[2],
                          "失效原因": 行[3], "时间": 行[4], "版本": 行[5]})
        return 结果表

    # ---- 引用计数 ----
    def 增加引用(self, *, 包id: str, 版本: str) -> None:
        连接 = self._连接()
        with 连接:
            引用键 = f"{包id}@{版本}"
            连接.execute(
                "INSERT INTO 引用计数(引用键, 包id, 版本, 计数) VALUES(?, ?, ?, 1) "
                "ON CONFLICT(引用键) DO UPDATE SET 计数=计数+1",
                (引用键, 包id, 版本))

    def 减少引用(self, *, 包id: str, 版本: str) -> int:
        连接 = self._连接()
        with 连接:
            引用键 = f"{包id}@{版本}"
            连接.execute(
                "UPDATE 引用计数 SET 计数=MAX(0, 计数-1) WHERE 引用键=?", (引用键,))
            行 = 连接.execute("SELECT 计数 FROM 引用计数 WHERE 引用键=?", (引用键,)).fetchone()
            return 行[0] if 行 else 0

    def 引用数(self, *, 包id: str, 版本: str) -> int:
        连接 = self._连接()
        行 = 连接.execute("SELECT 计数 FROM 引用计数 WHERE 引用键=?", (f"{包id}@{版本}",)).fetchone()
        return 行[0] if 行 else 0

    # ---- 进程 ----
    def 存活的进程身份表(self, 心跳超时秒: float = 15.0) -> list[dict[str, Any]]:
        """存活进程（心跳新鲜）；pid 复用不误认（指纹参与身份键）。"""
        连接 = self._连接()
        截止 = time.time() - 心跳超时秒
        结果表 = []
        for 行 in 连接.execute("SELECT * FROM 进程 WHERE 最后心跳 > ?", (截止,)):
            结果表.append({
                "身份键": 行[0], "进程id": 行[1], "启动指纹": 行[2], "项目id": 行[3],
                "所有者": 行[4], "实例id": 行[5], "最后心跳": 行[6],
            })
        return 结果表

    def 清理死亡进程资源(self, *, 项目id: str = "", 所有者: str = "",
                          心跳超时秒: float = 15.0) -> list[str]:
        """结构化精确回收：按进程身份键回收 锁/租约/未完成事务/句柄。

        系统进程已不存在时立即回收；进程仍存在但心跳过期时按失联回收。
        只处理项目/所有者匹配的资源；活跃进程锁不被误删；
        清理重复执行幂等。
        """
        from 运行核心.进程身份 import 系统进程存在

        连接 = self._连接()
        截止 = time.time() - 心跳超时秒
        清理列表 = []
        条件表: list[str] = []
        参数表: list[Any] = []
        if 项目id:
            条件表.append("项目id = ?")
            参数表.append(项目id)
        if 所有者:
            条件表.append("所有者 = ?")
            参数表.append(所有者)
        条件 = " AND ".join(条件表) if 条件表 else "1=1"
        候选进程表 = 连接.execute(
            f"SELECT 身份键, 进程id, 最后心跳 FROM 进程 WHERE {条件}", 参数表).fetchall()
        死亡进程表 = [
            (身份键, 进程id)
            for 身份键, 进程id, 最后心跳 in 候选进程表
            if 最后心跳 <= 截止 or not 系统进程存在(int(进程id))
        ]
        with 连接:
            for 身份键, 进程id in 死亡进程表:
                锁行 = 连接.execute("SELECT 资源id FROM 锁 WHERE 进程身份键=?", (身份键,)).fetchall()
                for (资源id,) in 锁行:
                    连接.execute("DELETE FROM 锁 WHERE 资源id=? AND 进程身份键=?", (资源id, 身份键))
                    清理列表.append(f"锁: {资源id}（死亡进程 {进程id}）")
                租约行 = 连接.execute(
                    "SELECT 租约id FROM 租约 WHERE 进程身份键=? AND 已回收=0", (身份键,)).fetchall()
                for (租约id,) in 租约行:
                    self.回收租约(租约id, "所属进程死亡")
                    清理列表.append(f"租约: {租约id}（死亡进程 {进程id}）")
                事务行 = 连接.execute(
                    "SELECT 事务id FROM 事务 WHERE 进程身份键=? AND 状态='进行中'", (身份键,)).fetchall()
                for (事务id,) in 事务行:
                    连接.execute("UPDATE 事务 SET 状态='失败', 结果='进程死亡回滚' WHERE 事务id=?", (事务id,))
                    清理列表.append(f"事务: {事务id}（死亡进程 {进程id}）")
                句柄行 = 连接.execute(
                    "SELECT 句柄id FROM 句柄 WHERE 进程身份键=? AND 状态='有效'", (身份键,)).fetchall()
                for (句柄id,) in 句柄行:
                    self.失效句柄(句柄id, "所属进程死亡")
                    清理列表.append(f"句柄: {句柄id}（死亡进程 {进程id}）")
        return 清理列表

    def 状态快照(self) -> dict[str, Any]:
        连接 = self._连接()
        return {
            "结构版本": self.目标版本,
            "句柄": self.活跃句柄数(),
            "租约": 连接.execute("SELECT COUNT(*) FROM 租约 WHERE 已回收=0").fetchone()[0],
            "资源": 连接.execute("SELECT COUNT(*) FROM 资源版本").fetchone()[0],
            "进行中事务": len(self.进行中事务()),
            "存活进程": len(self.存活的进程身份表()),
            "引用计数": 连接.execute("SELECT COUNT(*) FROM 引用计数 WHERE 计数 > 0").fetchone()[0],
            "锁": 连接.execute("SELECT COUNT(*) FROM 锁").fetchone()[0],
        }

    # ---- 可靠性：WAL 检查点 / 备份 / 关闭 / 损坏恢复 ----
    def WAL检查点(self, 模式: str = "TRUNCATE") -> None:
        """WAL 检查点（TRUNCATE 合并回主库并清空 WAL 日志）；先提交活跃写入。"""
        for 连接 in list(self._连接表.values()):
            try:
                连接.commit()
            except sqlite3.OperationalError:
                pass
            try:
                连接.execute(f"PRAGMA wal_checkpoint({模式})")
            except sqlite3.OperationalError:
                pass

    def 备份(self, 目标路径: Path) -> bool:
        """原子备份数据库（含 WAL 日志）。"""
        try:
            self.WAL检查点("TRUNCATE")
            目标路径 = Path(目标路径)
            目标路径.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(self.数据库路径, 目标路径)
            return 目标路径.is_file()
        except (OSError, sqlite3.OperationalError):
            return False

    def 关闭(self) -> None:
        """在没有其他活跃调用线程时关闭全部连接。"""
        当前线程 = threading.current_thread()
        with self._连接锁:
            活跃工作线程 = [
                线程 for 线程 in self._连接线程表.values()
                if 线程 is not 当前线程 and 线程.is_alive()
            ]
        if 活跃工作线程:
            raise RuntimeError("仍有工作线程正在使用权威状态，拒绝关闭数据库")
        self._清理死连接()
        self.WAL检查点("TRUNCATE")
        with self._连接锁:
            for 连接 in list(self._连接表.values()):
                try:
                    连接.close()
                except sqlite3.OperationalError:
                    pass
            self._连接表.clear()
            self._连接线程表.clear()

    def 校验结构(self) -> tuple[bool, str]:
        """结构校验：版本一致 + 必需列齐全 + integrity_check 返回 ok。"""
        try:
            连接 = self._连接()
            with 连接:
                self._校验版本结构(连接, self.目标版本)
                行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()
                if not 行 or 行[0] != self.目标版本:
                    return False, f"结构版本不一致: {行[0] if 行 else '无'}"
            return True, "结构完整"
        except Exception as 错误:
            return False, str(错误)

    def 损坏恢复(self, 备份目录: Path | None = None) -> tuple[bool, str]:
        """数据库损坏恢复：integrity_check 返回 ok 才认为完整；损坏则从最新备份恢复。

        恢复后重新校验 结构版本/必需列/完整性，再允许继续运行。
        """
        try:
            校验连接 = sqlite3.connect(f"file:{self.数据库路径}?mode=ro", uri=True)
            结果 = 校验连接.execute("PRAGMA integrity_check").fetchone()
            校验连接.close()
            if 结果 and 结果[0] == "ok":
                return True, "数据库完整"
            raise sqlite3.DatabaseError(f"完整性检查: {结果}")
        except sqlite3.DatabaseError:
            pass
        备份目录 = Path(备份目录 or (self.存储目录 / "备份"))
        if not 备份目录.is_dir():
            return False, "数据库损坏且无可用备份"
        for 备份文件 in sorted(备份目录.glob("*.db"), reverse=True):
            try:
                shutil.copy(备份文件, self.数据库路径)
                for 连接 in list(self._连接表.values()):
                    try:
                        连接.close()
                    except sqlite3.Error:
                        pass
                self._连接表.clear()
                self._连接线程表.clear()
                # 恢复后重新校验结构
                成功, 消息 = self.校验结构()
                if not 成功:
                    return False, f"备份恢复后结构校验失败: {消息}"
                return True, f"已从备份恢复: {备份文件.name}"
            except (OSError, sqlite3.OperationalError):
                continue
        return False, "数据库损坏且所有备份恢复失败"
