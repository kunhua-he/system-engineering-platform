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
- 作业表落 `作业.jsonl`（默认在 工程缓存/ 下，已被 .gitignore 覆盖），重启后
  非终态作业收敛为「崩溃」，与 40007 同语义。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
    """作业账本目录：`系统作业目录` 优先，否则 `工程缓存/作业状态`。"""
    环境目录 = os.environ.get("系统作业目录", "").strip()
    if 环境目录:
        return Path(环境目录)
    缓存根 = os.environ.get("系统底座_工程缓存根", "工程缓存")
    return Path(缓存根) / "作业状态"


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
    """作业门面：线程池执行、原子快照持久化、查询与尽力取消。"""

    def __init__(self, 存储目录: Path | None = None, *,
                 最大并发数: int = 默认最大并发数,
                 结果落盘上限字节: int = 默认结果落盘上限字节) -> None:
        self.存储目录 = Path(存储目录) if 存储目录 else 默认存储目录()
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.结果落盘上限字节 = max(1024, int(结果落盘上限字节))
        self.作业表: dict[str, 作业] = {}
        self.参数表: dict[str, dict[str, Any]] = {}
        self.未来表: dict[str, Future] = {}
        self.锁 = threading.RLock()
        self.线程池 = ThreadPoolExecutor(max_workers=max(1, int(最大并发数)),
                                          thread_name_prefix="作业")
        self.执行器: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
        self.加载()

    # ── 执行器注入（由 项目服务.py 提供，避免循环 import）──────────────────

    def 设置执行器(self, 执行器: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self.执行器 = 执行器

    # ── 持久化 ─────────────────────────────────────────────────────────

    @property
    def _账本路径(self) -> Path:
        return self.存储目录 / "作业.jsonl"

    def 加载(self) -> None:
        文件 = self._账本路径
        if not 文件.is_file():
            return
        with self.锁:
            for 行 in 文件.read_text(encoding="utf-8").splitlines():
                try:
                    数据 = json.loads(行)
                    对象 = 作业(**{键: 值 for 键, 值 in 数据.items()
                                   if 键 in 作业.__dataclass_fields__})
                except (json.JSONDecodeError, TypeError):
                    continue
                if 对象.状态 not in _终态:
                    对象.状态 = 状态_崩溃
                    对象.错误码 = "崩溃"
                    对象.错误说明 = "管理端重启，作业未完成"
                    对象.完成时间 = _现在()
                self.作业表[对象.作业id] = 对象
            self._保存已加锁()

    def _保存已加锁(self) -> None:
        if not self.存储目录.is_dir():
            return
        目标 = self._账本路径
        临时路径: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.存储目录,
                                             prefix=".作业.", suffix=".tmp", delete=False) as 输出:
                临时路径 = 输出.name
                for 对象 in self.作业表.values():
                    输出.write(json.dumps(self._落盘视图(对象), ensure_ascii=False) + "\n")
                输出.flush()
                os.fsync(输出.fileno())
            os.replace(临时路径, 目标)
        finally:
            if 临时路径 and os.path.exists(临时路径):
                os.unlink(临时路径)

    def _落盘视图(self, 对象: 作业) -> dict[str, Any]:
        """落盘结果超限即替换为摘要，避免账本被大输出撑爆（内存仍留完整结果）。

        截断同时把 `结果已截断` 标记回写内存对象：查询方能如实看到「只在账本里被截断」。
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
