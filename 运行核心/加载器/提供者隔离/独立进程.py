"""真实独立进程：subprocess 运行的工作进程管理。

支持：启动（含启动超时）、标准输入输出通信、请求id、调用超时、取消、
健康检查、崩溃检测、自动重启（次数限制）、资源状态记录、优雅停止、
强制终止、进程退出码记录、日志隔离。

核心只能通过统一中文协议调用提供者，不得泄漏原生进程对象。

**跨平台收口（华哥 2026-09-16 裁决：底座做完整跨平台）**：子进程组启动标志、进程组存活
判定、组信号发送全部走 `公共契约/运行时/平台适配.py` 与 `公共契约/运行时/进程终止.py`
—— **本文件调用点不含任何平台判断**（无 `os.name` / `sys.platform` / `os.killpg` /
`os.getpgrp`）。**「进程组归属」与「隔离回收」语义不变**：组长被 `poll()` 回收后，
「同组子孙仍在」只有收口层的按组号原语（`按组号探活` / `按组号终止`）能表达。

**管道读取同样不做平台判断**：stdout 由后台线程阻塞式 `os.read` 直读内核并用
`公共契约/运行时/有界IO.受限读取` 排空+限界，调用方在条件变量上等一个完整行
—— 不再用 `select` 轮询管道 fd（Windows 的 `select` 只接受 socket，轮询管道必然报错）。

**stdout 只有一个读者（唯一所有权）**：管道 fd 归本文件的后台读线程独有，
上层（如 `运行核心/运行环境管理器/提供者生命周期.py`）**永不直接碰管道 fd**：
要丢掉滞留响应行一律走 `弃置滞留行()` —— 它只在同一把交接锁下从后台线程维护的
`_读取缓冲` 里非阻塞取/弃完整行。旧实现让上层 `select + readline` 直读同一个
管道，两个读者分食同一字节流（竞态：要么上层偷走后台上游字节，要么
`select` 报可读但只有半行时 `readline` 无超时包裹地永久阻塞）。

**跨重启世代账本（常驻提供者进程）**：常驻工作进程用 `子进程组启动标志()`
（POSIX `setsid`）脱离网关会话/进程组，网关一退出就切断 OS 的「父死子随」兜底
—— 工作进程及模型子孙会被 launchd 收养、继续占显存与端口，而新网关内存里没有
上一代 PID/pgid，定位不到也回收不掉。故启动成功后把
`{网关世代id, 网关进程id, 提供者id, 组长进程id, 进程组号, 端口, 资源键, 启动时间}`
原子落进底座运行库（`常驻提供者进程` 表，本文件就地 `CREATE TABLE IF NOT EXISTS`，
WAL + `synchronous=FULL`），整组确认收敛后销行；新网关启动时调一次
`清扫上一代常驻进程()` 把上一代遗留整组回收。
判据是**归属 + 世代**（记录里的 `网关进程id` 已消失才算孤儿），**不按端口号盲杀**
—— embedding/rerank 这类合法长驻服务的父进程同样是 1，按端口杀会误杀。
"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import threading
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.版本规则.契约版本 import 取契约版本
from 公共契约.运行时 import 平台适配, 进程终止, 有界IO
from 公共契约.运行时.运行缓存 import 解析运行数据根
from 公共契约.基础类型.逻辑类型 import 真, 假

进程状态_已创建 = "已创建"
进程状态_启动中 = "启动中"
进程状态_运行中 = "运行中"
进程状态_已停止 = "已停止"
进程状态_故障 = "故障"

日志上限 = 200  # 日志列表环形裁剪上限（对齐 提供者生命周期._日志上限）
stderr日志上限 = 200
最大允许池大小 = 16
响应行上限字节 = 1024 * 1024  # 单行响应上限（防恶意/异常进程写无界行）
读取块大小 = 4096  # 直读内核的块大小（不做 TextIOWrapper 预读）


class _描述符读取器:
    """把裸文件描述符包成 ``有界IO.受限读取`` 需要的 ``read(大小)`` 接口。

    用 ``os.read`` 直读内核：每次只返回当前可用字节，不做 readline/预读的无界阻塞。
    **不使用 ``select``**：Windows 的 ``select`` 只接受 socket，轮询管道 fd 会直接
    报错（旧实现把该异常吞成「启动超时」，导致提供者隔离进程在 Windows 永远起不来）。
    """

    __slots__ = ("描述符",)

    def __init__(self, 描述符: int) -> None:
        self.描述符 = 描述符

    def read(self, 大小: int = 读取块大小) -> bytes:
        return os.read(self.描述符, int(大小))


#: 收口层 进程终止 的信号语义名（POSIX → SIGTERM/SIGKILL；Windows → taskkill 不带/带 /F）
信号_终止 = "终止"
信号_强杀 = "强杀"


def _已发出信号(收口结果) -> bool:
    """判定收口层 ``进程终止`` 的结果信封是否**真的发出了信号**。

    只读信封里的 ``已发出信号`` 字段（它由收口层按平台事实填写），调用点不猜平台：
    成功类结论（``已终止`` / ``已终止（回退）``）在 ``.值``，失败类结论在 ``.详细信息``。
    """
    载荷 = 收口结果.值 or 收口结果.详细信息 or {}
    return bool(载荷.get("已发出信号"))


# --------------------------------------------------------------------------- #
# 跨重启世代账本：常驻提供者进程落账 / 销账 / 启动清扫
# --------------------------------------------------------------------------- #

#: 底座运行库里本模块就地建的表（只读方按表名探测，缺表即视为无账本）
常驻进程账本表名 = "常驻提供者进程"
#: 底座运行库路径覆盖环境变量（与 运行核心/任务调度/任务系统.py 同一口径，避免第二套定位）
账本库环境变量 = "系统库运行库"
账本连接超时秒 = 10.0
#: 账本表列（读/写/判活共用一份，禁止两处各写一遍）
账本列 = ("网关世代id", "网关进程id", "提供者id", "组长进程id",
        "进程组号", "端口", "资源键", "启动时间", "启动时间戳")
#: 启动清扫整组回收的复查等待上限（强杀后等整组消失的总时长）
清扫等待秒 = 2.0
#: 排空滞留行的窗口与预算（上层「调用前排空」共用一份口径）
排空窗口秒 = 0.05
排空预算秒 = 2.0
排空预算字节 = 64 * 1024

_网关世代id: str | None = None


def 当前网关世代id() -> str:
    """本进程（网关世代）的唯一世代 id：进程号 + 纳秒时间 + 随机数，进程内只算一次。

    为什么按进程算而不是按调用算：世代 = 「一次网关进程生命周期」，同一次网关里
    所有常驻提供者必须记同一个世代 id，清扫时才能一眼分出「本世代 / 上一代」。
    """
    global _网关世代id
    if _网关世代id is None:
        _网关世代id = f"{os.getpid()}-{time.time_ns():x}-{uuid.uuid4().hex[:8]}"
    return _网关世代id


def _定位系统根() -> Path:
    """定位工程根（同时含 `支持库` 与 `模块库` 的最近祖先；找不到时退回本文件路径）。"""
    候选 = Path(__file__).resolve()
    for _祖先 in 候选.parents:
        if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
            return _祖先
    return 候选


def 账本库路径() -> Path:
    """世代账本所在的底座运行库路径：环境变量覆盖优先，否则经唯一解析器落运行数据根。"""
    显式 = str(os.environ.get(账本库环境变量, "") or "").strip()
    if 显式:
        return Path(显式).expanduser()
    return 解析运行数据根(_定位系统根()) / "底座运行.db"


def _账本连接(库路径: Path) -> sqlite3.Connection:
    """打开底座运行库连接（WAL；本模块只在建表与读写账本时用它）。

    ``synchronous=FULL``：WAL 模式下每次提交都对 WAL 做 fsync —— 这就是账本要求的
    「写后落盘」；账本行必须扛得住网关被 kill -9（正是它要解决的场景）。
    """
    连接 = sqlite3.connect(str(库路径), timeout=账本连接超时秒)
    连接.execute("PRAGMA journal_mode=WAL")
    连接.execute("PRAGMA synchronous=FULL")
    return 连接


def _建账本表(连接: sqlite3.Connection) -> None:
    """就地建表（幂等）。

    为什么不写进 `平台控制面/平台状态/状态存储.py` 的建表序列：该文件由并行任务在改，
    本模块只在**自己的库里**加一张自己的表，不动别人的迁移序列。
    主键取 (网关世代id, 提供者id)：不同世代的行可以并存，上一代的行在被确认回收前
    必须留着（否则孤儿失去观测对象）；同世代重复启动同一提供者则覆盖为新进程号。
    """
    连接.executescript(
        f"CREATE TABLE IF NOT EXISTS {常驻进程账本表名}("
        "网关世代id TEXT NOT NULL, 网关进程id INTEGER NOT NULL, 提供者id TEXT NOT NULL,"
        "组长进程id INTEGER NOT NULL, 进程组号 INTEGER, 端口 INTEGER,"
        "资源键 TEXT NOT NULL DEFAULT '', 启动时间 TEXT NOT NULL, 启动时间戳 REAL NOT NULL,"
        "PRIMARY KEY(网关世代id, 提供者id));"
    )


def 读取常驻进程账本() -> list[dict[str, Any]]:
    """读全部账本行（最新在后）；库不存在或无本表时返回空表（读路径不建库、不建表）。"""
    库路径 = 账本库路径()
    if not 库路径.is_file():
        return []
    连接 = _账本连接(库路径)
    try:
        表存在 = 连接.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (常驻进程账本表名,)).fetchone()
        if not 表存在:
            return []
        行表 = 连接.execute(
            f"SELECT {', '.join(账本列)} FROM {常驻进程账本表名} ORDER BY 启动时间戳").fetchall()
    finally:
        连接.close()
    return [dict(zip(账本列, 行)) for 行 in 行表]


def _登记常驻进程(记录: dict[str, Any]) -> None:
    """原子写一行账本（BEGIN IMMEDIATE + 提交即 fsync）；异常向上抛，由调用方留痕。"""
    库路径 = 账本库路径()
    库路径.parent.mkdir(parents=True, exist_ok=True)
    连接 = _账本连接(库路径)
    try:
        _建账本表(连接)
        连接.execute("BEGIN IMMEDIATE")
        连接.execute(
            f"INSERT OR REPLACE INTO {常驻进程账本表名}({', '.join(账本列)}) "
            f"VALUES ({', '.join('?' * len(账本列))})",
            tuple(记录.get(列) for 列 in 账本列))
        连接.commit()
    except sqlite3.Error:
        连接.rollback()
        raise
    finally:
        连接.close()


def _注销常驻进程(网关世代id: str, 提供者id: str) -> None:
    """删掉一行账本（确认整组收敛后才调用）；库/表不存在即视为无账可销。"""
    库路径 = 账本库路径()
    if not 库路径.is_file():
        return
    连接 = _账本连接(库路径)
    try:
        if not 连接.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (常驻进程账本表名,)).fetchone():
            return
        连接.execute("BEGIN IMMEDIATE")
        连接.execute(
            f"DELETE FROM {常驻进程账本表名} WHERE 网关世代id=? AND 提供者id=?",
            (网关世代id, 提供者id))
        连接.commit()
    except sqlite3.Error:
        连接.rollback()
        raise
    finally:
        连接.close()


def _账本记录存活(组长进程id: int, 进程组号: int | None) -> bool:
    """账本记录对应的整组是否仍存活（组长或同组子孙任一活着即为真）。

    先按组长进程号探活（跨平台）；组长已被回收时再按**组号**探活 —— `setsid` 保证
    组号 == 组长进程号，这是「组长退出、同组子孙仍在」唯一能表达的判据。
    """
    if 组长进程id <= 0:
        return 假
    if 进程终止.进程存活(组长进程id):
        return 真
    if 进程组号 is not None and 进程组号 == 组长进程id:
        return 进程终止.按组号探活(进程组号)
    return 假


def _回收账本行(行: dict[str, Any], *, 等待秒: float) -> tuple[bool, str]:
    """回收一条「非本世代」账本记录对应的整组；确认收敛才销行。返回（是否已回收, 说明）。"""
    提供者id = str(行.get("提供者id") or "")
    世代 = str(行.get("网关世代id") or "")
    组长进程id = 行.get("组长进程id")
    组长进程id = int(组长进程id) if isinstance(组长进程id, int) and not isinstance(组长进程id, bool) else 0
    组号 = 行.get("进程组号")
    组号 = int(组号) if isinstance(组号, int) and not isinstance(组号, bool) else None
    if 组长进程id <= 0:
        _注销常驻进程(世代, 提供者id)
        return 真, "记录无合法组长进程号，脏行已销"
    if not _账本记录存活(组长进程id, 组号):
        _注销常驻进程(世代, 提供者id)
        return 真, f"整组已不存在（组长 {组长进程id}），销行"
    # 仍活：整组回收走收口层既有能力（终止 → 宽限 → 强杀 → 复查；失败由收口层留痕）
    进程终止.强制结束子进程(组长进程id)
    if 组号 is not None and 组号 == 组长进程id and 进程终止.按组号探活(组号):
        # 组长已被回收但同组子孙仍在（组号 == 组长进程号）→ 按组号补一次强杀
        进程终止.按组号终止(组号, 信号="强杀")
    截止 = time.monotonic() + max(0.0, 等待秒)
    while _账本记录存活(组长进程id, 组号) and time.monotonic() < 截止:
        time.sleep(0.05)
    if _账本记录存活(组长进程id, 组号):
        return 假, f"整组仍未收敛（组长 {组长进程id}），保留账本行待下一世代再收"
    _注销常驻进程(世代, 提供者id)
    return 真, f"整组已回收（组长 {组长进程id}），销行"


def 清扫上一代常驻进程(*, 等待秒: float = 清扫等待秒) -> dict[str, Any]:
    """启动时扫一遍世代账本：回收「非本世代且归属网关已消失」的常驻进程整组。

    判据是**归属 + 世代**，不是端口号：
    - 记录世代 == 本世代 → 是本次网关自己的账，交给生命周期管理（不动）；
    - 记录归属网关进程仍活着（且不是本进程）→ 是**另一个仍在运行的网关**的合法财产，跳过
      —— 这也是并发测试/多网关并存时不被误杀的关键；
    - 记录归属网关进程已消失（kill -9 / 异常退出，内存里的 PID 表随之蒸发）→ 孤儿，整组回收。

    只回收「确认整组消失」的行；没收敛的行**保留**，留给下一世代再收（不静默销账）。
    `等待秒` 是强杀后等整组消失的上限。
    返回信封：`{成功, 本世代, 账本行数, 已回收, 未回收, 跳过, 错误说明}`。
    """
    本世代 = 当前网关世代id()
    结果: dict[str, Any] = {
        "成功": 真, "本世代": 本世代, "账本行数": 0,
        "已回收": [], "未回收": [], "跳过": [], "错误说明": "",
    }
    try:
        行表 = 读取常驻进程账本()
    except Exception as 错误:  # noqa: BLE001 —— 账本不可用必须可见（进错误说明），不静默
        结果["成功"] = 假
        结果["错误说明"] = f"世代账本不可读: {type(错误).__name__}: {错误}"
        return 结果
    结果["账本行数"] = len(行表)
    for 行 in 行表:
        提供者id = str(行.get("提供者id") or "")
        if str(行.get("网关世代id") or "") == 本世代:
            continue
        归属进程id = 行.get("网关进程id")
        归属进程id = int(归属进程id) if isinstance(归属进程id, int) and not isinstance(归属进程id, bool) else 0
        if 归属进程id != os.getpid() and 进程终止.进程存活(归属进程id):
            结果["跳过"].append({
                "提供者id": 提供者id, "网关世代id": 行.get("网关世代id"),
                "组长进程id": 行.get("组长进程id"),
                "原因": f"归属网关进程 {归属进程id} 仍在运行（不是孤儿）",
            })
            continue
        try:
            已回收, 说明 = _回收账本行(行, 等待秒=等待秒)
        except Exception as 错误:  # noqa: BLE001 —— 回收失败必须可见，不静默
            已回收, 说明 = 假, f"回收异常 {type(错误).__name__}: {错误}"
        项 = {"提供者id": 提供者id, "网关世代id": 行.get("网关世代id"),
             "组长进程id": 行.get("组长进程id"), "说明": 说明}
        if 已回收:
            结果["已回收"].append(项)
        else:
            结果["未回收"].append(项)
            结果["成功"] = 假
    if 结果["未回收"]:
        结果["错误说明"] = f"{len(结果['未回收'])} 条上一代常驻进程未收敛（账本行保留）"
    return 结果


@dataclass
class 进程调用结果:
    """一次进程调用的统一结果（不泄漏原生对象）。"""

    成功: bool
    值: Any = None
    错误码: str = ""
    错误说明: str = ""
    来源: str = "独立进程"
    可重试: bool = 假
    详细信息: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        return {
            "成功": self.成功, "值": self.值, "错误码": self.错误码,
            "错误说明": self.错误说明, "来源": self.来源,
            "可重试": self.可重试, "详细信息": self.详细信息,
        }


class 独立进程:
    """真实独立工作进程（subprocess + JSON 行协议）。"""

    def __init__(self, 名称: str, *, 工作器路径: Path | None = None,
                 启动超时秒: float = 5.0, 调用超时秒: float = 3.0,
                 最大重启次数: int = 3, 解释器路径: str | None = None,
                 提供者目录: Path | None = None,
                 端口: int | None = None, 资源键: str = "") -> None:
        self.名称 = 名称
        self.工作器路径 = 工作器路径 or Path(__file__).resolve().parent / "进程工作器.py"
        self.启动超时秒 = 启动超时秒
        self.调用超时秒 = 调用超时秒
        self.最大重启次数 = 最大重启次数
        self.解释器路径 = 解释器路径
        self.提供者目录 = 提供者目录
        # 世代账本的诊断字段：端口/资源键只如实记录调用方声明的事实，
        # **不参与判活与回收**（按端口盲杀会误伤 embedding/rerank 等合法长驻服务）。
        self.端口 = 端口
        self.资源键 = 资源键 or 名称
        self.账本错误 = ""  # 落账/销账失败留痕（可见，不静默）
        self.状态 = 进程状态_已创建
        self.进程: subprocess.Popen | None = None
        self.重启次数 = 0
        self.退出码: int | None = None
        self.日志列表: list[str] = []
        self.stderr日志 = deque(maxlen=stderr日志上限)
        self._stderr线程: threading.Thread | None = None
        self.关闭账本: list[dict[str, Any]] = []
        self._读取缓冲 = b""  # 后台读线程交接的行缓冲（os.read 直读内核，无预读）
        # 后台 stdout 读线程 ↔ 调用方的交接（条件变量：不用 sleep 轮询，也不用 select）
        self._读取条件 = threading.Condition()
        self._读取结束 = 假  # 后台读线程已 EOF/出错
        self._读取超限 = 假  # 单行超过 响应行上限字节
        self._读取序号 = 0  # 交接序号：每收到一块 +1（供「窗口内无新数据」判定，不靠 sleep 轮询）
        self._stdout线程: threading.Thread | None = None
        # JSON 行协议是一问一答；同一 Provider 进程不能让多个线程交叉
        # 写 stdin/读 stdout，否则迟到响应会被下一请求消费。
        self._通信锁 = threading.RLock()

    def _消费stderr(self, 进程: subprocess.Popen) -> None:
        """持续消费 stderr；只保留最近固定数量的块，防管道回压和日志无界。"""
        if 进程.stderr is None:
            return
        try:
            描述符 = 进程.stderr.fileno()
            while True:
                块 = os.read(描述符, 4096)
                if not 块:
                    break
                self.stderr日志.append(块.decode("utf-8", "replace"))
        except (OSError, ValueError):
            pass

    def _启动stderr消费(self, 进程: subprocess.Popen) -> None:
        self._stderr线程 = threading.Thread(
            target=self._消费stderr, args=(进程,),
            name=f"Provider-stderr-{self.名称}-{进程.pid}", daemon=True)
        self._stderr线程.start()

    def _启动stdout消费(self, 进程: subprocess.Popen) -> None:
        """启动 stdout 后台读线程（阻塞式 os.read + 有界IO.受限读取）。

        跨平台收口：**不依赖 select**（Windows 的 select 只支持 socket，轮询管道 fd
        必然报错，旧实现把该异常吞成「启动超时」）。新进程启动前重置交接状态，避免
        迟到半行/超限标记串到新进程。
        """
        with self._读取条件:
            self._读取缓冲 = b""
            self._读取结束 = 假
            self._读取超限 = 假
            self._读取序号 = 0
        self._stdout线程 = threading.Thread(
            target=self._消费stdout, args=(进程,),
            name=f"Provider-stdout-{self.名称}-{进程.pid}", daemon=True)
        self._stdout线程.start()

    def _收块(self, 块: bytes) -> None:
        """后台读线程的数据回调：上限内累积，超限后不再累积但继续排空（防管道回压）。"""
        with self._读取条件:
            if not self._读取超限:
                self._读取缓冲 += 块
                if len(self._读取缓冲) > 响应行上限字节:
                    self._读取超限 = 真
                    self._读取缓冲 = self._读取缓冲[:响应行上限字节]
            self._读取序号 += 1
            self._读取条件.notify_all()

    def _消费stdout(self, 进程: subprocess.Popen) -> None:
        """持续落盘到 EOF：有界IO.受限读取 负责排空与上限，异常收敛为「读取结束」。

        对端正常退出/管道被关闭都会走这里（OSError/ValueError），由等待侧按协议
        判据给出「超时/进程已退出」的结构化结论，故与 stderr 消费同样静默收敛。
        """
        try:
            if 进程.stdout is not None:
                有界IO.受限读取(
                    _描述符读取器(进程.stdout.fileno()), 响应行上限字节,
                    块大小=读取块大小, 数据回调=self._收块)
        except (OSError, ValueError):
            pass
        finally:
            with self._读取条件:
                self._读取结束 = 真
                self._读取条件.notify_all()

    def _确定解释器(self) -> str:
        """确定子进程解释器；声明提供者环境时失败必须阻断，禁止回退。"""
        if self.解释器路径:
            return self.解释器路径
        if self.提供者目录 is not None:
            try:
                from 运行核心.运行环境管理器 import 确保环境
                结果 = 确保环境(self.提供者目录)
                if 结果.成功 and 结果.解释器路径:
                    return 结果.解释器路径
            except Exception as 错误:
                raise RuntimeError(f"提供者隔离环境校验失败: {错误}") from 错误
            raise RuntimeError("提供者隔离环境不可用：未返回受管解释器")
        return sys.executable

    def _记录日志(self, 消息: str) -> None:
        self.日志列表.append(f"[{time.strftime('%H:%M:%S')}] {消息}")
        if len(self.日志列表) > 日志上限:
            del self.日志列表[:len(self.日志列表) - 日志上限]

    def _读取一行(self, 超时秒: float) -> str:
        """带超时的行读取：**后台读线程 + 有界IO.受限读取**，不轮询管道 fd。

        后台线程用 os.read 直读内核（不经过 readline/TextIOWrapper 预读），
        有界IO.受限读取 负责排空与上限；调用方在条件变量上等一个完整行：
        超过 超时秒 未读到完整行抛 TimeoutError；管道 EOF 抛 ConnectionError；
        单行超过 响应行上限字节 抛 ConnectionError。

        旧实现是 select.select([管道fd]) 轮询 —— Windows 的 select 只支持 socket，
        对管道 fd 直接报错，而 启动() 把该异常吞成「启动超时」，导致提供者隔离
        进程在 Windows 永远起不来。改后台线程后调用点不含任何平台判断。
        """
        截止 = time.monotonic() + max(0.01, 超时秒)
        with self._读取条件:
            while True:
                if b"\n" in self._读取缓冲:
                    行, 剩余 = self._读取缓冲.split(b"\n", 1)
                    self._读取缓冲 = 剩余
                    return 行.decode("utf-8", "replace")
                if self._读取超限:
                    raise ConnectionError(f"响应行超过上限（{响应行上限字节} 字节）")
                if self._读取结束:
                    raise ConnectionError("进程已退出（无响应）")
                剩余时间 = 截止 - time.monotonic()
                if 剩余时间 <= 0:
                    raise TimeoutError(f"读取响应超时（> {超时秒} 秒）")
                self._读取条件.wait(剩余时间)

    def 弃置滞留行(self, *, 窗口秒: float = 排空窗口秒,
                   预算秒: float = 排空预算秒, 预算字节: int = 排空预算字节) -> bool:
        """从后台读线程维护的 `_读取缓冲` 里**非阻塞取/弃完整行**；上层唯一排空入口。

        为什么必须是这一条路（旧实现的病根）：上层原先自己 `select([管道]) +
        readline()` 直读同一个 stdout 管道，与后台读线程**分食同一字节流** ——
        两个读者抢同一批字节，要么上层偷走后台上游字节（后续响应错位、请求id 不匹配），
        要么 `select` 报可读而管道里只有半行时 `readline` 无超时包裹地永久阻塞
        （实测阻塞 > 1 秒，远超 0.05 秒窗口）。管道 fd 现在只有一个读者：
        本类的后台读线程；上层要丢滞留响应只能来这里取**已经交接过来的**完整行。

        语义与旧「调用前排空」逐项对齐：
        - 返回 ``True``：窗口内已收敛（缓冲里的完整行已丢完且窗口内无新数据，
          或后台读线程已 EOF）；
        - 返回 ``False``：超预算 —— 累计丢弃字节 ≥ `预算字节`，或累计时间 ≥ `预算秒`，
          或单行超过 `响应行上限字节`（读缓冲已被判超限，协议流不可信）。
          调用方按「进程不可复用」处理（终止并重启）。
        半行（无换行）**不丢**：它不是完整响应行，擅自按行边界切会伪造协议。

        为什么还要拿 `_通信锁`：排空必须与「在途请求/响应」互斥 —— 否则并发调用时
        会把别人正在等的响应行当滞留行丢掉（JSON 行协议是一问一答，同一进程不能让
        排空插进问答之间）。锁序与 `_发送请求` 一致（通信锁 → 读取条件），不会反向。
        """
        开始 = time.monotonic()
        累计字节 = 0
        with self._通信锁, self._读取条件:
            while True:
                位置 = self._读取缓冲.rfind(b"\n")
                if 位置 >= 0:
                    累计字节 += 位置 + 1
                    self._读取缓冲 = self._读取缓冲[位置 + 1:]
                    if 累计字节 >= 预算字节:
                        return 假
                    continue
                if self._读取超限:
                    return 假
                if self._读取结束:
                    return 真
                剩余时间 = 预算秒 - (time.monotonic() - 开始)
                if 剩余时间 <= 0:
                    return 假
                序号 = self._读取序号
                self._读取条件.wait(min(max(窗口秒, 0.0), 剩余时间))
                if self._读取序号 == 序号 and b"\n" not in self._读取缓冲:
                    # 窗口内无新数据即视为已收敛（与旧实现「一次 select 窗口无可读即停」同语义）
                    return 真

    def _关闭管道(self) -> None:
        """关闭已结束进程的标准管道并回收后台消费线程，避免 fd/线程泄漏。"""
        if self.进程 is None:
            return
        for 管道 in (self.进程.stdin, self.进程.stdout, self.进程.stderr):
            if 管道 is not None and not 管道.closed:
                try:
                    管道.close()
                except OSError:
                    pass
        for 线程 in (self._stderr线程, self._stdout线程):
            if 线程 is not None and 线程 is not threading.current_thread():
                线程.join(timeout=1.0)

    def 启动(self) -> tuple[bool, str]:
        """启动子进程并等待 READY（启动超时失败）；成功后把常驻身份落进世代账本。"""
        if self.状态 == 进程状态_运行中:
            return 真, "已在运行"
        self.状态 = 进程状态_启动中
        self.账本错误 = ""
        try:
            # -S 跳过 site 初始化加速子进程启动（工作器自行注入系统根路径）
            系统根 = _定位系统根()
            self.进程 = subprocess.Popen(
                [self._确定解释器(), "-S", str(self.工作器路径), str(系统根)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1,
                env={**os.environ, "PYTHONNOUSERSITE": "1"},
                **平台适配.子进程组启动标志(),
            )
            self._启动stderr消费(self.进程)
            # stdout 后台读线程必须先起：READY/响应行由它落到交接缓冲，
            # 启动循环只做「等一行 + 判 READY」，不再轮询管道 fd。
            self._启动stdout消费(self.进程)
        except OSError as 错误:
            self.状态 = 进程状态_故障
            return 假, f"启动失败: {错误}"
        except RuntimeError as 错误:
            # 解释器解析/环境构建异常（如提供者隔离环境不可用）：状态置故障，
            # 清空句柄并统一返回失败结果，避免卡在“启动中”且进程表未登记。
            self.状态 = 进程状态_故障
            try:
                self._关闭管道()
            except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条）
                记录忽略('独立进程.启动', 错误)
            return 假, f"启动失败: {错误}"
        开始 = time.monotonic()
        while time.monotonic() - 开始 < self.启动超时秒:
            if self.进程.poll() is not None:
                self.状态 = 进程状态_故障
                self.退出码 = self.进程.returncode
                self._关闭管道()
                return 假, f"启动超时/提前退出（退出码 {self.退出码}）"
            try:
                # 分段限时读取：每次最多等 0.5 秒，超时走外层整体超时判定并强杀
                行 = self._读取一行(min(0.5, self.启动超时秒 - (time.monotonic() - 开始)))
            except (TimeoutError, ConnectionError, ValueError, OSError):
                行 = ""
            if "READY" in 行:
                self.状态 = 进程状态_运行中
                self._记录日志(f"启动成功（pid {self.进程.pid}）")
                self._登记世代账本()
                return 真, "启动成功"
        self.强制终止()
        self.状态 = 进程状态_故障
        return 假, f"启动超时（> {self.启动超时秒} 秒）"

    def _发送请求(self, 请求: dict) -> dict:
        with self._通信锁:
            if self.进程 is None or self.进程.poll() is not None:
                raise ConnectionError("进程未运行")
            self.进程.stdin.write(json.dumps(请求, ensure_ascii=False) + "\n")
            self.进程.stdin.flush()
            行 = self._读取一行(self.调用超时秒)
            响应 = json.loads(行)
            if 响应.get("请求id") != 请求.get("请求id"):
                raise ConnectionError(
                    f"响应请求id不匹配: 期望 {请求.get('请求id')}，实际 {响应.get('请求id')}")
            return 响应

    def 调用(self, *, 能力id: str, 参数: dict | None = None,
             契约版本: str | None = None) -> 进程调用结果:
        """按统一中文协议调用能力（请求id/能力id/契约版本/参数/超时）。

        契约版本 缺省取唯一事实源（公共契约/版本规则/契约版本.py），不写死字面量。
        """
        契约版本 = 契约版本 or 取契约版本()
        if self.状态 != 进程状态_运行中:
            return 进程调用结果(假, 错误码="外部不可访问", 错误说明=f"进程未运行（状态 {self.状态}）")
        请求 = {
            "请求id": uuid.uuid4().hex[:12], "类型": "调用",
            "能力id": 能力id, "契约版本": 契约版本, "参数": 参数 or {},
            "超时秒": self.调用超时秒, "取消": 假,
        }
        try:
            响应 = self._发送请求(请求)
        except TimeoutError as 错误:
            self._记录日志(f"调用超时: {能力id}")
            return 进程调用结果(假, 错误码="超时", 错误说明=str(错误), 可重试=真)
        except (ConnectionError, json.JSONDecodeError) as 错误:
            self.崩溃检测()
            return 进程调用结果(假, 错误码="外部不可访问", 错误说明=str(错误), 可重试=真)
        return 进程调用结果(
            成功=响应.get("成功", 假), 值=响应.get("值"),
            错误码=响应.get("错误码", ""), 错误说明=响应.get("错误说明", ""),
            来源=响应.get("来源", "独立进程"), 可重试=响应.get("可重试", 假),
            详细信息=响应.get("详细信息", {}),
        )

    def 健康检查(self) -> bool:
        """健康检查：进程存活 + 健康请求响应。"""
        if self.进程 is None or self.进程.poll() is not None:
            return 假
        try:
            响应 = self._发送请求({"请求id": "健康", "类型": "健康"})
            return bool(响应.get("成功"))
        except (TimeoutError, ConnectionError, json.JSONDecodeError):
            return 假

    def 崩溃检测(self) -> bool:
        """崩溃检测：进程退出即崩溃；触发自动重启（限制次数）。"""
        if self.进程 is None:
            return 假
        退出码 = self.进程.poll()
        if 退出码 is None:
            return 假
        self.退出码 = 退出码
        self.状态 = 进程状态_故障
        self._记录日志(f"进程崩溃（退出码 {退出码}）")
        if self.重启次数 < self.最大重启次数:
            self.重启次数 += 1
            self._记录日志(f"自动重启（第 {self.重启次数} 次）")
            # 重启前必须显式关闭旧管道并重置读缓冲，避免旧 Popen 管道
            # 依赖垃圾回收、新进程继承旧半行/迟到响应造成协议串读。
            # （读缓冲/结束/超限标记由 _启动stdout消费 在起线程前统一重置）
            self._关闭管道()
            self._读取缓冲 = b""
            成功, 消息 = self.启动()
            if 成功:
                return 假  # 已重启恢复
            self._记录日志(f"自动重启失败: {消息}")
        return 真  # 崩溃且未恢复

    def _进程组存活(self) -> bool:
        """成员进程组是否仍存活（组长已回收但同组子孙仍在也算存活）。

        **为什么必须用「按组号」的收口原语**：收口层 `进程存活` / `终止进程组` 都以
        `os.getpgid(pid)` 为判定前提，而 `Popen.wait()/poll()` 一旦观察到组长退出就把
        它**回收**，回收后 `os.getpgid(组长pid)` 必然失败（收口只能如实判「进程不存在」）
        —— 于是「组长正常退出、同组子孙仍在」这条语义就判不出来了，而这正是本类必须
        覆盖的语义（测试中心/第一批维修/测试_Provider进程.py::test_P0_14_组长正常退出
        也必须回收同组子进程）。

        故先看句柄（句柄未回收即未退出 → 组必然活着），句柄已回收才用收口层为此场景
        专门补齐的 `按组号探活(组长pid)`（组号 == 组长 pid，由 `子进程组启动标志()` 保证）。
        平台差异（有无 `os.killpg`、Windows 无组概念）全部收口在
        `公共契约/运行时/进程终止.py`，**本调用点不做任何平台判断**。
        """
        进程 = self.进程
        if 进程 is None:
            return 假
        if 进程.poll() is None:
            return 真
        return 进程终止.按组号探活(进程.pid)

    def _等待进程组退出(self, 超时秒: float) -> bool:
        截止 = time.monotonic() + max(0.0, 超时秒)
        while self._进程组存活() and time.monotonic() < 截止:
            time.sleep(0.01)
        进程 = self.进程
        if 进程 is not None and 进程.poll() is None and not self._进程组存活():
            try:
                进程.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        return not self._进程组存活()

    def _发进程组信号(self, 信号名: str) -> None:
        """向成员进程组发信号：两发都走跨平台收口，**调用点不做任何平台判断**。

        第一发 `终止进程组(组长pid)`：组长仍活着（含僵尸）时收口按组长身份一次整组终止，
        非组长则退化为单进程（不误伤同组其他进程）—— 这正是原实现里自己拼
        `os.name == "posix"` + `killpg` + `pid != os.getpgrp()` 分支要表达的语义。

        组长已被 `Popen` 回收时收口取不到组号（只能如实回「进程不存在」），而组内子孙可能
        仍在，故第二发改用收口层专为此场景补齐的 `按组号终止(组长pid)` 补发一次 ——
        保住「组长已回收 ≠ 组已收敛」（测试中心/第一批维修/测试_Provider进程.py::test_P0_14）。

        `本进程组号` 由收口 `进程组号()` 取（非 POSIX 平台如实回 `None`），仅用于避免误伤
        本进程自己所在的组 —— 这不是平台判断，而是「不要打自己」的安全闸；收口两层都
        没真的发出信号时才退化为单进程句柄信号（与原实现 killpg 抛错后回退同语义）。
        """
        进程 = self.进程
        if 进程 is None:
            return
        if _已发出信号(进程终止.终止进程组(进程.pid, 信号=信号名)):
            return
        本进程组号 = 进程终止.进程组号(os.getpid())
        if 本进程组号 is None or 进程.pid != 本进程组号:
            if _已发出信号(进程终止.按组号终止(进程.pid, 信号=信号名)):
                return
        if 进程.poll() is None:
            try:
                进程.terminate() if 信号名 == 信号_终止 else 进程.kill()
            except (OSError, ProcessLookupError):
                pass

    def _核对资源收敛(self) -> list[str]:
        """进程组、三管道、stderr 消费线程全部收敛才算关闭成功。"""
        未收敛: list[str] = []
        进程 = self.进程
        if 进程 is not None and self._进程组存活():
            未收敛.append(f"进程组仍存活:{进程.pid}")
        if 进程 is not None:
            for 名称, 管道 in (("stdin", 进程.stdin), ("stdout", 进程.stdout), ("stderr", 进程.stderr)):
                if 管道 is not None and not 管道.closed:
                    未收敛.append(f"管道未关闭:{名称}")
        if self._stderr线程 is not None and self._stderr线程.is_alive():
            未收敛.append(f"stderr线程仍存活:{self._stderr线程.name}")
        if self._stdout线程 is not None and self._stdout线程.is_alive():
            未收敛.append(f"stdout线程仍存活:{self._stdout线程.name}")
        return 未收敛

    def _登记世代账本(self) -> None:
        """把本常驻进程的身份原子落进世代账本（失败可见，不静默）。

        为什么落账失败不阻断启动：账本是**跨重启兜底**，不是启动前置条件 —— 账本库
        不可写（只读盘/权限）时若拒绝启动，等于把「诊断账本不可用」升级成「提供者
        全线不可用」。故失败只如实记进 `账本错误` 与环形日志（调用方/诊断可读），
        代价是这一代进程失去跨重启回收能力，属已知剩余风险。
        """
        进程 = self.进程
        if 进程 is None:
            return
        try:
            _登记常驻进程({
                "网关世代id": 当前网关世代id(),
                "网关进程id": os.getpid(),
                "提供者id": self.名称,
                "组长进程id": 进程.pid,
                "进程组号": 进程终止.进程组号(进程.pid),
                "端口": self.端口,
                "资源键": self.资源键,
                "启动时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "启动时间戳": time.time(),
            })
            self.账本错误 = ""
        except Exception as 错误:  # noqa: BLE001 —— 账本不可用必须可见（哲学第 3 条）
            self.账本错误 = f"常驻进程世代账本落账失败: {type(错误).__name__}: {错误}"
            self._记录日志(self.账本错误)

    def _注销世代账本(self) -> None:
        """确认整组收敛后销账（销不掉不影响关闭结论：留行只会让下一世代再收一次）。"""
        try:
            _注销常驻进程(当前网关世代id(), self.名称)
            self.账本错误 = ""
        except Exception as 错误:  # noqa: BLE001 —— 销账失败必须可见
            self.账本错误 = f"常驻进程世代账本销账失败: {type(错误).__name__}: {错误}"
            self._记录日志(self.账本错误)

    def _关闭结果(self, *, 已使用SIGKILL: bool = 假) -> dict[str, Any]:
        self._关闭管道()
        if self._stderr线程 is not None:
            self._stderr线程.join(timeout=1.0)
        未收敛 = self._核对资源收敛()
        成功 = not 未收敛
        self.状态 = 进程状态_已停止 if 成功 else 进程状态_故障
        if 成功:
            # 只有整组 + 三管道 + 消费线程全部收敛才销账：留着「其实已死」的行无害，
            # 但把「还活着」的行销掉就等于让孤儿失去观测对象（假阴性）。
            self._注销世代账本()
        结果 = {
            "成功": 成功, "错误码": "" if 成功 else "资源未收敛",
            "错误说明": "资源已收敛" if 成功 else f"Provider资源未收敛: {'；'.join(未收敛)}",
            "可重试": not 成功, "未收敛": 未收敛,
            "已使用SIGKILL": 已使用SIGKILL, "退出码": self.退出码,
        }
        self.关闭账本.append(dict(结果, 时间=time.time()))
        return 结果

    def 关闭(self) -> dict[str, Any]:
        """优雅请求后按 TERM→KILL 收口；只有全部资源核对通过才成功。"""
        进程 = self.进程
        已使用SIGKILL = 假
        if self._进程组存活():
            if 进程 is not None and 进程.poll() is None:
                try:
                    self._发送请求({"请求id": uuid.uuid4().hex[:12], "类型": "停止"})
                except (TimeoutError, ConnectionError, json.JSONDecodeError, OSError, ValueError):
                    pass
                try:
                    进程.wait(timeout=self.调用超时秒)
                except subprocess.TimeoutExpired:
                    pass
            if self._进程组存活():
                self._发进程组信号(信号_终止)
                self._等待进程组退出(min(max(self.调用超时秒, 0.05), 1.0))
            if self._进程组存活():
                已使用SIGKILL = 真
                self._发进程组信号(信号_强杀)
                self._等待进程组退出(2.0)
            if 进程 is not None:
                self.退出码 = 进程.poll()
        return self._关闭结果(已使用SIGKILL=已使用SIGKILL)

    def 重试关闭(self) -> dict[str, Any]:
        return self.关闭()

    def 优雅停止(self) -> tuple[bool, str]:
        结果 = self.关闭()
        return bool(结果["成功"]), str(结果["错误说明"])

    def 强制终止(self) -> tuple[bool, str]:
        进程 = self.进程
        已使用SIGKILL = 假
        if self._进程组存活():
            self._发进程组信号(信号_终止)
            self._等待进程组退出(min(max(self.调用超时秒, 0.05), 1.0))
            if self._进程组存活():
                已使用SIGKILL = 真
                self._发进程组信号(信号_强杀)
                self._等待进程组退出(2.0)
            if 进程 is not None:
                self.退出码 = 进程.poll()
        结果 = self._关闭结果(已使用SIGKILL=已使用SIGKILL)
        return bool(结果["成功"]), str(结果["错误说明"])

    def 停止(self) -> tuple[bool, str]:
        return self.优雅停止()

    def 关闭并清理(self) -> dict[str, Any]:
        return self.关闭()


class 提供者进程池:
    """有界 Provider 进程池；资源键稳定绑定成员，每个成员独立管道和通信锁。"""

    def __init__(self, 名称: str, *, 池大小: int = 2, 最大资源键数: int = 4096,
                 工作器路径: Path | None = None, 启动超时秒: float = 5.0,
                 调用超时秒: float = 3.0, 最大重启次数: int = 3,
                 解释器路径: str | None = None, 提供者目录: Path | None = None) -> None:
        if not 1 <= int(池大小) <= 最大允许池大小:
            raise ValueError(f"池大小必须在 1..{最大允许池大小} 之间")
        if 最大资源键数 < 池大小:
            raise ValueError("最大资源键数不得小于池大小")
        self.名称 = 名称
        self.池大小 = int(池大小)
        self.最大资源键数 = int(最大资源键数)
        self.成员表 = [独立进程(
            f"{名称}#{序号 + 1}", 工作器路径=工作器路径,
            启动超时秒=启动超时秒, 调用超时秒=调用超时秒,
            最大重启次数=最大重启次数, 解释器路径=解释器路径,
            提供者目录=提供者目录) for 序号 in range(self.池大小)]
        self.资源分配: OrderedDict[str, int] = OrderedDict()
        self._分配锁 = threading.Lock()
        self.关闭账本: list[dict[str, Any]] = []
        self.运行状态 = 进程状态_已创建

    def 启动(self) -> tuple[bool, str]:
        已启动: list[独立进程] = []
        for 成员 in self.成员表:
            成功, 消息 = 成员.启动()
            if not 成功:
                for 已有成员 in 已启动:
                    已有成员.关闭并清理()
                self.运行状态 = 进程状态_故障
                return 假, f"成员 {成员.名称} 启动失败: {消息}"
            已启动.append(成员)
        self.运行状态 = 进程状态_运行中
        return 真, f"Provider进程池启动成功（{self.池大小} 个成员）"

    def _分配成员(self, 资源键: str) -> 独立进程 | None:
        """按资源键分配池成员（**有界 LRU**：满表淘汰最久未用，不拒绝新键）。

        **为什么必须淘汰而不是拒绝**（同一缺陷在本仓已出现三次：
        `平台控制面/提供者/进程提供者.py`、本文件、以及审计报告点的同构副本）：
        资源键是**单调增长**的 —— 长驻服务上每见过一个新键就占一格，满
        `最大资源键数` 后旧实现直接 `return None`，调用侧永久拿「资源繁忙」，
        等于**软性自我 DoS**：用过的键越多、可用键越少，且永不恢复。

        **为什么淘汰不需要释放池内资源**：本表是「键 → 成员索引」的**等价绑定**，
        索引由 `sha256(键) % 池大小` 纯函数决定，池成员是**共享的**（不是一键一成员），
        生命周期归 `关闭()` 统一管理。淘汰只丢一行缓存记录；被淘汰的键再次到来时，
        按同一哈希必然绑回**同一个成员对象**（`is` 同一性已实测）。

        命中时 `move_to_end` 刷「最近使用」才是真 LRU —— 少了它退化成 FIFO，
        会把仍活跃的键淘汰掉（反向验证拍2 专测这条）。
        """
        with self._分配锁:
            索引 = self.资源分配.get(资源键)
            if 索引 is None:
                # 满表：先淘汰最久未用的键，再接受新键（**不再有「满表拒绝」分支**）
                while len(self.资源分配) >= self.最大资源键数:
                    self.资源分配.popitem(last=False)
                摘要 = hashlib.sha256(资源键.encode("utf-8")).digest()
                索引 = int.from_bytes(摘要[:8], "big") % self.池大小
                self.资源分配[资源键] = 索引
            else:
                self.资源分配.move_to_end(资源键)
            return self.成员表[索引]

    def 调用(self, *, 能力id: str, 参数: dict | None = None,
             契约版本: str | None = None, 资源键: str | None = None) -> 进程调用结果:
        契约版本 = 契约版本 or 取契约版本()
        键 = str(资源键 or 能力id)
        成员 = self._分配成员(键)
        if 成员 is None:
            return 进程调用结果(假, 错误码="资源繁忙",
                              错误说明="Provider资源键表已满", 可重试=真)
        return 成员.调用(能力id=能力id, 参数=参数, 契约版本=契约版本)

    def 健康检查(self) -> bool:
        return bool(self.成员表) and all(成员.健康检查() for 成员 in self.成员表)

    def _核对资源收敛(self) -> list[str]:
        未收敛: list[str] = []
        for 序号, 成员 in enumerate(self.成员表):
            未收敛.extend(f"成员{序号 + 1}:{问题}" for 问题 in 成员._核对资源收敛())
        return 未收敛

    def 关闭(self) -> dict[str, Any]:
        成员结果 = [成员.关闭并清理() for 成员 in self.成员表]
        未收敛 = self._核对资源收敛()
        成功 = not 未收敛 and all(结果["成功"] for 结果 in 成员结果)
        if not 成功 and not 未收敛:
            未收敛 = [结果["错误说明"] for 结果 in 成员结果 if not 结果["成功"]]
        self.运行状态 = 进程状态_已停止 if 成功 else 进程状态_故障
        结果 = {
            "成功": 成功, "错误码": "" if 成功 else "资源未收敛",
            "错误说明": "Provider进程池资源已收敛" if 成功 else f"Provider进程池资源未收敛: {'；'.join(未收敛)}",
            "可重试": not 成功, "未收敛": 未收敛,
            "已使用SIGKILL": any(项.get("已使用SIGKILL", 假) for 项 in 成员结果),
            "成员结果": 成员结果,
        }
        self.关闭账本.append(dict(结果, 时间=time.time()))
        return 结果

    def 重试关闭(self) -> dict[str, Any]:
        return self.关闭()

    def 状态(self) -> dict[str, Any]:
        成员状态 = [{
            "名称": 成员.名称,
            "状态": 成员.状态,
            "pid": 成员.进程.pid if 成员.进程 is not None else None,
            "stderr日志": list(成员.stderr日志),
            "退出码": 成员.退出码,
        } for 成员 in self.成员表]
        return {
            "状态": self.运行状态, "池大小": self.池大小,
            "pid表": [项["pid"] for 项 in 成员状态 if 项["pid"] is not None],
            "成员表": 成员状态, "资源分配": dict(self.资源分配),
            "关闭账本": list(self.关闭账本),
        }


class 进程管理器:
    """进程管理器（第五阶段兼容接口）：创建、监控、重启、隔离。"""

    def __init__(self) -> None:
        self.进程表: dict[str, 独立进程] = {}
        self.日志表: list[str] = []

    def 创建进程(self, 名称: str, *, 版本: str = "") -> 独立进程:
        进程 = 独立进程(名称)
        进程.版本号 = 版本
        self.进程表[名称] = 进程
        return 进程

    def 启动并检查(self, 进程: 独立进程) -> tuple[bool, str]:
        成功, 消息 = 进程.启动()
        if not 成功:
            return 假, f"启动失败: {消息}"
        if not 进程.健康检查():
            return 假, "健康检查失败（已触发崩溃重启）"
        return 真, f"运行正常（版本 {getattr(进程, '版本号', '未知')}）"

    def 记录日志(self, 进程: 独立进程, 消息: str) -> None:
        self.日志表.append(f"[{进程.名称}:{getattr(进程, '进程', None).pid if 进程.进程 else '无pid'}] {消息}")

    def 全部健康(self) -> bool:
        return all(进程.状态 == "运行中" for 进程 in self.进程表.values())

    def 停止全部(self, *, 优雅: bool = 真) -> list[str]:
        结果列表 = []
        for 进程 in self.进程表.values():
            if 进程.状态 == "运行中":
                if 优雅:
                    结果, 消息 = 进程.优雅停止()
                else:
                    结果, 消息 = 进程.强制终止()
                结果列表.append(f"{进程.名称}: {消息}")
        return 结果列表
