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

锁租约语义（P2-7，2026-09-18 硬化）：`锁.租约截止 > 0` 表示持有者**只在租约内**
持有锁；租约截止早于当前时刻即为弃锁，其它持有者可 CAS 抢占（判据 = 观察到的
`租约截止` 原值；同一事务内递增栅栏令牌并写回收证据）。被抢占者的提交/续期/释放
都会因令牌判据被拒。`租约截止 = 0` 表示**无租约**（只有进程死亡清理能回收该锁），
与硬化前逐字一致。

机器判据（P1-6 / P2-8，2026-09-18 硬化）：迁移可恢复性判 **sqlite 错误码**
（`迁移可重试主码`）、并发冲突判 **sqlite 错误码 + 异常类型**（`是并发冲突`），
禁止解析 sqlite 英文消息文本做控制分支——文案给人看，错误码给机器判。
"""
from __future__ import annotations

import atexit
import contextlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
import weakref
from pathlib import Path
from typing import Any

from 运行核心.进程身份 import 创建进程身份
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假
# `只读库URI` / `连接真实库路径` 的唯一出处已下移 `公共契约/运行时/数据库URI.py`
# （2026-09-18 同类收口：八个层共用的原语不能住在最高层——`支持库`/`模块库` 按
# `依赖防火墙.允许依赖表` 够不到 运行核心，只能各写一份裸拼，正是本次要消灭的）。
from 公共契约.运行时.数据库URI import 只读库URI, 连接真实库路径

状态结构版本 = "1.2.0"  # 1.1.0：栅栏令牌列；1.2.0：结构化锁表+租约/句柄/事务进程身份键+迁移器重构

# 权威账本「已终态行」真删前的保留窗口（秒）。可配置常量：类属性 `保留窗口秒` 可覆盖，
# 清理器入参可逐次覆盖，禁止把窗口天数硬编码进 SQL。
# 与内存句柄表的口径一致（有界即正确）：句柄体系只留「有效行 + 近期已失效行」，
# 账本同理只留「有效行 + 保留窗口内的终态行」；窗口按天取，与现场规模匹配
# （18 天累积 句柄 9130 / 租约 9166 / 进程 3633 行）。
账本保留窗口秒 = 7 * 24 * 3600.0

# 稳定错误码：底层异常一律转换为以下稳定枚举，不得把 Exception 文本直接返回用户/Agent。
# B-8（2026-09-16）：**对外错误只走中文**（决策记录 0003）。本表原先左值中文、右值英文
# 枚举，等于平台内部两套错误语义；现全部收敛为中文码——左值是业务语义键、右值是**对外
# 码本身**，两者一致（查询平台授权口径的只读模型会把本表原样返回给 Agent，英文枚举
# 会直接漏到对外返回值里）。
稳定错误码 = {
    "资源不存在": "资源不存在",
    "版本冲突": "版本冲突",
    "旧令牌提交": "旧令牌提交",
    "令牌不匹配": "令牌不匹配",
    "锁所有权不匹配": "锁所有权不匹配",
    "租约过期": "租约过期",
    "锁获取超时": "锁获取超时",
    "权限不足": "权限不足",
    "重复能力": "重复能力",
    "签名失效": "签名失效",
    "未签名": "未签名",
    "已撤销": "已撤销",
    "内容变化": "内容变化",
    "参数不合法": "参数不合法",
    "迁移失败": "迁移失败",
    "数据库损坏": "数据库损坏",
    "内部错误": "内部错误",
}

# —— 机器判据（P1-6 / P2-8，2026-09-18 硬化）：sqlite 一律判错误码，禁止解析英文消息 ——
# sqlite 主错误码 = 错误码去掉扩展位（SQLITE_BUSY_SNAPSHOT=517 → 主码 5，
# SQLITE_BUSY_TIMEOUT=773 → 主码 5）。现场实测（python3.14 + sqlite 3.53）：
# `错误.sqlite_errorcode` 给的是**扩展码**（517），所以必须取主码再比对。
sqlite主码掩码 = 0xFF
# 并发冲突主码（P2-8）：写事务撞上其它进程/线程 → 可重试，不是内部错误。
并发冲突主码 = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})
# 结构迁移可重试主码（P1-6）：原判据解析三条英文消息（no such table /
# database is locked / database table is locked），现按同一批错误的**主码**判定：
# SQLITE_ERROR=1（no such table）、SQLITE_BUSY=5（database is locked）、
# SQLITE_LOCKED=6（database table is locked）。SQLITE_ERROR 是 sqlite 的通用码，
# 该判据因此略宽于原文案（no such column 之类也会重试）——代价有界（最多 4 次尝试、
# 合计 ≤0.3 秒），最终抛出的仍是同一条「结构迁移失败」异常。
迁移可重试主码 = frozenset({sqlite3.SQLITE_ERROR, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})


def sqlite主错误码(错误: BaseException) -> int:
    """取 sqlite 主错误码（去扩展位）；非 sqlite 异常或取不到码时返回 0。

    0 是「未知码」：任何 `in 主码集合` 的判据都不会命中——绝不把未知情况当可重试。
    自造 `sqlite3.Error` 子类没有 `sqlite_errorcode` 属性（现场实测），走的就是这条。
    """
    码 = getattr(错误, "sqlite_errorcode", None)
    if not isinstance(码, int):
        return 0
    return 码 & sqlite主码掩码


def 是并发冲突(错误: BaseException) -> bool:
    """并发冲突判定（P2-8）：机器判据 = 异常类型 + sqlite 错误码，不看文案。"""
    return (isinstance(错误, sqlite3.OperationalError)
            and sqlite主错误码(错误) in 并发冲突主码)


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


def 锁所有权判据(资源id: str, *, 操作id: str = "", 事务id: str = "",
                进程身份键: str = "", 令牌: int = 0,
                必判: tuple[str, ...] = ()) -> tuple[list[str], list[Any]]:
    """锁所有权 WHERE 判据的唯一生成器：`释放锁`/`续期锁` 同口径，禁止各写一套。

    维度语义（与 获取锁 写入的列一一对应）：
    - 非空/非零 ⇒ **必须匹配**（值进了 WHERE）；
    - 空串/零 ⇒ 默认**不加入判据**（调用方未提供该维度）；`必判` 里的列例外，
      即使为空也照样进 WHERE，用于保持「原先就硬性要求某些维度」的方法行为不变。

    为什么要有它：`释放锁()` 原签名收 `操作id` 却从不判它，`续期锁()` 同形——
    等于「只校验部分所有权」，谁拿到 事务id+进程身份键+令牌 就能删/续别人的锁，
    哪怕 操作id 已经不是签发时那一个。锁是
    `获取锁(资源id, 操作id=…, 事务id=…)` 签发的（见 `运行核心/资源协调/句柄服务.py`
    更新受管状态），`操作id` 必须参与判据才算完整所有权校验。
    """
    条件表 = ["资源id=?"]
    参数表: list[Any] = [资源id]
    for 列, 值 in (("操作id", 操作id), ("事务id", 事务id),
                  ("进程身份键", 进程身份键), ("栅栏令牌", 令牌)):
        if 值 or 列 in 必判:
            条件表.append(f"{列}=?")
            参数表.append(值)
    return 条件表, 参数表


# 固定迁移序列表：(目标版本, 迁移函数名)；顺序执行，版本只增不减
迁移序列表 = [
    ("1.0.0", "_迁移到100"),
    ("1.1.0", "_迁移到110"),
    ("1.2.0", "_迁移到120"),
]

_活动状态实例: weakref.WeakSet = weakref.WeakSet()


def _退出时关闭状态连接() -> None:
    """解释器退出前关闭所有仍存活的状态对象连接。"""
    for 状态 in list(_活动状态实例):
        try:
            状态.关闭()
        except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
            记录忽略('权威状态._退出时关闭状态连接', 错误)


atexit.register(_退出时关闭状态连接)


class 权威状态:
    """权威状态存储（sqlite3 WAL）。

    只读校验的两个坑（P2-13③，2026-09-18 现场实测钉死，下一个人别再踩）：

    1. **空库的 `PRAGMA integrity_check` 照样返回 `ok`** —— 这是 SQLite 的既定行为
       （实测空库、截断前缀现场新建的库都返回 `ok`），不是缺陷。
       推论：「完整性 ok」单独**不足以**证明「我读的就是目标库」：只要连接开到了
       另一个（哪怕是现场新建的）空库，检查就恒过 ⇒ **真实损坏被掩盖**。
       故凡是用只读连接判完整性，必须先断言「连接实际打开的库 == 目标库路径」
       （`只读库URI()` + `连接真实库路径()`），不许用「再查一次 integrity_check」
       这种同源判据糊过去。
    2. **`file:` URI 必须 percent-encode**（唯一构造口径 = `只读库URI()`）：
       `f"file:{路径}?mode=ro"` 在路径含 `#`/`?` 时被 URI 解析器**静默截断**——
       `#` 起（含其后拼的 `?mode=ro`）整体算 fragment；`?` 起算 query，把路径尾部
       连同 `?mode=ro` 一起吞掉。后果有三层且**全不报错**：打开截断前缀名的空库、
       **只读模式彻底失效（该连接实测可写）**、`integrity_check` 对空库返回 `ok`。
    """

    # 类属性（子类可覆盖扩展）：目标结构版本 / 迁移序列表 / 结构校验规则表 / 账本保留窗口
    目标版本 = 状态结构版本
    保留窗口秒 = 账本保留窗口秒  # 覆盖即可改账本历史行保留时长（门禁/运维裁决用）
    迁移序列表 = [
        ("1.0.0", "_迁移到100"),
        ("1.1.0", "_迁移到110"),
        ("1.2.0", "_迁移到120"),
    ]
    校验规则表 = {
        "1.0.0": {"表": ["元信息", "句柄", "租约", "资源版本", "事务", "锁", "进程", "回收证据", "引用计数"]},
        "1.1.0": {"列": [("资源版本", "栅栏令牌"), ("事务", "基础令牌")]},
        "1.2.0": {"列": [("锁", "操作id"), ("锁", "事务id"), ("锁", "进程身份键"),
                          ("锁", "项目id"), ("锁", "所有者"), ("锁", "栅栏令牌"),
                          ("锁", "获取时间"), ("锁", "租约截止"),
                          ("租约", "进程身份键"), ("句柄", "进程身份键"),
                          ("事务", "进程身份键")]},
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
        _活动状态实例.add(self)
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

    @contextlib.contextmanager
    def _事务(self, 连接: sqlite3.Connection | None = None):
        """交出「本次写入用的事务边界」；已在事务中则**复用**，不嵌套、不提前提交。

        A1 根因：嵌套调用 `回收租约()` / `失效句柄()` 原先各自 `self._连接()` 并
        `with 连接`——内层退出即提交**外层**事务，外层原子性被破坏（已实证：外层
        中途抛异常后内层改动仍落盘：锁已删、租约已回收、句柄已失效、证据已写，
        而外层事务仍标「进行中」）。三种情形各有出口：

        - 传 `连接`（本文件内部调用点，如 `清理死亡进程资源`）：复用同一连接，
          提交/回滚由最外层 `with 连接` 统一决定；
        - 不传且当前线程连接**已在事务中**（外层已写过、正处在 `with 连接:` 里）：
          同样只交出连接、不提交也不结束事务——把「内层提前提交外层」这个隐蔽
          破坏兜死。外层没写过任何东西时连接尚未进入事务，内层按自身事务收口，
          此时外层也没有可被破坏的写入；
        - 不传且无活动事务（普通公开调用）：按普通事务起止，与原先行为一致。
        """
        连接 = self._连接() if 连接 is None else 连接
        if 连接.in_transaction:
            yield 连接  # 已在事务中：复用，提交/回滚交给最外层
            return
        with 连接:
            yield 连接

    def _清理死连接(self) -> None:
        """显式回收已结束线程的连接；普通读取路径不得调用本方法。"""
        with self._连接锁:
            for 线程id, 线程 in list(self._连接线程表.items()):
                if not 线程.is_alive():
                    self._连接表[线程id].close()
                    del self._连接表[线程id]
                    del self._连接线程表[线程id]

    def 释放当前线程连接(self) -> None:
        """关闭并移除当前线程的缓存连接（供长驻后台维护线程在两次任务之间让出连接）。

        长驻线程（如账本周期维护）若一直持有线程级连接，会让 关闭() 的
        「仍有工作线程正在使用权威状态」判据在退出时误报。维护线程每轮收尾
        调用本方法，退出路径只剩正在执行的那一次，不阻塞正常关闭。
        """
        线程id = threading.get_ident()
        with self._连接锁:
            连接 = self._连接表.pop(线程id, None)
            self._连接线程表.pop(线程id, None)
        if 连接 is None:
            return
        try:
            连接.close()
        except sqlite3.Error as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
            记录忽略('权威状态.释放当前线程连接', 错误)

    # ---- 结构迁移器（初始化/迁移分离） ----
    def _初始化(self) -> None:
        """打开数据库并执行结构迁移；数据库损坏时自动从备份恢复后再初始化。"""
        with self._本地锁:
            try:
                # 迁移脚本包含历史 DDL；旧版本 SQLite 的 executescript 可能在
                # 并发进程间短暂暴露中间 schema。对可恢复的 schema 竞态重试，
                # 其它迁移错误仍立即失败，避免吞掉真实损坏。
                # P1-6（2026-09-18 硬化）：可恢复性判 **sqlite 错误码**（原始异常由
                # `_迁移结构` 挂在 `__cause__` 上），禁止解析 sqlite 英文消息文本。
                for 次数 in range(4):
                    try:
                        self._迁移结构()
                        break
                    except RuntimeError as 错误:
                        原因 = 错误.__cause__
                        可恢复 = (isinstance(原因, sqlite3.OperationalError)
                                  and sqlite主错误码(原因) in 迁移可重试主码)
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
                                f"结构迁移失败 {当前版本}→{目标}: {错误}（已回滚，版本保持 {当前版本}）"
                            ) from 错误
                        连接.execute("INSERT OR REPLACE INTO 元信息(键, 值) VALUES('结构版本', ?)", (目标,))
                # for 循环后兜底：版本匹配但结构不完整的错误历史状态无法修复时失败。
                # 原判据 `版本元组(状态结构版本) < 版本元组("1.0.0")` 拿模块常量
                # 状态结构版本("1.2.0") 与 "1.0.0" 比，恒为 (1,2,0)<(1,0,0)=False，
                # 整个兜底是死分支——假升级重放迁移后结构仍不完整也会被静默放行。
                # 按原意改为「重放后复验结构」：仍不完整即说明现有迁移序列表修不好它。
                if 需要补列 and not self._校验当前结构(连接):
                    raise RuntimeError(
                        f"结构校验失败: 元信息版本已是 {目标版本} 但表结构不完整，"
                        f"按序重放迁移后仍未补齐")
                连接.execute("DELETE FROM 元信息 WHERE 键='迁移失败'")
            except Exception:
                连接.rollback()
                raise

    def _校验当前结构(self, 连接: sqlite3.Connection) -> bool:
        """当前版本完整结构校验（列齐全才认为版本真实）。"""
        try:
            self._校验版本结构(连接, self.目标版本)
            return 真
        except RuntimeError:
            return 假

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
        结构化锁列 = ("操作id", "事务id", "进程身份键", "项目id", "所有者",
                      "栅栏令牌", "获取时间", "租约截止")
        锁列 = {行[1] for 行 in 连接.execute("PRAGMA table_info(锁)").fetchall()}
        if "持有者" in 锁列:
            # 旧布局（持有者拼接字符串）才整表重建；不能用「缺 操作id」判定，
            # 半结构化表也缺 操作id，走重建会因 锁旧表 无 持有者 列而报错。
            连接.execute("ALTER TABLE 锁 RENAME TO 锁旧表")
            连接.executescript("""
                -- 租约截止：> 0 表示该锁带租约（过期即可被 CAS 抢占，见 获取锁 P2-7）；
                --           = 0 表示无租约，只有进程死亡清理能回收该锁。
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
        else:
            # 结构化布局：逐列补回缺失列（假升级 / 手工删列的错误历史状态）。
            # 原判据只认 操作id 一列，缺 进程身份键 等列时整段跳过 → 假升级状态
            # 永远修不好，只会在 _校验版本结构 处直接抛错（见 _迁移结构 的
            # 「假升级错误历史补列」承诺）。半结构化表不能走整表重建：重建的
            # INSERT 要读 锁旧表.持有者，而它没有该列。
            锁列定义 = {"操作id": "TEXT DEFAULT ''", "事务id": "TEXT DEFAULT ''",
                        "进程身份键": "TEXT DEFAULT ''", "项目id": "TEXT DEFAULT ''",
                        "所有者": "TEXT DEFAULT ''", "栅栏令牌": "INTEGER DEFAULT 0",
                        "获取时间": "REAL DEFAULT 0", "租约截止": "REAL DEFAULT 0"}
            for 列 in 结构化锁列:
                self._补列(连接, "锁", 列, 锁列定义[列])

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

    def 全部句柄(self, *, 仅有效: bool = 假) -> list[dict[str, Any]]:
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

    def 有效句柄与租约(self) -> list[dict[str, Any]]:
        """一次性取回「有效句柄 + 其最新租约」：消除启动恢复的 N+1 逐行查询。

        每个句柄取 最后心跳 最大的那条租约（与 读取租约 同口径，含已回收租约）。
        现场 8983 个有效句柄逐行调 读取租约 要 2.99s（租约.句柄id 无索引 ⇒
        每行一次全表扫），单条窗口查询可降到毫秒级；启动恢复只依赖本方法。
        返回按 句柄id 升序：[{句柄字段…, "租约": 租约字典 或 None}, …]。
        """
        连接 = self._连接()
        结果表: list[dict[str, Any]] = []
        for 行 in 连接.execute(
            "WITH 最新租约 AS ("
            " SELECT 租约id, 资源id, 项目id, 所有者, 句柄id, 空闲超时秒, 硬截止时间,"
            "        最后心跳, 已回收, 进程身份键,"
            "        ROW_NUMBER() OVER (PARTITION BY 句柄id ORDER BY 最后心跳 DESC) AS 序次"
            " FROM 租约)"
            " SELECT h.句柄id, h.句柄类型, h.资源id, h.项目id, h.所有者, h.状态, h.版本,"
            "        h.创建时间, h.失效时间, h.失效原因, h.进程身份键,"
            "        l.租约id, l.资源id, l.项目id, l.所有者, l.句柄id, l.空闲超时秒,"
            "        l.硬截止时间, l.最后心跳, l.已回收, l.进程身份键"
            " FROM 句柄 h LEFT JOIN 最新租约 l ON l.句柄id = h.句柄id AND l.序次 = 1"
            " WHERE h.状态='有效' ORDER BY h.句柄id"
        ):
            租约 = None
            if 行[11] is not None:
                租约 = {"租约id": 行[11], "资源id": 行[12], "项目id": 行[13],
                        "所有者": 行[14], "句柄id": 行[15], "空闲超时秒": 行[16],
                        "硬截止时间": 行[17], "最后心跳": 行[18],
                        "已回收": bool(行[19]), "进程身份键": 行[20]}
            结果表.append({
                "句柄id": 行[0], "句柄类型": 行[1], "资源id": 行[2],
                "项目id": 行[3], "所有者": 行[4], "状态": 行[5], "版本": 行[6],
                "创建时间": 行[7], "失效时间": 行[8], "失效原因": 行[9],
                "进程身份键": 行[10], "租约": 租约,
            })
        return 结果表

    def 失效句柄(self, 句柄id: int, 原因: str, *,
                 连接: sqlite3.Connection | None = None) -> bool:
        """失效句柄；`连接` 传入既有连接时复用该连接的事务，不再新开连接提交。

        A1 根因（严重）：本方法原写法无条件 `self._连接()` + `with 连接`。当它被
        处在 `with 连接` 里的调用方嵌套调用时，内层 `with` 退出即提交**外层**事务，
        外层任一失败都被吞掉（已实证：外层中途抛异常后内层改动仍落盘）。
        传 `连接` 即复用同一事务，提交/回滚统一由最外层决定。
        不传时行为与原先完全一致（自有连接、自有事务）。
        """
        with (self._事务() if 连接 is None
              else contextlib.nullcontext(连接)) as 当前连接:
            游标 = 当前连接.execute(
                "UPDATE 句柄 SET 状态='已失效', 失效时间=?, 失效原因=? WHERE 句柄id=? AND 状态='有效'",
                (time.strftime("%Y-%m-%d %H:%M:%S"), 原因, 句柄id))
            return 游标.rowcount > 0

    def 失效句柄并记录证据(self, *, 句柄id: int, 资源id: str,
                         类型: str, 原因: str, 版本: str,
                         连接: sqlite3.Connection | None = None) -> bool:
        """在同一 SQLite 事务内更新句柄终态并写入回收证据。

        `连接` 传入既有连接时复用该连接的事务（本文件既有的正确路径做法），
        不传时自有连接自有事务。
        """
        时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        with (self._事务() if 连接 is None
              else contextlib.nullcontext(连接)) as 当前连接:
            游标 = 当前连接.execute(
                "UPDATE 句柄 SET 状态='已失效', 失效时间=?, 失效原因=? "
                "WHERE 句柄id=? AND 状态='有效'", (时间, 原因, 句柄id))
            if 游标.rowcount == 0:
                return 假
            当前连接.execute(
                "INSERT INTO 回收证据(证据id, 句柄id, 资源id, 类型, 失效原因, 时间, 版本) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:16], 句柄id, 资源id, 类型, 原因, 时间, 版本))
            return 真

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

    def 回收租约(self, 租约id: str, 原因: str, *, 仅当过期: bool = 假,
                 现在: float | None = None,
                 连接: sqlite3.Connection | None = None) -> bool:
        """回收租约（置 已回收=1 并级联失效句柄）。

        `仅当过期=True` 用于**过期扫描**：把过期判据放进 UPDATE 的 WHERE 里做
        CAS，消灭「SELECT 判过期 → UPDATE 无条件置已回收」之间被续租抢进的窗口
        （长租句柄空闲超时后恰在窗口内续租成功，会被旧实现无条件误杀）。
        rowcount==0 表示租约已被续租/已回收，跳过，不得误杀。
        显式失效（句柄主动失效、所属进程死亡）保持无条件语义，调用方传默认值。

        `连接` 传入既有连接时复用该连接的事务（A1 根因修复）：本方法原写法无条件
        `self._连接()` + `with 连接`，被处在 `with 连接` 里的调用方嵌套调用时，
        内层退出即提交外层事务——外层任一失败都被吞掉（已实证）。
        不传时行为与原先完全一致（自有连接、自有事务）。
        """
        时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        with (self._事务() if 连接 is None
              else contextlib.nullcontext(连接)) as 当前连接:
            if 仅当过期:
                现在 = time.time() if 现在 is None else 现在
                游标 = 当前连接.execute(
                    "UPDATE 租约 SET 已回收=1 WHERE 租约id=? AND 已回收=0 AND "
                    "(硬截止时间 < ? OR (空闲超时秒 > 0 AND ? - 最后心跳 > 空闲超时秒))",
                    (租约id, 现在, 现在),
                )
            else:
                游标 = 当前连接.execute(
                    "UPDATE 租约 SET 已回收=1 WHERE 租约id=? AND 已回收=0", (租约id,))
            if 游标.rowcount == 0:
                return 假
            行 = 当前连接.execute(
                "SELECT 句柄id, 资源id FROM 租约 WHERE 租约id=?", (租约id,)
            ).fetchone()
            if 行 and 行[0]:
                # 必须复用当前连接完成句柄终态和回收证据写入；调用
                # 失效句柄() 会打开第二个连接，破坏租约事务原子性。
                句柄游标 = 当前连接.execute(
                    "UPDATE 句柄 SET 状态='已失效', 失效时间=?, 失效原因=? "
                    "WHERE 句柄id=? AND 状态='有效'",
                    (时间, 原因, 行[0]),
                )
                if 句柄游标.rowcount:
                    句柄行 = 当前连接.execute(
                        "SELECT 句柄类型, 版本 FROM 句柄 WHERE 句柄id=?", (行[0],)
                    ).fetchone()
                    当前连接.execute(
                        "INSERT INTO 回收证据(证据id, 句柄id, 资源id, 类型, 失效原因, 时间, 版本) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (uuid.uuid4().hex[:16], 行[0], 行[1],
                         句柄行[0] if 句柄行 else "", 原因, 时间,
                         句柄行[1] if 句柄行 else ""),
                    )
            return 真

    def 扫描过期租约(self) -> list[str]:
        """空闲超时/硬截止过期的租约（幂等回收）。

        SELECT 只用于发现候选；真正的过期判定由 回收租约(仅当过期=True) 的
        条件 UPDATE 在同一条 SQL 内复检（CAS），SELECT→UPDATE 之间被续租的
        租约 rowcount=0 被跳过并**不计入返回清单**，保证回带的就是真回收的。
        """
        连接 = self._连接()
        现在 = time.time()
        候选列表 = []
        for 行 in 连接.execute(
                "SELECT 租约id FROM 租约 WHERE 已回收=0 AND "
                "(硬截止时间 < ? OR (空闲超时秒 > 0 AND ? - 最后心跳 > 空闲超时秒))",
                (现在, 现在)):
            候选列表.append(行[0])
        已回收列表 = []
        for 租约id in 候选列表:
            if self.回收租约(租约id, "空闲超时或硬截止", 仅当过期=真, 现在=现在):
                已回收列表.append(租约id)
        return 已回收列表

    # ---- 唤醒重校准（审计 §9-B6） ----

    #: 元信息表里存放「上次观测到的双时钟读数」的键（跨重启的唤醒检测基线）。
    时钟观测键 = "时钟观测读数"

    def 记录时钟观测(self) -> Any:
        """把当前双时钟读数写进元信息表（唯一事实源），供下次启动做唤醒判定。

        为什么要落盘：唤醒检测的基线一旦只存在内存里，「睡下 → 进程被重启」这条
        路径上基线就丢了，启动时的账本恢复又会拿睡前的墙钟截止时间把租约判死
        （审计 §9-B6 的同一条缺陷，只是发生在启动而非运行期）。
        存的是 `墙钟|单调` 一对：跨重启时 `单调` 会回退（本机开机时基归零），
        比对时据「单调是否回退」区分**重启**（不是睡眠，跳过）与**睡眠**（差值即睡眠秒）。
        """
        from 运行核心.时钟校准 import 当前读数

        读数 = 当前读数()
        连接 = self._连接()
        with 连接:
            连接.execute(
                "INSERT INTO 元信息(键, 值) VALUES(?, ?) "
                "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (self.时钟观测键, f"{读数.墙钟!r}|{读数.单调!r}"))
        return 读数

    def 检测跨重启唤醒(self, 阈值秒: float | None = None):
        """启动路径：按上次落盘的双时钟读数判定「睡下之后才启动」的唤醒。

        返回 `唤醒判定` 或 None（无基线 / 不构成唤醒 / 单调时钟回退 = 重启而非睡眠）。
        判定口径与运行期完全一致（同一个 `判刚唤醒` 纯函数），只是把「上次读数」
        从内存换成落盘值。判定完成后把本次读数写回（推进基线）。
        """
        from 运行核心.时钟校准 import 判刚唤醒, 时钟读数, 默认唤醒阈值秒

        连接 = self._连接()
        行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键=?",
                          (self.时钟观测键,)).fetchone()
        本次读数 = self.记录时钟观测()
        if 行 is None or not 行[0]:
            return None
        try:
            墙钟文本, 单调文本 = str(行[0]).split("|", 1)
            上次读数 = 时钟读数(墙钟=float(墙钟文本), 单调=float(单调文本))
        except (ValueError, TypeError):
            return None  # 基线不可解析：不猜，按「无基线」处理（下次会重写）
        if 本次读数.单调 < 上次读数.单调:
            # 单调时钟回退 = 本机重启过（开机时基归零），不是睡眠，不构成唤醒。
            return None
        判定 = 判刚唤醒(上次读数, 本次读数,
                        阈值秒=(默认唤醒阈值秒 if 阈值秒 is None else 阈值秒),
                        序号=1)
        return 判定 if 判定.刚唤醒 else None

    def 唤醒重判租约(self, 判定=None) -> dict[str, Any]:
        """刚唤醒 → **租约按单调时钟重判**，不沿用睡眠期间的墙钟判定。

        **为什么必须有这一步**（审计 §9-B6 根因）：`硬截止时间` 与 `最后心跳`
        是**落盘墙钟秒**；合盖 5 小时唤醒后墙钟跳 5 小时，于是「截止时间 < 现在」
        对全部租约同时成立 → 持有者一秒没跑、租约却**集体过期**、句柄被判超时失效。
        持有者是被冻住的，不是闲置超时。这里给出与「真闲置」不同的判据（复核口径）：
        只有**截止时间落在睡眠窗口之前**（`墙钟截止 ≤ 墙钟现在 − 睡眠秒`）的租约才算真过期；
        落在 `(墙钟现在 − 睡眠秒, 墙钟现在]` 里的，是睡眠期间才越过的 → 一律存活，
        并把截止时间**整体顺延睡眠秒数**（等于把持有者被冻住的那段时间还给它），
        同时推 `最后心跳`，使后续判据回到「睡眠没发生过」的等价状态。

        为什么顺延而不是只跳过：只跳过的话，下一轮巡检（同一次唤醒之后不久）
        会拿同一个「现在」再判一次，租约仍然是过期的 —— 判据只在本次调用里有效。
        顺延把修正**落进账本**，判据对后续所有调用一致。

        幂等：同一次唤醒重复调用（多个组件各问一次）结果一致；睡眠秒为 0
        （`判定.刚唤醒=False`）时**零动作**，返回全 0 复核结果。

        本方法只动 租约.硬截止时间/最后心跳（都是落盘墙钟口径），不新增后台线程、
        不新增巡检周期 —— 挂在调用方本来就有的唤醒检测点上。
        """
        from 运行核心.时钟校准 import 最新唤醒

        判定 = 判定 if 判定 is not None else 最新唤醒()
        if 判定 is None or not 判定.刚唤醒:
            return {"刚唤醒": 假, "睡眠秒": 0.0, "存活租约数": 0, "真过期租约数": 0,
                    "顺延租约数": 0, "顺延秒": 0.0}
        睡眠秒 = float(判定.睡眠秒)
        连接 = self._连接()
        现在墙钟 = float(判定.窗口终点墙钟)
        睡眠起点墙钟 = float(判定.窗口起点墙钟)
        结果表: dict[str, Any] = {"刚唤醒": 真, "睡眠秒": 睡眠秒,
                                  "存活租约数": 0, "真过期租约数": 0,
                                  "顺延租约数": 0, "顺延秒": 睡眠秒}
        with 连接:
            for 租约id, 截止, 心跳 in 连接.execute(
                    "SELECT 租约id, 硬截止时间, 最后心跳 FROM 租约 WHERE 已回收=0").fetchall():
                try:
                    截止值 = float(截止 or 0.0)
                except (TypeError, ValueError):
                    截止值 = 0.0
                if 截止值 <= 0 or 截止值 > 现在墙钟:
                    # 无截止（=0，从未写过）或尚未到期：本就不在过期候选里，零动作。
                    continue
                if 截止值 > 睡眠起点墙钟:
                    # 睡眠期间才越过 → 持有者被冻住，判存活并把冻住的时间还给它。
                    # 同时推 最后心跳：后续的「心跳停摆」兜底判据也回到睡眠前口径。
                    游标 = 连接.execute(
                        "UPDATE 租约 SET 硬截止时间=?, 最后心跳=? "
                        "WHERE 租约id=? AND 已回收=0",
                        (截止值 + 睡眠秒, 现在墙钟, 租约id))
                    if 游标.rowcount:
                        结果表["顺延租约数"] += 1
                    else:
                        # CAS 落空（同轮被释放/回收）：不计入动作，如实记存活。
                        结果表["存活租约数"] += 1
                else:
                    # 截止时间在睡眠之前就已越过 → 真闲置/真超时，维持原判不重判。
                    结果表["真过期租约数"] += 1
        return 结果表

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

        并发冲突（P2-8）：写事务撞上其它进程/线程（sqlite 主码 BUSY/LOCKED，含
        SQLITE_BUSY_SNAPSHOT）时返回 `(假, "并发冲突: …可原样重试")`——**可重试**语义，
        不再冒泡成「内部错误」。判据是 sqlite 错误码，不是文案。
        """
        进程身份键 = 进程身份键 or self.身份.身份键()
        连接 = self._连接()
        try:
            return self._提交资源单事务(
                连接=连接, 资源id=资源id, 期望版本=期望版本, 期望令牌=期望令牌,
                事务id=事务id, 进程身份键=进程身份键, 项目id=项目id,
                所有者=所有者, 新值=新值, 新摘要=新摘要)
        except sqlite3.OperationalError as 错误:
            if not 是并发冲突(错误):
                raise
            # P2-8（2026-09-18 硬化）：WAL 下「先读后写」的写事务后到者会撞
            # SQLITE_BUSY / SQLITE_BUSY_SNAPSHOT（busy handler 对快照冲突不自动
            # 重试）。这是**并发冲突（可重试）**，不是内部错误——归成明确失败交回
            # 调用方重试，禁止冒泡成「内部错误」丢掉可重试语义。
            # 判据是 sqlite 错误码（`是并发冲突`），不是文案。
            名称 = getattr(错误, "sqlite_errorname", "") or "并发写冲突"
            return 假, (f"并发冲突: 资源 {资源id} 的写事务与其它进程/线程重叠（{名称}），"
                        f"本次未提交，可原样重试")

    def _提交资源单事务(self, *, 连接: sqlite3.Connection, 资源id: str,
                        期望版本: str, 期望令牌: str, 事务id: str,
                        进程身份键: str, 项目id: str, 所有者: str,
                        新值: Any, 新摘要: str) -> tuple[bool, str]:
        """提交的读校验 + 条件更新（事务边界与并发冲突归类由 `提交资源` 统一负责）。"""
        with 连接:
            锁行 = 连接.execute(
                "SELECT 事务id, 进程身份键, 项目id, 所有者, 栅栏令牌 FROM 锁 WHERE 资源id=?",
                (资源id,)).fetchone()
            if 锁行 is None:
                return 假, "锁不存在: 提交必须持有资源锁"
            if 锁行[0] and 锁行[0] != 事务id:
                return 假, f"锁所有权不匹配: 锁属事务 {锁行[0]}，请求 {事务id}"
            if 锁行[1] and 锁行[1] != 进程身份键:
                return 假, f"锁所有权不匹配: 锁属进程 {锁行[1]}，请求 {进程身份键}"
            if 锁行[2] and 锁行[2] != 项目id:
                return 假, f"跨项目提交被拒绝: 锁属 {锁行[2]}，请求 {项目id}"
            if 锁行[3] and 锁行[3] != 所有者:
                return 假, f"跨所有者提交被拒绝: 锁属 {锁行[3]}，请求 {所有者}"
            资源行 = 连接.execute(
                "SELECT 版本, 栅栏令牌 FROM 资源版本 WHERE 资源id=?", (资源id,)).fetchone()
            if 资源行 is None:
                return 假, "资源不存在"
            if str(资源行[0]) != str(期望版本):
                return 假, f"版本冲突: 期望 {期望版本}，当前 {资源行[0]}"
            if str(资源行[1]) != str(期望令牌) or str(锁行[4]) != str(期望令牌):
                return 假, "旧令牌提交: 栅栏令牌已变化，提交被拒绝"
            try:
                版本号文本 = str(资源行[0])
                当前版本号 = int(版本号文本)
            except (TypeError, ValueError):
                # A3：版本是外部可写的账本字段（迁移库/手工写入/异常数据都可能是
                # 「v2」或 NULL），int() 不得让异常穿透错误边界——异常文本会直接
                # 漏给调用方。版本域失败统一用已登记中文码「版本冲突」
                # （网关 公开错误说明表 已登记，本地网关 公开错误码状态映射 → 409）。
                当前版本号 = None
            if 当前版本号 is None:
                return 假, (f"版本冲突: 资源 {资源id} 当前版本 {资源行[0]!r} "
                               f"不是十进制数字，无法递增新版本，提交被拒绝")
            新版本 = str(当前版本号 + 1)
            游标 = 连接.execute(
                "UPDATE 资源版本 SET 版本=?, 值=?, 摘要=?, 更新时间=? "
                "WHERE 资源id=? AND 版本=? AND 栅栏令牌=?",
                (新版本, json.dumps(新值, ensure_ascii=False), 新摘要,
                 time.strftime("%Y-%m-%d %H:%M:%S"), 资源id, 期望版本, 期望令牌))
            if 游标.rowcount != 1:
                return 假, "并发提交冲突"
            return 真, 新版本

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

        租约与抢占（P2-7，2026-09-18 硬化）：`租约秒 > 0` 时锁带租约（`租约截止`），
        租约过期即视为弃锁——其它持有者用「观察到的 `租约截止` 原值」做 CAS 抢占，
        同一事务内递增栅栏令牌并写一条回收证据（`类型='锁租约过期抢占'`）；被抢占者
        的提交/续期/释放都会被令牌判据拒绝。`租约秒 = 0`（缺省）时 `租约截止 = 0`
        即**无租约**：只有进程死亡清理能回收该锁，与硬化前逐字一致。
        """
        进程身份键 = 进程身份键 or self.身份.身份键()
        截止 = time.time() + 超时秒
        退避 = 0.005
        while True:
            连接 = self._连接()
            with 连接:
                现在 = time.time()
                行 = 连接.execute(
                    "SELECT 操作id, 事务id, 进程身份键, 项目id, 所有者, 栅栏令牌, "
                    "获取时间, 租约截止 FROM 锁 WHERE 资源id=?", (资源id,)).fetchone()
                if 行 is None:
                    令牌行 = 连接.execute(
                        "SELECT 栅栏令牌 FROM 资源版本 WHERE 资源id=?", (资源id,)).fetchone()
                    if 令牌行 is None:
                        return 假, "资源不存在: 无法授锁", 0
                    游标 = 连接.execute(
                        "INSERT OR IGNORE INTO 锁(资源id, 操作id, 事务id, 进程身份键, "
                        "项目id, 所有者, 栅栏令牌, 获取时间, 租约截止) "
                        "VALUES(?, ?, ?, ?, ?, ?, 0, ?, ?)",
                        (资源id, 操作id, 事务id, 进程身份键, 项目id, 所有者,
                         现在, 现在 + 租约秒 if 租约秒 > 0 else 0.0))
                    if 游标.rowcount > 0:
                        # 同一原子事务内递增令牌（签发后不回退）
                        return 真, "锁已获取", self._签发新令牌(连接, 资源id)
                elif 行[7] and 0 < 行[7] < 现在:
                    # 租约过期抢占：CAS 判据是观察到的 `租约截止` 原值，
                    # 并发抢占只有一个进程 rowcount=1（其余回到等待/超时路径）。
                    新租约截止 = 现在 + 租约秒 if 租约秒 > 0 else 0.0
                    游标 = 连接.execute(
                        "UPDATE 锁 SET 操作id=?, 事务id=?, 进程身份键=?, 项目id=?, 所有者=?, "
                        "获取时间=?, 租约截止=? WHERE 资源id=? AND 租约截止=?",
                        (操作id, 事务id, 进程身份键, 项目id, 所有者, 现在, 新租约截止,
                         资源id, 行[7]))
                    if 游标.rowcount == 1:
                        新令牌 = self._签发新令牌(连接, 资源id)
                        连接.execute(
                            "INSERT INTO 回收证据(证据id, 句柄id, 资源id, 类型, 失效原因, "
                            "时间, 版本) VALUES(?, ?, ?, ?, ?, ?, ?)",
                            (uuid.uuid4().hex[:16], "", 资源id, "锁租约过期抢占",
                             f"原持有者（事务{行[1] or '未记'} / 进程{行[2] or '未记'}）"
                             f"租约截止 {行[7]:.3f} 已过期，"
                             f"事务{事务id or '未记'} / 进程{进程身份键} 抢占并递增令牌",
                             time.strftime("%Y-%m-%d %H:%M:%S"), str(新令牌)))
                        return 真, "锁已获取（原持有者租约过期，已抢占）", 新令牌
            if time.time() > 截止:
                return 假, f"锁获取超时: 资源 {资源id} 被占用", 0
            time.sleep(退避)
            退避 = min(退避 * 2, 0.1)  # 指数退避，有界

    def _签发新令牌(self, 连接: sqlite3.Connection, 资源id: str) -> int:
        """锁授予的令牌签发（新授锁与租约抢占共用，禁止各写一套）：同事务内递增并回写。

        签发后永不回退：被抢占/已释放的旧令牌再也通不过 `提交资源`/`续期锁`/
        `释放锁` 的令牌判据。
        """
        连接.execute("UPDATE 资源版本 SET 栅栏令牌=栅栏令牌+1 WHERE 资源id=?", (资源id,))
        新令牌 = 连接.execute(
            "SELECT 栅栏令牌 FROM 资源版本 WHERE 资源id=?", (资源id,)).fetchone()[0]
        连接.execute("UPDATE 锁 SET 栅栏令牌=? WHERE 资源id=?", (新令牌, 资源id))
        return 新令牌

    def 续期锁(self, 资源id: str, *, 操作id: str = "", 事务id: str = "",
               进程身份键: str = "", 令牌: int = 0, 租约秒: float = 10.0) -> bool:
        """锁租约续期：校验操作/事务/进程身份/令牌后才允许续期。

        与 `释放锁` 同口径（`锁所有权判据` 是两者唯一的判据生成器）：
        `操作id` 原先收了却不判——它和 `事务id` 在全部既有调用点都是同一个值
        （锁由 `获取锁(资源id, 操作id=事务id, 事务id=事务id, …)` 签发），
        不判它等于「事务id+进程身份键+令牌 对得上就能续别人的锁」，即便签发
        该锁的操作早已换人。不传 `操作id`（空串）时不加入判据，与原先逐字一致。
        令牌列沿用原先的硬性判据（不传即按 0 比对，续期必须携带正确令牌）。
        """
        进程身份键 = 进程身份键 or self.身份.身份键()
        条件表, 参数表 = 锁所有权判据(
            资源id, 操作id=操作id, 事务id=事务id,
            进程身份键=进程身份键, 令牌=令牌, 必判=("栅栏令牌",))
        连接 = self._连接()
        with 连接:
            游标 = 连接.execute(
                f"UPDATE 锁 SET 租约截止=? WHERE {' AND '.join(条件表)}",
                [time.time() + 租约秒, *参数表])
            return 游标.rowcount > 0

    def 释放锁(self, 资源id: str, *, 操作id: str = "", 事务id: str = "",
               进程身份键: str = "", 令牌: int = 0) -> bool:
        """释放锁：错误进程/错误事务/错误令牌不能释放他人的锁。

        `操作id` 参与 WHERE 判据（与 `续期锁` 共用 `锁所有权判据`）：它与
        `事务id` 在**全部既有调用点都是同一个值** —— 锁是
        `获取锁(资源id, 操作id=事务id, 事务id=事务id, ...)` 用同一个操作
        标识签发的（见 `运行核心/资源协调/句柄服务.py` 更新受管状态 与 本文件
        `获取锁` 的列写入）。原先收了参数却不判，等于「只校验部分所有权」：
        谁拿到 事务id+进程身份键+令牌，即便 `操作id` 已经换了，也能把别人的锁删掉。
        不传 `操作id`（空串）时**不加入判据**，与原先行为逐字一致——既有调用点
        （`资源协调/服务.py`、发布门禁）不传该参数，语义不变。
        """
        进程身份键 = 进程身份键 or self.身份.身份键()
        条件表, 参数表 = 锁所有权判据(
            资源id, 操作id=操作id, 事务id=事务id, 进程身份键=进程身份键, 令牌=令牌)
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

    # ---- 心跳时基（§9-B6：进程.最后心跳 列为单调口径，历史行是墙钟） ----

    @property
    def _时基换算(self) -> float:
        """墙钟 epoch 秒 → 本进程单调秒 的**一次性常量**（进程生命周期内不变）。

        本进程（源码/制品任一形态）从没写过墙钟心跳，历史行的墙钟值必然
        **早于**本进程启动，故用「进程启动那一刻的双时钟偏差」换算，误差 = 启动耗时（毫秒级），
        对 15 秒量级的心跳超时判据无影响。取一次即缓存：热路径不再重复取时钟。
        """
        缓存 = getattr(self, "_时基换算缓存", None)
        if 缓存 is None:
            缓存 = time.time() - time.monotonic()
            self._时基换算缓存 = 缓存
        return 缓存

    def _心跳到单调(self, 心跳值: Any) -> float:
        """把某一行的 `最后心跳` 统一到**单调时基**（同一列两种时基的收敛点）。

        为什么必须收敛：本列自 §9-B6 起改为单调口径（经过时间量，睡眠期间不走），
        而历史行存的是 epoch 秒。两种时基混在同一列，两个方向都会错：
        - 拿单调 `截止` 比墙钟值（≈1.7e9 ≫ ≈6e5）→ 恒真 → **死进程永久显示存活**；
        - 拿墙钟 `截止` 比单调值 → 恒假 → **活进程被批量判死**（那正是本轮要修的误杀）。
        判据：值 > 1e8 即视为墙钟量（epoch，2026 年 ≈1.79e9；任何单调时钟都不可能到 1e8 秒
        ≈ 3.2 年开机时长），换算到单调；否则按已是单调值原样返回。
        """
        try:
            值 = float(心跳值 or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return 值 - self._时基换算 if 值 > 1e8 else 值

    def _单调截止(self, 心跳超时秒: float) -> float:
        """心跳新鲜判据的截止点（**单调时基**）：比它新才算活着。"""
        return time.monotonic() - float(心跳超时秒)

    # ---- 进程 ----
    def 存活的进程身份表(self, 心跳超时秒: float = 15.0) -> list[dict[str, Any]]:
        """存活进程（心跳新鲜）；pid 复用不误认（指纹参与身份键）。"""
        连接 = self._连接()
        结果表 = []
        # 比较口径：全部经 `_心跳到单调` 收敛后与本进程单调时钟比，绝不直接把列与
        # 时间戳混算（见 `_心跳到单调` 的两种错法）。候选集先按最宽的墙钟/单调
        # 两界取全，再由 Python 侧收敛复判 —— 保证不漏行、不误判。
        上界 = max(time.time(), time.monotonic()) + 1.0
        for 行 in 连接.execute("SELECT * FROM 进程 WHERE 最后心跳 > ?", (0.0,)):
            心跳 = self._心跳到单调(行[6])
            if 心跳 <= 0 or 心跳 > 上界:
                continue
            if 心跳 <= self._单调截止(心跳超时秒):
                continue
            结果表.append({
                "身份键": 行[0], "进程id": 行[1], "启动指纹": 行[2], "项目id": 行[3],
                "所有者": 行[4], "实例id": 行[5], "最后心跳": 心跳,
            })
        return 结果表

    def 清理死亡进程资源(self, *, 项目id: str = "", 所有者: str = "",
                          心跳超时秒: float = 15.0,
                          保留窗口秒: float | None = None) -> list[str]:
        """结构化精确回收：按进程身份键回收 锁/租约/未完成事务/句柄。

        系统进程已不存在时立即回收；进程仍存在但心跳过期时按失联回收。
        只处理项目/所有者匹配的资源；活跃进程锁不被误删；
        清理重复执行幂等。
        末尾按保留窗口真删 句柄/租约/进程 三类终态历史行
        （见 回收过期资源行），使账本「只增不删」变为「有界即正确」。
        自身进程身份键永不判死：清理器不得回收正在运行的调用方资源。

        本轮顺带收割「已结束线程的缓存连接」：网关是「每连接一线程」，
        每条连接线程用完就退出，而 `_清理死连接` 原先唯一调用点在 `关闭()`，
        进程长驻期间那些连接会一直挂在 `_连接表` 上（tid 复用只能兜住一部分）。
        收口点选在这里，是因为本方法就是 `资源账本维护循环` 每轮的判死回收动作
        ——零新增线程、零新增周期，拿现成的显式维护点。
        """
        from 运行核心.进程身份 import 系统进程存在

        # 收割已结束线程的缓存连接（显式维护点；`_连接()` 读取路径不收割）
        self._清理死连接()
        连接 = self._连接()
        截止 = self._单调截止(心跳超时秒)
        自身身份键 = self.身份.身份键()
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
        # 心跳判据全在**单调时基**上做（`_心跳到单调` 收敛历史墙钟行）：
        # 墙钟口径下合盖睡眠会让所有行集体显得「心跳过期」（审计 §9-B6 的误杀根因），
        # 单调口径下睡眠不动 → 只有真失联的行才过期；PID 探活仍是并列的兜底判据。
        死亡进程表 = [
            (身份键, 进程id)
            for 身份键, 进程id, 最后心跳 in 候选进程表
            if 身份键 != 自身身份键
            and (self._心跳到单调(最后心跳) <= 截止 or not 系统进程存在(int(进程id)))
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
                    # 传入外层连接：内层不得自带 `with 连接`，否则内层退出即提交
                    # 外层事务，本方法整体原子性失效（A1）。
                    self.回收租约(租约id, "所属进程死亡", 连接=连接)
                    清理列表.append(f"租约: {租约id}（死亡进程 {进程id}）")
                事务行 = 连接.execute(
                    "SELECT 事务id FROM 事务 WHERE 进程身份键=? AND 状态='进行中'", (身份键,)).fetchall()
                for (事务id,) in 事务行:
                    连接.execute("UPDATE 事务 SET 状态='失败', 结果='进程死亡回滚' WHERE 事务id=?", (事务id,))
                    清理列表.append(f"事务: {事务id}（死亡进程 {进程id}）")
                句柄行 = 连接.execute(
                    "SELECT 句柄id FROM 句柄 WHERE 进程身份键=? AND 状态='有效'", (身份键,)).fetchall()
                for (句柄id,) in 句柄行:
                    # 同上：复用外层连接，句柄失效随外层事务一起提交或回滚。
                    self.失效句柄(句柄id, "所属进程死亡", 连接=连接)
                    清理列表.append(f"句柄: {句柄id}（死亡进程 {进程id}）")
        # 真删放在标记事务之外：标记先落地，真删失败下一轮重试，不做半嵌套事务。
        清理列表.extend(self.回收过期资源行(保留窗口秒=保留窗口秒))
        return 清理列表

    def _保留窗口(self, 保留窗口秒: float | None) -> float:
        """解析本次调用的保留窗口：入参 > 类属性 `保留窗口秒`；NaN/无穷按「永不真删」处理。"""
        窗口 = self.保留窗口秒 if 保留窗口秒 is None else float(保留窗口秒)
        if 窗口 != 窗口 or 窗口 == float("inf"):  # NaN / 无穷：保持只增语义，不真删
            return float("inf")
        if 窗口 < 0:
            raise ValueError("保留窗口秒不得为负")
        return float(窗口)

    def 回收过期资源行(self, *, 保留窗口秒: float | None = None) -> list[str]:
        """按保留窗口真删 句柄/租约/进程 三类历史行（只删已终态且够老的行）。

        为什么需要：判死清理（清理死亡进程资源）对 租约/句柄 只改状态、对 进程 只读不写，
        锁表是唯一真删；不改终态为删除 ⇒ 三表只增不删（现场 18 天 9130/9166/3633 行）。
        行级判据（三类各自与 清理死亡进程资源 的判死判据配对）：
        - 句柄：`状态='已失效'` 且 `失效时间` < 保留截止（失效时间为本地时间文本，
          定宽零填充，可直接字典序比较）；历史行没有 失效时间 时用 创建时间 兜底，
          两者都缺则视为不可判定、继续保留；
        - 租约：`已回收=1` 且 `最后心跳` < 保留截止（epoch 秒，NULL 视为远古）；
        - 进程：`最后心跳` < 保留截止 且 身份键不再被 锁 表引用 且 不是自身身份键
          （残留引用保护：仍有锁的行说明清理链未走完，留给下一轮）。
        单事务提交，逐条返回删除说明；幂等（重复调用第二次返回空）。
        """
        窗口 = self._保留窗口(保留窗口秒)
        if 窗口 == float("inf"):
            return []
        现在 = time.time()
        截止时间 = 现在 - 窗口
        截止文本 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(截止时间))
        连接 = self._连接()
        删除列表: list[str] = []
        with 连接:
            # 句柄：失效时间缺失的历史行（旧版本只改状态不写时间）用 创建时间 兜底，
            # 两边都缺（'' 或 NULL）的行视为不可判定，继续保留（审计优先于清空）。
            游标 = 连接.execute(
                "DELETE FROM 句柄 WHERE 状态='已失效' "
                "AND COALESCE(NULLIF(失效时间, ''), NULLIF(创建时间, '')) IS NOT NULL "
                "AND COALESCE(NULLIF(失效时间, ''), NULLIF(创建时间, '')) < ?",
                (截止文本,))
            if 游标.rowcount:
                删除列表.append(f"句柄: 真删 {游标.rowcount} 行（失效早于 {截止文本}）")
            游标 = 连接.execute(
                "DELETE FROM 租约 WHERE 已回收=1 AND COALESCE(最后心跳, 0) < ?", (截止时间,))
            if 游标.rowcount:
                删除列表.append(f"租约: 真删 {游标.rowcount} 行（心跳早于 {截止时间:.0f}）")
            # 进程：`最后心跳` 自 §9-B6 起是**单调**口径（`进程身份.心跳` 写
            # `time.monotonic()`），历史行却是墙钟 epoch 秒。真删判据必须按行收敛到
            # 同一时基（`_心跳到单调`）：不收敛的话，`截止时间`（墙钟 epoch ≈1.79e9）
            # 对**任何**单调值（≈6e5）都恒真 → 每一轮清扫都把**全部活进程行真删**
            # （本轮实测复现：写入一条心跳为当前 monotonic 的行，一轮即被删）。
            # 与 存活的进程身份表/清理死亡进程资源 用同一个 `_心跳到单调` 收敛点。
            时基换算 = self._时基换算
            游标 = 连接.execute(
                "DELETE FROM 进程 WHERE 身份键 <> ? "
                "AND 身份键 NOT IN (SELECT 进程身份键 FROM 锁) "
                "AND (CASE WHEN COALESCE(最后心跳, 0) > 1e8 "
                "          THEN COALESCE(最后心跳, 0) - ? "
                "          ELSE COALESCE(最后心跳, 0) END) < ?",
                (self.身份.身份键(), 时基换算, self._单调截止(窗口)))
            if 游标.rowcount:
                删除列表.append(
                    f"进程: 真删 {游标.rowcount} 行（心跳早于单调 {self._单调截止(窗口):.0f}）")
        return 删除列表

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
            return 假

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

    def __del__(self) -> None:
        """对象异常离开生命周期时尽力关闭连接，避免解释器回收时报资源泄漏。"""
        try:
            连接表 = getattr(self, "_连接表", {})
            for 连接 in list(连接表.values()):
                try:
                    连接.close()
                except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
                    记录忽略('权威状态.__del__', 错误)
            连接表.clear()
            getattr(self, "_连接线程表", {}).clear()
        except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
            记录忽略('权威状态.__del__', 错误)

    def _校验目标库(self, 连接: sqlite3.Connection) -> None:
        """只读校验连接必须真的开在 `self.数据库路径` 上；否则抛 sqlite3.DatabaseError。

        为什么单列一条判据（P2-13③）：`PRAGMA integrity_check` 对**任何**容器的空库
        都返回 `ok`（含 SQLite 现场新建的空文件），拿它单独判完整性会**掩盖真实损坏**
        —— 只要连接开到别处（另一个库、截断出来的空库），它就恒过。

        两级判据，先精后宽（都是为了「既不放过错误库、也不冤枉正确库」，因为判红的
        后果是走备份覆盖 ⇒ 假红会拿旧备份盖掉好库）：
        1. `os.path.samefile` 比 **inode + 设备号**：同一文件的不同写法（软链接、
           `/var` 与 `/private/var`、`..` 段）全判等，这是「是不是同一个文件」的精确答案；
        2. 任一侧不存在时降级比**规范化路径双向包含**（`abspath`/`realpath` 各一份，
           任一命中即算等）。

        路径判据里禁止出现 `#`/`?` 这类**拼进 URI 就会被改写语义**的字符（哲学第 2 条 2 项）：
        这里的比对全在文件系统路径层做，URI 编码只发生在 `只读库URI()` 一处。
        """
        目标 = str(self.数据库路径)
        自报 = 连接真实库路径(连接)
        if 自报 and self._判定同一库(目标, 自报):
            return
        # 用 sqlite3.DatabaseError 而不是 RuntimeError：本方法专为「损坏恢复」的
        # 校验段服务，语义就是「这个连接不可信 ⇒ 当作数据库不可用」，
        # 复用既有的损坏→备份恢复分支，不新增未处理异常类型。
        raise sqlite3.DatabaseError(
            f"只读校验连接未开在目标库: 目标={os.path.realpath(目标)} "
            f"实际={os.path.realpath(自报) if 自报 else '（空）'}")

    @staticmethod
    def _判定同一库(目标: str, 自报: str) -> bool:
        """两个路径是否指向同一个库文件（同 inode 优先，路径双向包含兜底）。"""
        try:
            if os.path.samefile(目标, 自报):
                return True
        except OSError:
            pass  # 任一侧不存在（如截断出来又没建成的前缀）→ 降级比路径
        for 规约 in (os.path.abspath, os.path.realpath):
            甲, 乙 = 规约(目标), 规约(自报)
            if 甲 in 乙 or 乙 in 甲:
                return True
        return False

    def 校验结构(self) -> tuple[bool, str]:
        """结构校验：版本一致 + 必需列齐全 + integrity_check 返回 ok。"""
        try:
            连接 = self._连接()
            with 连接:
                self._校验版本结构(连接, self.目标版本)
                行 = 连接.execute("SELECT 值 FROM 元信息 WHERE 键='结构版本'").fetchone()
                if not 行 or 行[0] != self.目标版本:
                    return 假, f"结构版本不一致: {行[0] if 行 else '无'}"
            return 真, "结构完整"
        except Exception as 错误:
            return 假, str(错误)

    def 损坏恢复(self, 备份目录: Path | None = None) -> tuple[bool, str]:
        """数据库损坏恢复：integrity_check 返回 ok 才认为完整；损坏则从最新备份恢复。

        恢复后重新校验 结构版本/必需列/完整性，再允许继续运行。

        判据顺序（P2-13③，2026-09-18 收口）：① 只读连接必须真开在目标库上
        （`_校验目标库`，先拆「连到空库」这种掩盖）→ ② 才看 `integrity_check`。
        顺序不能反：空库的完整性检查恒返回 `ok`，先看它就等于给假绿开门
        （类 docstring 第 1 条）。
        """
        try:
            校验连接 = sqlite3.connect(只读库URI(self.数据库路径), uri=True)
            try:
                self._校验目标库(校验连接)
                结果 = 校验连接.execute("PRAGMA integrity_check").fetchone()
            finally:
                # 库损坏时 integrity_check 先抛 sqlite3.DatabaseError，原写法
                # 的 close() 在异常路径永不执行 ⇒ 「越需要恢复越漏连接」。
                # close 必须在 finally 里，只读校验连接不得泄漏。
                校验连接.close()
            if 结果 and 结果[0] == "ok":
                return 真, "数据库完整"
            raise sqlite3.DatabaseError(f"完整性检查: {结果}")
        except sqlite3.DatabaseError:
            pass
        备份目录 = Path(备份目录 or (self.存储目录 / "备份"))
        if not 备份目录.is_dir():
            return 假, "数据库损坏且无可用备份"
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
                    return 假, f"备份恢复后结构校验失败: {消息}"
                return 真, f"已从备份恢复: {备份文件.name}"
            except (OSError, sqlite3.OperationalError):
                continue
        return 假, "数据库损坏且所有备份恢复失败"
