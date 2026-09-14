"""MCP 管理端后台作业：长工具提交即返回，在线程池内执行，可查询与尽力取消。

解决的问题：8766 是单事件循环的 asyncio 服务，长工具（发布门禁、合规扫描、跑 unittest）
同步阻塞事件循环，把同一实例上其它会话的调用堵在队里。作业模型让提交立即返回，
长活在线程里跑，事件循环不再被占死。

与 40007 `运行核心/任务调度/任务系统.py` 的差异：那边用 multiprocessing fork 独立进程
（可 killpg 真取消），本模块在 asyncio 进程内，fork 有死锁风险，故改用线程池。
状态机与终态名与那边逐字对齐。

边界（如实声明）：
- 并发默认 **1（串行队列）**：本模块只解决「长活别占事件循环」，不引入工具级并发——
  五十来个工具是否线程安全未逐一验证，多个作业同时改写共享缓存 / 权威状态会出新竞态。
  确认某类工具可并发后，可用 `最大并发数` 显式调大。排队中的作业状态是「等待中」。
- 取消是尽力取消——未开始的可真取消；已运行中的只能标记并丢弃产出（线程无法中断
  阻塞中的 subprocess.run）。超时由目标工具自身参数负责，本模块不假装能中断线程。
- 作业表落**底座运行库**（`工程缓存/运行数据/底座运行.db` 的 `作业` 域，经唯一 SQLite
  支持库访问），重启后非终态作业收敛为「崩溃」，与 40007 同语义。旧 `作业.jsonl`
  只做只读兼容与首次搬迁，不再写文件（华哥 2026-09-15 定盘：运行态一律入库、不搞双写）。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

系统根 = Path(__file__).resolve().parents[1]

状态_等待中 = "等待中"
状态_运行中 = "运行中"
状态_成功 = "成功"
状态_失败 = "失败"
状态_已取消 = "已取消"
状态_超时 = "超时"
状态_崩溃 = "崩溃"

_终态 = frozenset({状态_成功, 状态_失败, 状态_已取消, 状态_超时, 状态_崩溃})

默认最大并发数 = 1
默认结果落盘上限字节 = 512 * 1024


def 默认存储目录() -> Path:
    """旧作业账本目录：`系统作业目录` 优先，否则 `工程缓存/作业状态`（只读兼容用）。"""
    环境目录 = os.environ.get("系统作业目录", "").strip()
    if 环境目录:
        return Path(环境目录)
    缓存根 = os.environ.get("系统底座_工程缓存根", "工程缓存")
    return Path(缓存根) / "作业状态"


def 默认运行库路径() -> str:
    """底座运行库路径（运行态唯一落点；可用 `系统库运行库` 环境变量覆盖）。"""
    环境 = os.environ.get("系统库运行库", "").strip()
    if 环境:
        return 环境
    return str(系统根 / "工程缓存" / "运行数据" / "底座运行.db")


def 是否终态(状态: str) -> bool:
    """终态判定：等待中 / 运行中 之外皆为终态（成功/失败/已取消/超时/崩溃）。"""
    return 状态 in _终态


def _现在() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class 作业:
    作业id: str
    工具: str
    状态: str = 状态_等待中
    结果: Any = None
    错误码: str = ""
    错误说明: str = ""
    开工id: str = ""
    创建时间: str = ""
    开始时间: str = ""
    完成时间: str = ""
    取消标记: bool = False
    结果已截断: bool = False
    _单调开始: float = field(default=0.0, repr=False)

    def 转字典(self, *, 含结果: bool = True) -> dict[str, Any]:
        数据 = {
            "作业id": self.作业id, "工具": self.工具, "状态": self.状态,
            "错误码": self.错误码, "错误说明": self.错误说明, "开工id": self.开工id,
            "创建时间": self.创建时间, "开始时间": self.开始时间,
            "完成时间": self.完成时间, "取消标记": self.取消标记,
            "结果已截断": self.结果已截断,
        }
        if 含结果:
            数据["结果"] = self.结果
        return 数据


class 作业系统:
    """作业门面：线程池执行、运行库持久化、查询与尽力取消。"""

    def __init__(self, 存储目录: Path | None = None, *,
                 最大并发数: int = 默认最大并发数,
                 结果落盘上限字节: int = 默认结果落盘上限字节,
                 运行库路径: str | None = None) -> None:
        # 存储目录 只用于迁移期读旧 `作业.jsonl`（只读兼容），不再是写入落点。
        self.存储目录 = Path(存储目录) if 存储目录 else 默认存储目录()
        # 运行态唯一落点（华哥 2026-09-15 定盘：运行态一律入库，不再写 JSONL）。
        self.运行库路径 = str(运行库路径).strip() if 运行库路径 else 默认运行库路径()
        self.结果落盘上限字节 = max(1024, int(结果落盘上限字节))
        self.作业表: dict[str, 作业] = {}
        self.参数表: dict[str, dict[str, Any]] = {}
        self.未来表: dict[str, Future] = {}
        self.锁 = threading.RLock()
        self.线程池 = ThreadPoolExecutor(max_workers=max(1, int(最大并发数)),
                                          thread_name_prefix="作业")
        self.执行器: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
        self.上次落盘指纹: dict[str, str] = {}
        self.同步错误: str = ""
        self.加载()

    # ── 执行器注入（由 项目服务.py 提供，避免循环 import）──────────────────

    def 设置执行器(self, 执行器: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self.执行器 = 执行器

    # ── 持久化（运行库为唯一落点；旧 JSONL 只读兼容 + 首次搬迁）────────────

    @property
    def _旧账本路径(self) -> Path:
        """迁移期只读兼容的旧账本（`作业.jsonl`）：不删、不再写。"""
        return self.存储目录 / "作业.jsonl"

    def _运行库调用(self, 能力id: str, 参数: dict[str, Any]) -> Any:
        """经唯一调用入口访问底座运行库；不可用时记入 `同步错误`（可见，不静默）。"""
        try:
            # 注册惰性装配钩子：MCP 管理端进程不经加载器装配，缺这步会恒「未装配」。
            import 运行核心.能力调用.唯一能力调用  # noqa: F401

            from 公共契约.能力契约.调用器 import 获取能力调用器

            return 获取能力调用器().调用能力(能力id, 参数)
        except Exception as 错误:  # noqa: BLE001 —— 运行库不可用必须可见，见 同步错误
            self.同步错误 = f"运行库不可用：{错误}"
            return None

    def _读运行库(self) -> list[dict[str, Any]] | None:
        """从运行库读回作业记录；库不可用或为空时返回 None（交给旧账本回退）。"""
        结果对象 = self._运行库调用(
            "数据库连接支持库.SQLite数据库.查询运行态",
            {"数据库路径": self.运行库路径, "域": "作业", "限制": 1000, "超时秒": 10.0},
        )
        if 结果对象 is None or not 结果对象.成功:
            return None
        值 = 结果对象.值 if isinstance(结果对象.值, dict) else {}
        行列表 = 值.get("行列表") or []
        if not 行列表:
            return None
        记录表: list[dict[str, Any]] = []
        for 行 in 行列表:
            载荷 = 行.get("载荷") if isinstance(行, dict) else None
            try:
                记录 = json.loads(载荷) if isinstance(载荷, str) and 载荷 else {}
            except json.JSONDecodeError:
                continue
            if isinstance(记录, dict) and 记录:
                记录表.append(记录)
        return 记录表 or None

    def _读旧账本(self) -> list[dict[str, Any]]:
        """迁移期只读兼容：读旧 `作业.jsonl`（首次加载后一次性搬入运行库）。"""
        文件 = self._旧账本路径
        if not 文件.is_file():
            return []
        记录表: list[dict[str, Any]] = []
        for 行 in 文件.read_text(encoding="utf-8").splitlines():
            if not 行.strip():
                continue
            try:
                记录表.append(json.loads(行))
            except json.JSONDecodeError:
                continue
        return 记录表

    def 加载(self) -> None:
        """先读运行库；库空时回退读旧账本，并把旧账本一次性搬进运行库（不双写）。"""
        记录表 = self._读运行库()
        需搬迁 = 记录表 is None
        if 需搬迁:
            记录表 = self._读旧账本()
        if not 记录表:
            return
        with self.锁:
            for 数据 in 记录表:
                try:
                    对象 = 作业(**{键: 值 for 键, 值 in 数据.items()
                                   if 键 in 作业.__dataclass_fields__})
                except TypeError:
                    continue
                if 对象.状态 not in _终态:
                    对象.状态 = 状态_崩溃
                    对象.错误码 = "崩溃"
                    对象.错误说明 = "管理端重启，作业未完成"
                    对象.完成时间 = _现在()
                self.作业表[对象.作业id] = 对象
            if 需搬迁:
                self._保存已加锁()

    def _保存已加锁(self) -> None:
        """落库到运行库（运行态唯一落点）；不再写 `作业.jsonl`，避免两条腿。

        按 `sha256(记录)` 指纹做增量 upsert：只写变化的行，不重写全表。
        """
        if not self.作业表:
            return
        需要写: dict[str, tuple[dict[str, Any], str]] = {}
        for 对象 in self.作业表.values():
            记录 = self._落盘视图(对象)
            记录["id"] = 对象.作业id
            指纹 = hashlib.sha256(
                json.dumps(记录, ensure_ascii=False, sort_keys=True, default=str).encode()
            ).hexdigest()
            if self.上次落盘指纹.get(对象.作业id) != 指纹:
                需要写[对象.作业id] = (记录, 指纹)
        if not 需要写:
            return
        for 作业id, (记录, 指纹) in 需要写.items():
            结果对象 = self._运行库调用(
                "数据库连接支持库.SQLite数据库.写入运行态",
                {"数据库路径": self.运行库路径, "域": "作业", "记录": 记录, "超时秒": 10.0},
            )
            if 结果对象 is None or not 结果对象.成功:
                说明 = getattr(结果对象, "错误说明", "") or "运行库不可用"
                self.同步错误 = f"作业落库失败（作业 {作业id}）：{说明}"
                return
            self.上次落盘指纹[作业id] = 指纹

    def _落盘视图(self, 对象: 作业) -> dict[str, Any]:
        """落库结果超限即替换为摘要，避免库里的载荷被大输出撑爆（内存仍留完整结果）。

        截断同时把 `结果已截断` 标记回写内存对象：查询方能如实看到「只在库/账本里被截断」。
        """
        视图 = 对象.转字典()
        结果 = 视图.get("结果")
        if 结果 is None:
            return 视图
        try:
            文本 = json.dumps(结果, ensure_ascii=False)
        except (TypeError, ValueError):
            视图["结果"] = {"截断": True, "消息": "结果不可 JSON 序列化，未落盘"}
            视图["结果已截断"] = True
            对象.结果已截断 = True
            return 视图
        字节数 = len(文本.encode("utf-8"))
        if 字节数 > self.结果落盘上限字节:
            视图["结果"] = {
                "截断": True, "原字节数": 字节数,
                "消息": f"结果超过 {self.结果落盘上限字节} 字节，账本未存全文；进程内存内仍可查。",
            }
            视图["结果已截断"] = True
            对象.结果已截断 = True
        return 视图

    # ── 提交 / 执行 ────────────────────────────────────────────────────

    def 提交(self, 工具: str, 参数: dict[str, Any] | None = None, *,
             开工id: str = "") -> dict[str, Any]:
        """提交作业并返回**快照**（不是活动对象）：线程随即会改状态，返回可变对象会骗调用方。"""
        工具名 = str(工具 or "").strip()
        if not 工具名:
            raise ValueError("工具名必填")
        if self.执行器 is None:
            raise ValueError("作业系统未注入执行器")
        if 工具名 in 作业工具名集:
            raise ValueError(f"作业工具不可嵌套提交：{工具名}")
        作业id = uuid.uuid4().hex[:16]
        对象 = 作业(作业id=作业id, 工具=工具名, 创建时间=_现在(),
                    开工id=str(开工id or ""))
        参数副本 = dict(参数 or {})
        with self.锁:
            self.作业表[作业id] = 对象
            self.参数表[作业id] = 参数副本
            self._保存已加锁()
        未来 = self.线程池.submit(self._执行, 作业id)
        with self.锁:
            self.未来表[作业id] = 未来
            return self.视图(对象, 含结果=False)

    def _执行(self, 作业id: str) -> None:
        with self.锁:
            对象 = self.作业表.get(作业id)
            if 对象 is None or 对象.状态 in _终态:
                return
            if 对象.取消标记:
                self._收敛已加锁(对象, 状态_已取消, "已取消", "作业未开始即取消")
                return
            对象.状态 = 状态_运行中
            对象.开始时间 = _现在()
            对象._单调开始 = time.monotonic()
            参数 = self.参数表.get(作业id, {})
            执行器 = self.执行器
            self._保存已加锁()
        try:
            数据 = 执行器(对象.工具, 参数) if 执行器 else {"成功": False, "错误码": "无执行器"}
        except Exception as 错误:  # 执行器自身崩溃：作业判失败，不炸线程池
            with self.锁:
                self._收敛已加锁(对象, 状态_失败, type(错误).__name__, str(错误))
            return
        finally:
            self.参数表.pop(作业id, None)
        with self.锁:
            对象.结果 = 数据
            if 对象.取消标记:
                self._收敛已加锁(对象, 状态_已取消, "已取消",
                                 "运行中被打上取消标记，产出已丢弃")
            elif isinstance(数据, dict) and 数据.get("成功") is False:
                self._收敛已加锁(对象, 状态_失败,
                                 str(数据.get("错误码", "") or "执行失败"),
                                 str(数据.get("错误说明", "") or 数据.get("消息", "")))
            else:
                self._收敛已加锁(对象, 状态_成功)

    def _收敛已加锁(self, 对象: 作业, 状态: str, 错误码: str = "",
                    错误说明: str = "") -> None:
        对象.状态 = 状态
        对象.错误码 = 错误码
        对象.错误说明 = 错误说明
        对象.完成时间 = _现在()
        self.未来表.pop(对象.作业id, None)  # 终态作业不再需要 Future；取消走到这就提前返回了
        self._保存已加锁()

    # ── 查询 / 取消 / 列出 ──────────────────────────────────────────────

    def 查询(self, 作业id: str) -> 作业:
        作业id = str(作业id or "").strip()
        with self.锁:
            对象 = self.作业表.get(作业id)
            if 对象 is None:
                raise KeyError(f"未知作业id: {作业id}")
            return 对象

    def 列出(self, 数量: int = 20) -> list[作业]:
        with self.锁:
            表 = sorted(self.作业表.values(), key=lambda 项: 项.创建时间, reverse=True)
            return 表[:max(1, int(数量))]

    def 取消(self, 作业id: str) -> tuple[bool, str]:
        作业id = str(作业id or "").strip()
        with self.锁:
            对象 = self.作业表.get(作业id)
            if 对象 is None:
                return False, f"未知作业id: {作业id}"
            if 对象.状态 in _终态:
                return True, f"作业已处于终态 {对象.状态}（取消幂等）"
            对象.取消标记 = True
            未来 = self.未来表.get(作业id)
        if 未来 is not None and 未来.cancel():
            with self.锁:
                self.参数表.pop(作业id, None)  # 线程不会启动了，_执行 的 finally 清不到这份参数
                self._收敛已加锁(对象, 状态_已取消, "已取消", "作业未开始，已直接取消")
            return True, "作业未开始，已直接取消"
        return True, "作业运行中已标记取消；产出将被丢弃（阻塞中的子进程无法中断）"

    def 活动数(self) -> int:
        with self.锁:
            return sum(1 for 对象 in self.作业表.values() if 对象.状态 not in _终态)

    def 关闭(self, *, 等待秒数: float = 2.0) -> None:
        self.线程池.shutdown(wait=False, cancel_futures=False)
        del 等待秒数  # 保留签名供调用方显式表达意图；线程池不阻塞等待

    def 视图(self, 对象: 作业, *, 含结果: bool = True) -> dict[str, Any]:
        """查询视图：附运行时长（运行中才有），便于判断「卡了多久」。"""
        数据 = 对象.转字典(含结果=含结果)
        if 对象.状态 == 状态_运行中 and 对象._单调开始:
            数据["已运行秒"] = round(time.monotonic() - 对象._单调开始, 3)
        return 数据


# 作业工具自身不可作为作业目标，防递归提交。
作业工具名集 = frozenset({"tool_job_submit", "tool_job_query", "tool_job_cancel"})
