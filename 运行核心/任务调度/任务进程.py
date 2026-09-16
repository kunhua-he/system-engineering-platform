"""独立任务进程：每个任务使用独立进程，支持真实超时、取消和回收。

**跨平台收口（华哥 2026-09-16 裁决：底座做完整跨平台）**：独立进程组建立、进程组存活
判定、组信号发送全部走 `公共契约/运行时/平台适配.py` 与 `公共契约/运行时/进程终止.py`
—— **本文件调用点不含任何平台判断**（无 `os.name` / `sys.platform` / `os.killpg` /
`os.getpgrp`）。两条必保语义都在：① **「不向自己进程组发信号」的自保护**（组号与本进程
组号相同时拒绝整组发信号）；② **「组长已回收但同组子孙仍在」仍按组回收**（只有收口层
的按组号原语能表达，`os.getpgid(组长pid)` 在组长被 join 回收后必然失败）。

**启动方式按平台收口**：POSIX 用 `fork`（子进程继承已注册的中文能力表，执行器零序列化）；
其他平台（Windows 只有 `spawn`）用 `spawn`，执行器在提交点**显式 pickle 成字节**送达子进程
——旧实现无条件强制 `fork`，在 Windows 上 `get_context("fork")` 抛 `ValueError`，把
`启动运行核心网关.py` 在导入期直接打死。
"""

from __future__ import annotations

import json
import multiprocessing
import os
import pickle
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from 公共契约.运行时 import 平台适配, 进程终止
from 运行核心.任务调度.任务工作器 import 执行单次任务

任务状态_等待中 = "等待中"
任务状态_运行中 = "运行中"
任务状态_成功 = "成功"
任务状态_失败 = "失败"
任务状态_取消中 = "取消中"
任务状态_已取消 = "已取消"
任务状态_超时 = "超时"
任务状态_崩溃 = "崩溃"

_终态 = {任务状态_成功, 任务状态_失败, 任务状态_已取消, 任务状态_超时, 任务状态_崩溃}

#: 收口层 进程终止 的信号语义名（POSIX → SIGTERM/SIGKILL；Windows → taskkill 不带/带 /F）
信号_终止 = "终止"
信号_强杀 = "强杀"


def _本进程组号() -> int | None:
    """本进程所属进程组号；平台无进程组概念时由收口层如实回 ``None``。

    只问能力、不写平台判断：这是「不要打自己」安全闸与「本平台有无进程组」判定的唯一来源。
    """
    return 进程终止.进程组号(os.getpid())


class 资源繁忙错误(Exception):
    """提交任务超过进程池有界容量时的统一资源繁忙错误，区分"忙"与"失败"。"""

    def __init__(self, 消息: str = "") -> None:
        super().__init__(消息 or "任务进程池资源繁忙，拒绝提交新任务")


def _还原执行器(执行器: Any) -> Callable:
    """还原执行器句柄：`spawn` 送达的是字节（显式序列化），`fork` 直接是函数对象。"""
    if isinstance(执行器, (bytes, bytearray)):
        return pickle.loads(bytes(执行器))
    return 执行器


def _执行任务进程入口(进程组就绪事件: Any, 发送连接: Any, 执行器: Any,
                    请求: dict[str, Any], 取消事件: Any) -> None:
    """先建立独立会话/进程组，再允许能力启动任何后代进程。

    「本平台是否具备独立进程组」由收口层判定（`进程终止.进程组号(本进程pid)`，非 POSIX
    平台如实回 `None`）：**不具备时不建立、也绝不谎报就绪** —— 该平台上「整棵回收」由
    收口层的进程树终止（Windows `taskkill /T`）承担，`_发送工作器信号` 走同一条收口；
    具备时按 POSIX 语义 `os.setsid()` 建独立进程组，建立失败（`OSError`）即明确报
    「进程组建立失败」并拒绝执行 —— 绝不静默跳过，那会让取消/超时路径无法整组回收。
    """
    函数 = _还原执行器(执行器)
    if 进程终止.进程组号(os.getpid()) is not None:
        try:
            os.setsid()
        except OSError as 错误:
            响应 = {
                "任务id": 请求.get("任务id", ""), "成功": False,
                "错误码": "进程组建立失败", "错误说明": str(错误),
            }
            try:
                发送连接.send_bytes(json.dumps(响应, ensure_ascii=False).encode("utf-8"))
            finally:
                发送连接.close()
            return
        进程组就绪事件.set()
    执行单次任务(发送连接, 函数, 请求, 取消事件)


class 独立任务:
    def __init__(self, *, 任务id: str = "", 能力id: str = "", 项目id: str = "",
                 用户id: str = "", 请求id: str = "", 超时秒: float = 10.0) -> None:
        self.任务id = 任务id or uuid.uuid4().hex[:16]
        self.能力id = 能力id
        self.项目id = 项目id
        self.用户id = 用户id
        self.请求id = 请求id
        self.超时秒 = max(0.01, float(超时秒))
        self.状态 = 任务状态_等待中
        self.进度 = 0.0
        self.结果: Any = None
        self.错误码 = ""
        self.错误说明 = ""
        self.日志: list[str] = []
        self.进程: multiprocessing.Process | None = None
        self.进程组id: int | None = None
        self.进程组就绪事件: Any = None
        self.接收连接: Any = None
        self.取消事件: Any = None
        self.待发布状态 = ""
        self.待发布错误码 = ""
        self.待发布错误说明 = ""
        #: 结果连接是否已被读取过（单读者仲裁，B-07）：每任务最多收取一次结果，
        #: 不可能出现两个读者对同一连接并发 poll→recv。
        self.结果已收取 = False
        #: 本会话是否真实起过工作进程（B-08）：从磁盘快照重建的对象恒为 False，
        #: 它没有状态话语权，不能把重启收敛结果覆盖回「运行中」。
        self.本会话活动 = False
        self.截止时刻: float = 0.0
        self.创建时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        self.完成时间 = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "任务id": self.任务id, "能力id": self.能力id, "状态": self.状态,
            "进度": self.进度, "结果": self.结果, "错误码": self.错误码,
            "错误说明": self.错误说明, "日志": list(self.日志),
            "项目id": self.项目id, "用户id": self.用户id, "请求id": self.请求id,
            "创建时间": self.创建时间, "完成时间": self.完成时间,
        }


class 任务进程池:
    """每任务独立进程；fork 继承已注册函数，连接中只传 JSON 字节。

    资源治理（手册第十节 10.1）：进程数与排队任务有界；提交超过容量时
    阻塞到明确截止或返回统一资源繁忙错误；内部只保留一个轮询监视线程
    （线程数不超过 最大活动数+1），禁止为每个任务无限创建监视线程。
    """

    def __init__(self, *, 工作器路径: Path | None = None, 存储目录: Path | None = None,
                 解释器: str | None = None, 最大活动数: int = 4,
                 最大排队数: int = 16, 提交截止秒: float = 30.0,
                 终止截止秒: float = 1.5, 排空截止秒: float = 5.0,
                 关闭截止秒: float = 2.0) -> None:
        self.工作器路径 = 工作器路径
        self.解释器 = 解释器
        self.存储目录 = 存储目录 or Path(tempfile.gettempdir()) / "系统级支持库_任务进程"
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.任务表: dict[str, 独立任务] = {}
        self.执行函数表: dict[str, Callable] = {}
        self.锁 = threading.RLock()
        self.最大活动数 = max(1, int(最大活动数))
        self.最大排队数 = max(0, int(最大排队数))
        self.提交截止秒 = max(0.0, float(提交截止秒))
        self.终止截止秒 = max(0.0, float(终止截止秒))
        self.排空截止秒 = max(0.0, float(排空截止秒))
        self.关闭截止秒 = max(0.0, float(关闭截止秒))
        self.等待队列: list[独立任务] = []
        self.活动任务表: dict[str, 独立任务] = {}
        self.已停止 = False
        self.提交条件 = threading.Condition(self.锁)
        self.监视线程: threading.Thread | None = None
        self.监视唤醒事件 = threading.Event()
        self.监视停止事件 = threading.Event()
        self.进程上下文, self.需序列化执行器 = self._选择进程上下文()

    @staticmethod
    def _选择进程上下文() -> tuple[Any, bool]:
        """按平台选多进程启动方式；返回 `(上下文, 执行器是否必须显式序列化)`。

        - POSIX → `fork`：子进程继承父进程里已注册的中文能力表，执行器直接传函数对象。
        - 其他平台（Windows 上 `multiprocessing` **只有 spawn**）→ `spawn`：子进程是全新
          解释器，执行器必须经 pickle 显式送达（`_准备执行器`）。
        - 自称 POSIX 却不提供 `fork` 的受限构建 → 退回 `spawn`，由执行器序列化补齐能力。

        平台判定只经收口层 `平台适配`（本文件调用点仍不直接读 `sys.platform` / `os.name`）。
        """
        if 平台适配.是POSIX():
            try:
                return multiprocessing.get_context("fork"), False
            except ValueError:
                pass
        return multiprocessing.get_context("spawn"), True

    def _准备执行器(self, 能力id: str, 函数: Callable) -> Any:
        """按启动方式准备执行器句柄：`fork` 给函数对象，`spawn` 显式 pickle 成字节。

        **为什么在提交点显式做**：`spawn` 下执行器只能靠序列化过去，若留给 `进程.start()`
        隐式序列化，失败会发生在子进程创建路径上且难以归因（任务会卡在「运行中」的黑洞里）。
        这里失败即抛能力级明确错误，调用方按「提交失败」处理，错误信息直接指出是哪个能力。
        """
        if not self.需序列化执行器:
            return 函数
        try:
            return pickle.dumps(函数)
        except Exception as 错误:  # noqa: BLE001 —— 任何不可序列化都必须转成一句人话
            raise RuntimeError(
                f"当前平台的多进程启动方式为 spawn，任务执行器必须可序列化；"
                f"能力[{能力id}] 的执行器不是模块级可导出对象（如 lambda / 局部闭包 / 未注册实例方法）："
                f"{type(错误).__name__}: {错误}") from 错误

    def 注册执行函数(self, 能力id: str, 函数: Callable) -> None:
        with self.锁:
            self.执行函数表[能力id] = 函数

    def 提交(self, *, 能力id: str, 参数: dict | None = None, 项目id: str = "",
             用户id: str = "", 请求id: str = "", 超时秒: float = 10.0) -> 独立任务:
        """有界提交：活动进程数达到上限时排队等待，超容量或超截止返回资源繁忙错误。

        **「入队即占槽、上抛必归还」是不变式**：`len(等待队列)` 就是排队容量判据，
        因此本方法任何异常路径（含 `KeyboardInterrupt` / `SystemExit` 这类
        `BaseException`）都必须在把异常抛给调用方之前**先把自己的排队槽还回去**
        （`_退出排队`）。旧实现把归还写在两处 `raise` 之后，抛异常时永不执行：
        死条目会一直留在等待队列里吃掉一个排队槽，后续正常提交被误判成「资源繁忙」，
        且没有任何调用方能再清理它（只有 `停止`/`排空` 才会整队清空）。
        """
        任务对象 = 独立任务(能力id=能力id, 项目id=项目id, 用户id=用户id,
                         请求id=请求id, 超时秒=超时秒)
        with self.锁:
            函数 = self.执行函数表.get(能力id)
            if 函数 is None:
                self.任务表[任务对象.任务id] = 任务对象
                self._完成失败(任务对象, 任务状态_失败, "能力不存在", f"任务能力未注册: {能力id}")
                return 任务对象
            # 截止计算移出入队判断：排队等待全程复用同一截止；已入队任务等槽位
            # 不受截止约束（有界队列语义：排队任务不得丢失），但 wait 一律带
            # 超时心跳（可感知停止标志与唤醒通知，不永久无界阻塞）
            提交截止 = time.monotonic() + self.提交截止秒 if self.提交截止秒 > 0 else 0.0
            try:
                while self.活动进程数() >= self.最大活动数:
                    if self.已停止:
                        raise RuntimeError("任务进程池已停止，拒绝提交新任务")
                    if 任务对象 not in self.等待队列:
                        if len(self.等待队列) < self.最大排队数:
                            self.等待队列.append(任务对象)
                        elif self.提交截止秒 <= 0:
                            raise 资源繁忙错误(
                                f"任务进程池排队已满（上限 {self.最大排队数}），资源繁忙，"
                                f"任务[{任务对象.任务id}]未提交且未丢失")
                        else:
                            # 队列满且未入队：阻塞到明确截止，超时返回提交超时错误
                            剩余截止 = 提交截止 - time.monotonic()
                            if 剩余截止 <= 0:
                                raise 资源繁忙错误(
                                    f"提交任务[{任务对象.任务id}]等待槽位超过 "
                                    f"{self.提交截止秒} 秒，进程池资源繁忙（提交超时）")
                            self.提交条件.wait(timeout=剩余截止)
                            continue
                    # 已入队：带心跳等待槽位（排队任务不丢失；可感知停止）
                    self.提交条件.wait(timeout=0.1)
                if self.已停止:
                    raise RuntimeError("任务进程池已停止，拒绝提交新任务")
                # 拿到槽位：先归还排队槽再建进程（归还与建进程都不得中断在途，
                # 故放在同一临界区内，异常由下面的 except 统一兜底）
                self._退出排队(任务对象)
                # 「先改共享状态再抛」禁止项①：`进程.start()` 会抛（fork 失败/资源耗尽
                # 时的 `OSError`），所以**进程真正起来之前不写任何状态、不登记任何表**：
                # 状态与 `本会话活动` 一律等 start 成功后再写。旧实现先写「运行中/本会话
                # 活动」再 start，start 抛错时对象会对外谎报「运行中」而进程根本不存在。
                接收连接: Any = None
                发送连接: Any = None
                进程: Any = None
                try:
                    接收连接, 发送连接 = self.进程上下文.Pipe(duplex=False)
                    取消事件 = self.进程上下文.Event()
                    进程组就绪事件 = self.进程上下文.Event()
                    请求 = {"任务id": 任务对象.任务id, "能力id": 能力id, "参数": 参数 or {}}
                    执行器 = self._准备执行器(能力id, 函数)
                    进程 = self.进程上下文.Process(
                        target=_执行任务进程入口,
                        args=(进程组就绪事件, 发送连接, 执行器, 请求, 取消事件),
                        name=f"系统级任务-{任务对象.任务id}",
                        daemon=True,
                    )
                    进程.start()
                except BaseException:
                    # 异常路径不得泄漏句柄/连接：start 抛错时进程**可能已经 fork**
                    # （两侧管道都还开着、子进程已在跑能力），而它没进活动账本就没有
                    # 任何回收路径（`_监视循环` 只遍历活动任务表）—— 必须就地终止，
                    # 再关掉两条管道，绝不把半成品留给调用方。
                    self._终止未登记工作器(进程)
                    self._关闭连接(接收连接)
                    self._关闭连接(发送连接)
                    raise
                任务对象.接收连接 = 接收连接
                任务对象.取消事件 = 取消事件
                任务对象.进程组就绪事件 = 进程组就绪事件
                任务对象.进程 = 进程
                任务对象.截止时刻 = time.monotonic() + 任务对象.超时秒
                任务对象.进程组id = 进程.pid
                任务对象.状态 = 任务状态_运行中
                # 本会话真实起了工作进程：该对象才有状态话语权（B-08）
                任务对象.本会话活动 = True
                发送连接.close()
                self.任务表[任务对象.任务id] = 任务对象
                self.活动任务表[任务对象.任务id] = 任务对象
                # 「先改共享状态再抛」禁止项⑤：工作进程**已经真实起来了**（状态、
                # 句柄、活动账本都已就位），此处落盘失败若照旧上抛，调用方会当成
                # 「提交失败」——而任务确实在跑：调用方拿不到任务id、不会再查询；
                # 更重的是抛出会跳过方法末尾的 `_确保监视线程()`，连既有收敛路径
                # （轮询监视线程）都没启动，任务永远停在「运行中」白占一个活动
                # 账本槽位。现在把落盘失败如实记进任务日志后继续走返回路径：
                # 任务状态里（含磁盘快照）都读得到这条标记，`提交` 的返回形状与
                # 错误码集合一字不变，也不把「落盘失败」伪装成「提交失败」。
                try:
                    self._持久化(任务对象)
                except Exception as 错误:  # noqa: BLE001 —— 落盘失败如实记账，不冒充提交失败
                    任务对象.日志.append(
                        f"提交后落盘失败：{type(错误).__name__}: {错误}；"
                        "任务已提交且工作进程已在运行，重启后可能缺失该任务的磁盘快照")
                self.提交条件.notify_all()
            except BaseException:
                # 任何抛出（含中断/退出信号）都先归还排队槽再上抛：留在队列里的
                # 死条目会永久占槽并把后续提交打成「资源繁忙」，没人能再回收它。
                self._退出排队(任务对象)
                raise
        self._确保监视线程()
        return 任务对象

    def _退出排队(self, 任务对象: 独立任务) -> bool:
        """把任务从等待队列还回去（幂等）；**返回是否真的占用过一个排队槽**。

        入队/出队必须成对：只要调用方可能抛出，就一定要先经过这里再上抛
        （`提交` 的 `except BaseException` 是唯一兜底）。移除后 `notify_all()`：
        排队槽被归还，等在「队列已满」分支上的提交方不该白等到硬截止。
        """
        if 任务对象 not in self.等待队列:
            return False
        self.等待队列.remove(任务对象)
        self.提交条件.notify_all()
        return True

    @staticmethod
    def _关闭连接(连接: Any) -> None:
        """尽力关闭一条管道连接；幂等，已关闭/句柄已被回收一律不抛。"""
        if 连接 is None:
            return
        try:
            连接.close()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _终止未登记工作器(进程: Any) -> None:
        """终止 `进程.start()` 抛错时**可能已经 fork** 但未登记进账本的工作器。

        未登记进活动任务表的进程没有任何回收路径（`_监视循环` 只遍历活动账本），
        留着就是一个跑着能力、却没人能取消/回收的幽灵进程。平台差异走收口层
        （POSIX 按组 / Windows 进程树），收口失败再退到进程句柄 —— **调用点不做平台判断**。
        """
        if 进程 is None or getattr(进程, "pid", None) is None:
            return
        if not 进程终止.终止进程组(进程.pid, 信号=信号_强杀).成功:
            try:
                if hasattr(进程, "kill"):
                    进程.kill()
                else:
                    进程.terminate()
            except (OSError, ValueError, ProcessLookupError):
                pass
        try:
            进程.join(timeout=0.2)
        except (OSError, ValueError, AssertionError):
            pass


    def _确保监视线程(self) -> None:
        """进程池内部至多保留一个轮询监视线程；停止后不再启动。"""
        if self.已停止:
            return
        with self.锁:
            if self.监视线程 is not None and self.监视线程.is_alive():
                return
            self.监视停止事件 = threading.Event()
            self.监视唤醒事件 = threading.Event()
            self.监视线程 = threading.Thread(
                target=self._监视循环, name="任务进程池-监视", daemon=True)
            self.监视线程.start()

    def _监视循环(self) -> None:
        """单线程轮询活动任务表，取代每任务一个监视线程；停止事件置位后退出。

        单次轮询异常只记录并继续（不退出线程）；线程意外死亡时由提交路径
        _确保监视线程 的 is_alive 检测自动重建。
        """
        停止事件 = self.监视停止事件
        while not 停止事件.is_set():
            try:
                with self.锁:
                    快照 = list(self.活动任务表.values())
                for 任务对象 in 快照:
                    self._轮询任务(任务对象)
            except Exception as 错误:
                print(f"任务进程池-监视轮询异常（已跳过继续）: {错误}", file=sys.stderr)
            self.监视唤醒事件.wait(timeout=0.05)
            self.监视唤醒事件.clear()

    def _轮询任务(self, 任务对象: 独立任务, *, 截止时刻: float | None = None) -> None:
        """单次轮询：推进状态，但任何资源回收都不得越过调用方给定的硬截止。

        **单读者仲裁（B-07）**：`poll` 与 `recv_bytes` **全程在同一把池锁内**完成，且每个
        任务的结果连接**最多被读取一次**（`结果已收取`）。旧实现把 poll/recv 放在锁外，
        监视线程与 `排空`/`等待` 会对同一连接并发 poll→recv：两个读者分食同一字节流
        （一方拿到真实结果、另一方读到 EOF/残缺帧），读到坏帧的一方先进锁把任务判成
        「崩溃」终态，真实结果随后被 `状态 in _终态` 挡掉 —— 实测 30/30 轮全部误判，
        并把已经算完的子进程一起误杀（退出码 -15）。

        **判崩溃前必须复查 `进程.exitcode`**：只有工作进程**确认已退出**时，「读不到结果」
        才算崩溃；进程仍在运行则一律不凭「读不到东西」下终态判决（交给超时/后续轮询）。
        """
        with self.锁:
            if 任务对象.状态 in _终态:
                return
            if 任务对象.待发布状态:
                self._完成(
                    任务对象, 任务对象.待发布状态,
                    任务对象.待发布错误码, 任务对象.待发布错误说明,
                    截止时刻=截止时刻)
                return
            if 任务对象.状态 == 任务状态_取消中:
                # “请求已发出”不等于“已退出”。请求阶段只设置取消事件；
                # 若工作器自行响应退出，则在此确认后发布终态。强制终止只由
                # 取消重试/关闭路径在各自硬截止内执行。
                if not self._工作器存活(任务对象):
                    self._完成失败(
                        任务对象, 任务状态_已取消, "已取消", "任务已取消",
                        截止时刻=截止时刻)
                return
            进程 = 任务对象.进程
            连接 = 任务对象.接收连接
            已收取 = 任务对象.结果已收取
            if 连接 is not None and not 已收取 and 连接.poll():
                任务对象.结果已收取 = True
                响应 = self._收取响应(连接)
                if 响应 is not None:
                    self._发布响应(任务对象, 响应, 截止时刻=截止时刻)
                    return
                # EOF / 残缺帧 / 坏 JSON：**不得仅凭此判崩溃**，先复查进程是否真的退出
                if not self._进程已退出(进程):
                    return
                self._完成失败(
                    任务对象, 任务状态_崩溃, "崩溃",
                    f"工作进程异常退出（退出码 {self._退出码(进程)}）", 截止时刻=截止时刻)
                return
            if time.monotonic() >= 任务对象.截止时刻:
                self._完成失败(
                    任务对象, 任务状态_超时, "超时",
                    f"任务执行超过 {任务对象.超时秒} 秒", 截止时刻=截止时刻)
                return
            if self._进程已退出(进程):
                # 进程已退出：它若成功发送过，数据必已进入管道缓冲（写入先于退出），
                # 因此在这里做最后一次锁内收取；确认真的没有结果才按崩溃收敛。
                if 连接 is not None and not 已收取:
                    任务对象.结果已收取 = True
                    响应 = self._收取响应(连接) if 连接.poll() else None
                    if 响应 is not None:
                        self._发布响应(任务对象, 响应, 截止时刻=截止时刻)
                        return
                self._完成失败(
                    任务对象, 任务状态_崩溃, "崩溃",
                    f"工作进程异常退出（退出码 {self._退出码(进程)}）", 截止时刻=截止时刻)

    @staticmethod
    def _收取响应(连接: Any) -> dict[str, Any] | None:
        """锁内收取一次结果信封；EOF / 残缺帧 / 坏 JSON / 超大一律收口成 ``None``。

        调用方**必须**再用 `_进程已退出` 复查退出码才可判崩溃（B-07）：
        读到 ``None`` 只说明「这一次没读到合法信封」，不说明工作进程崩了
        （并发读者被另一读者抢先读走、句柄被回收后 read(None) 的 ``TypeError`` 都走这里）。
        """
        try:
            return json.loads(连接.recv_bytes(4 * 1024 * 1024).decode("utf-8"))
        except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError,
                ValueError, TypeError, multiprocessing.BufferTooShort):
            return None

    def _发布响应(self, 任务对象: 独立任务, 响应: Any, *,
                截止时刻: float | None = None) -> None:
        """把一次合法读出按协议发布成终态（锁内调用）。"""
        if not isinstance(响应, dict):
            self._完成失败(
                任务对象, 任务状态_失败, "协议错误",
                 f"工作进程返回的信封不是 JSON 对象：{type(响应).__name__}",
                截止时刻=截止时刻)
        elif 响应.get("取消"):
            self._完成失败(
                任务对象, 任务状态_已取消, "已取消", "任务已取消",
                截止时刻=截止时刻)
        elif 响应.get("成功", False):
            任务对象.结果 = 响应.get("值")
            self._完成(任务对象, 任务状态_成功, 截止时刻=截止时刻)
        else:
            self._完成失败(
                任务对象, 任务状态_失败,
                响应.get("错误码", "内部错误"), 响应.get("错误说明", "任务执行失败"),
                截止时刻=截止时刻)

    @staticmethod
    def _进程已退出(进程: Any) -> bool:
        """工作进程是否**确认已退出**（退出码已定）；退出码 ``None`` 即仍在运行。

        **这是判崩溃的唯一依据**：绝不用「管道读不到东西」代替（B-07 根因）。
        """
        return 进程 is not None and 进程.exitcode is not None

    @staticmethod
    def _退出码(进程: Any) -> Any:
        return 进程.exitcode if 进程 is not None else None

    def _完成失败(self, 任务对象: 独立任务, 状态: str, 错误码: str, 错误说明: str,
              *, 截止时刻: float | None = None) -> bool:
        return self._完成(
            任务对象, 状态, 错误码, 错误说明, 截止时刻=截止时刻)

    def _完成(self, 任务对象: 独立任务, 最终状态: str,
            错误码: str = "", 错误说明: str = "", *,
            截止时刻: float | None = None) -> bool:
        # 终态是对外承诺：先确认工作器退出并释放通信资源，再发布终态。
        # 强杀仍未确认收敛时不得发布终态（否则账本显示终态但进程仍持有
        # 文件/socket/句柄，形成不可观测僵尸资源）。
        任务对象.待发布状态 = 最终状态
        任务对象.待发布错误码 = 错误码
        任务对象.待发布错误说明 = 错误说明
        实际截止 = 截止时刻 if 截止时刻 is not None else time.monotonic() + self.终止截止秒
        收敛 = self._终止工作器(任务对象, 实际截止)
        if not 收敛:
            # 进程未确认退出：保留任务在活动表，标记为故障待回收，不发布终态
            任务对象.错误码 = "资源未收敛"
            任务对象.错误说明 = "结束请求已发出但完整进程组未确认退出，资源账本已保留供重试"
            self._持久化(任务对象)
            self.提交条件.notify_all()
            return False
        任务对象.错误码 = 错误码
        任务对象.错误说明 = 错误说明
        任务对象.状态 = 最终状态
        任务对象.进度 = 1.0
        任务对象.完成时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        任务对象.待发布状态 = ""
        任务对象.待发布错误码 = ""
        任务对象.待发布错误说明 = ""
        self.活动任务表.pop(任务对象.任务id, None)
        self._持久化(任务对象)
        self.提交条件.notify_all()
        return True

    @staticmethod
    def _进程组存活(进程组id: int | None) -> bool:
        """工作器进程组是否仍存活（组长已回收但同组子孙仍在也算存活）。

        **为什么必须按组号而不是按 pid**：组长一旦被 `进程.join()` 回收，
        `os.getpgid(组长pid)` 必然失败（收口层的 `进程存活` / `终止进程组` 都以它为
        判定前提），只有收口层专为此场景补齐的 `按组号探活`（`os.killpg(组号, 0)`，
        组长被回收后仍可用）能表达「组长退出、同组子孙仍在」。平台差异（Windows 无
        组概念）由收口层如实回 `False`，**本调用点不做任何平台判断**。
        """
        if not 进程组id:
            return False
        return 进程终止.按组号探活(进程组id)

    def _进程组已就绪(self, 任务对象: 独立任务) -> bool:
        """工作器是否已建立独立进程组（就绪事件只在子进程 setsid 成功后置位）。

        追加「本平台具备进程组能力」的判定：由收口 `进程组号(本进程pid)` 如实回答
        （非 POSIX 平台返回 `None`）—— 平台差异在收口层判定，调用点只问能力。
        """
        事件 = 任务对象.进程组就绪事件
        return bool(事件 is not None and 事件.is_set() and _本进程组号() is not None)

    def _工作器存活(self, 任务对象: 独立任务) -> bool:
        if self._进程组已就绪(任务对象):
            return self._进程组存活(任务对象.进程组id)
        进程 = 任务对象.进程
        return bool(进程 is not None and 进程.is_alive())

    def _发送工作器信号(self, 任务对象: 独立任务, 信号名: str) -> None:
        """向任务工作器发信号（组优先、单进程兜底），**调用点不做任何平台判断**。

        **必保的自保护语义**：`任务对象.进程组id` 与本进程所在组号相同时**拒绝整组发
        信号** —— 否则会把主进程自己一起打死（就绪事件只在子进程 setsid 成功后置位，
        正常情况下组号必不等于主进程组号）。本进程组号由收口 `进程组号()` 取（非 POSIX
        平台如实回 `None`），这不是平台判断，而是「不要打自己」的安全闸；本平台没有
        进程组能力时 `_进程组已就绪` 即为假，直接走单进程句柄信号兜底。

        组发信号全程走收口 `按组号终止`：组长已被 `join()` 回收后仍可用，且**永不抛
        异常**（失败收口成结果信封）—— 进程组可能在存活检查与发信号之间退出，EPERM
        也不能被解释成信号已送达，后续仍以存活复查决定是否收敛。
        """
        进程 = 任务对象.进程
        组号 = 任务对象.进程组id
        if 组号 and self._进程组已就绪(任务对象) and 组号 != _本进程组号():
            进程终止.按组号终止(组号, 信号=信号名)
            return
        if 进程 is None or not 进程.is_alive():
            return
        if _本进程组号() is None:
            进程号 = 进程.pid
            if 进程号:
                # 本平台没有进程组概念（收口层如实回 None，如 Windows）：整棵回收只能由收口层
                # 的**进程树终止**表达（Windows `taskkill /T`）。若在这里直接用进程句柄的
                # terminate()/kill()，只杀得掉工作进程本身，能力自己派生的子孙会漏网 ——
                # 那才是真正的「伪成功」。收口失败（无权限/不支持）时不冒充成功，
                # 落到句柄兜底，收敛与否一律以随后的存活复查为准。
                结果 = 进程终止.终止进程组(进程号, 信号=信号名)
                if 结果.成功:
                    return
        try:
            if 信号名 == 信号_强杀 and hasattr(进程, "kill"):
                进程.kill()
            else:
                进程.terminate()
        except (ProcessLookupError, OSError):
            pass

    def _等待工作器退出(self, 任务对象: 独立任务, 截止时刻: float) -> bool:
        进程 = 任务对象.进程
        while self._工作器存活(任务对象):
            剩余秒 = 截止时刻 - time.monotonic()
            if 剩余秒 <= 0:
                return False
            if 进程 is not None:
                进程.join(timeout=min(0.02, 剩余秒))
            else:
                time.sleep(min(0.01, 剩余秒))
        return True

    def _终止工作器(self, 任务对象: 独立任务, 截止时刻: float) -> bool:
        """在共享硬截止内 TERM→KILL 完整进程组；只有确认退出才回收账本。"""
        if 任务对象.取消事件 is not None:
            任务对象.取消事件.set()
        if not self._工作器存活(任务对象):
            return self._回收工作器(任务对象)
        剩余秒 = 截止时刻 - time.monotonic()
        if 剩余秒 <= 0:
            return False
        self._发送工作器信号(任务对象, 信号_终止)
        优雅截止 = min(截止时刻, time.monotonic() + min(0.2, 剩余秒 * 0.4))
        if not self._等待工作器退出(任务对象, 优雅截止):
            self._发送工作器信号(任务对象, 信号_强杀)
            self._等待工作器退出(任务对象, 截止时刻)
        return self._回收工作器(任务对象)

    def _回收工作器(self, 任务对象: 独立任务) -> bool:
        """回收工作器；返回是否确认收敛（进程已退出且管道已关闭）。"""
        进程 = 任务对象.进程
        if self._工作器存活(任务对象):
            return False
        if 进程 is not None:
            进程.join(timeout=0)
        if 任务对象.接收连接 is not None:
            try:
                任务对象.接收连接.close()
            except OSError:
                pass
            任务对象.接收连接 = None
        return True

    def _持久化(self, 任务对象: 独立任务) -> None:
        目标 = self.存储目录 / f"{任务对象.任务id}.json"
        临时路径: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.存储目录,
                                             prefix=f".{任务对象.任务id}.", suffix=".tmp",
                                             delete=False) as 输出:
                临时路径 = 输出.name
                json.dump(任务对象.转字典(), 输出, ensure_ascii=False, indent=2)
                输出.flush()
                os.fsync(输出.fileno())
            os.replace(临时路径, 目标)
        finally:
            if 临时路径 and os.path.exists(临时路径):
                os.unlink(临时路径)

    def 查询(self, 任务id: str) -> 独立任务:
        with self.锁:
            任务对象 = self.任务表.get(任务id)
            if 任务对象 is None:
                文件 = self.存储目录 / f"{任务id}.json"
                if 文件.is_file():
                    数据 = json.loads(文件.read_text(encoding="utf-8"))
                    任务对象 = 独立任务(任务id=任务id, 能力id=数据.get("能力id", ""))
                    for 键, 值 in 数据.items():
                        if hasattr(任务对象, 键):
                            setattr(任务对象, 键, 值)
                    self.任务表[任务id] = 任务对象
            if 任务对象 is None:
                raise KeyError(f"未知任务id: {任务id}")
            return 任务对象

    def 查询状态(self, 任务id: str) -> str:
        return self.查询(任务id).状态

    def 查询日志(self, 任务id: str) -> list[str]:
        return list(self.查询(任务id).日志)

    def 取消(self, 任务id: str, *, 等待截止秒: float | None = None) -> tuple[bool, str]:
        """发出取消请求，并在硬截止内确认完整进程组退出；未确认则可重试。"""
        with self.锁:
            任务对象 = self.查询(任务id)
            if 任务对象.状态 in _终态:
                return True, f"任务已处于终态 {任务对象.状态}（取消幂等）"
            # 「先改共享状态再抛」禁止项②：`_持久化` 会抛（`OSError`）。顺序必须是
            # 「先落盘成功、再发出不可撤销的取消请求」—— 落盘失败时内存状态回滚成原值，
            # 内存与磁盘始终一致，且取消事件未置位（取消请求确实没发出去，调用方可重试）。
            原状态 = 任务对象.状态
            任务对象.状态 = 任务状态_取消中
            try:
                self._持久化(任务对象)
            except BaseException:
                任务对象.状态 = 原状态
                raise
            if 任务对象.取消事件 is not None:
                任务对象.取消事件.set()
            等待秒 = self.终止截止秒 if 等待截止秒 is None else max(0.0, float(等待截止秒))
            self.监视唤醒事件.set()
            if 等待秒 <= 0:
                return False, "取消请求已发出，工作进程尚未确认退出，活动账本已保留供重试"
            任务对象.待发布状态 = 任务状态_已取消
            任务对象.待发布错误码 = "已取消"
            任务对象.待发布错误说明 = "任务已取消并终止工作进程"
            收敛 = self._终止工作器(任务对象, time.monotonic() + 等待秒)
            if not 收敛:
                任务对象.错误码 = "资源未收敛"
                任务对象.错误说明 = "取消请求已发出但完整进程组未确认退出，活动账本已保留供重试"
                self._持久化(任务对象)
                return False, 任务对象.错误说明
            self._完成失败(
                任务对象, 任务状态_已取消, "已取消", "任务已取消并终止工作进程")
            return True, "任务已取消，完整工作进程组终止完成，已确认退出"

    def 查询诊断(self, 任务id: str) -> dict[str, Any]:
        任务对象 = self.查询(任务id)
        return {"任务id": 任务id, "状态": 任务对象.状态, "错误码": 任务对象.错误码,
                "错误说明": 任务对象.错误说明, "能力id": 任务对象.能力id}

    def 活动进程数(self) -> int:
        with self.锁:
            return sum(1 for 任务对象 in self.活动任务表.values()
                       if self._工作器存活(任务对象))

    def 等待(self, 任务id: str, *, 超时秒: float = 10.0) -> tuple[bool, str]:
        """等待单任务到终态；只等待到硬截止，不把等待超时伪装成任务终态。"""
        截止时刻 = time.monotonic() + max(0.0, float(超时秒))
        while True:
            任务对象 = self.查询(任务id)
            if 任务对象.状态 in _终态:
                return True, f"任务已到终态 {任务对象.状态}"
            self._轮询任务(任务对象, 截止时刻=截止时刻)
            if 任务对象.状态 in _终态:
                return True, f"任务已到终态 {任务对象.状态}"
            剩余秒 = 截止时刻 - time.monotonic()
            if 剩余秒 <= 0:
                return False, "等待已到硬截止，任务仍未进入终态"
            self.监视唤醒事件.wait(timeout=min(0.02, 剩余秒))

    def _拒绝等待队列(self, 原因: str) -> None:
        """把等待队列里的任务统一拒绝成「已取消」终态，并**无论成败都清空队列**。

        「先改共享状态再抛」禁止项③：`_完成失败` 要落盘（可抛 `OSError`）。旧实现把
        `clear()/notify_all()` 放在循环之后：只要有一条落盘失败，整队清空就被跳过，
        而 `已停止` 已置位 —— 死条目永久留在队列里，且没有任何调用方还能再清理它
        （只有 `停止`/`排空` 会整队清空，而它们已经走过去了）。现在逐条兜住异常
        （一条落盘失败不再连累其余任务拿不到终态），清空与唤醒放进 `finally`，
        最后把第一个异常如实上抛：**不吞掉落盘失败，也不留残留**。
        """
        首个异常: BaseException | None = None
        try:
            for 任务对象 in list(self.等待队列):
                try:
                    self._完成失败(任务对象, 任务状态_已取消, "已取消", 原因)
                except BaseException as 错误:  # noqa: BLE001 —— 逐条兜底，最后统一上抛
                    if 首个异常 is None:
                        首个异常 = 错误
        finally:
            self.等待队列.clear()
            self.提交条件.notify_all()
        if 首个异常 is not None:
            raise 首个异常

    def _停止监视(self, 截止时刻: float) -> bool:
        self.监视停止事件.set()
        self.监视唤醒事件.set()
        线程 = self.监视线程
        if 线程 is None or not 线程.is_alive():
            return True
        剩余秒 = max(0.0, 截止时刻 - time.monotonic())
        线程.join(timeout=剩余秒)
        return not 线程.is_alive()

    def 排空(self, *, 超时秒: float | None = None) -> tuple[bool, str]:
        """停止接收新任务并等待现有任务自然完成；到硬截止即失败且保留账本。"""
        等待秒 = self.排空截止秒 if 超时秒 is None else max(0.0, float(超时秒))
        截止时刻 = time.monotonic() + 等待秒
        with self.锁:
            self.已停止 = True
            self._拒绝等待队列("进程池排空，排队任务未执行")
        while True:
            with self.锁:
                活动快照 = list(self.活动任务表.values())
            for 任务对象 in 活动快照:
                self._轮询任务(任务对象, 截止时刻=截止时刻)
            with self.锁:
                已排空 = not self.活动任务表
            if 已排空:
                if self._停止监视(截止时刻):
                    return True, "任务进程池已在硬截止内排空"
                return False, "任务已排空但监视线程未在硬截止内退出"
            剩余秒 = 截止时刻 - time.monotonic()
            if 剩余秒 <= 0:
                return False, "排空已到硬截止，未收敛任务及资源账本已保留"
            self.监视唤醒事件.wait(timeout=min(0.02, 剩余秒))

    def 停止(self, *, 超时秒: float | None = None) -> tuple[bool, str]:
        """关闭进程池；所有任务共用一个硬截止，失败保留活动账本供重试。

        「先改共享状态再抛」禁止项④ —— **关闭路径不得被单条落盘失败截断**：
        `已停止` 一置位，本方法就是全部活动任务**唯一**的回收入口（`提交` 从此一律
        拒绝，`_监视循环` 只推进状态、不做强制终止），中途抛出留下的就是「半停止」：
        一部分任务停在内存「取消中」而工作进程照样在跑，后续任务连状态都没改，
        没有任何调用方能再回收它们。因此三段都不得把异常直接放走：

        - `_拒绝等待队列` 自身已保证清空队列与唤醒，它的落盘异常只记账不打断关闭；
        - 标记循环里落盘失败的任务**内存状态回滚成原值**（内存与磁盘始终一致，
          与 `取消` 的顺序约定同源），其余任务照常标记；
        - 终止循环**逐条兜住**（`_完成失败` 尾部同样要落盘）：一条落盘失败不再让
          排在后面的活动任务逃过终止。

        三段走完后第一个异常**如实上抛**（类型与上抛行为与修前一致，不吞不换）：
        此时池已按完整关闭路径收敛，重试 `停止` 即可继续收敛未收敛的那部分。
        """
        等待秒 = self.关闭截止秒 if 超时秒 is None else max(0.0, float(超时秒))
        截止时刻 = time.monotonic() + 等待秒
        首个异常: BaseException | None = None
        with self.锁:
            self.已停止 = True
            try:
                self._拒绝等待队列("进程池关闭，排队任务未执行")
            except BaseException as 错误:  # noqa: BLE001 —— 记账后继续关闭
                首个异常 = 错误
            活动快照 = list(self.活动任务表.values())
            for 任务对象 in 活动快照:
                if 任务对象.状态 in _终态:
                    continue
                原状态 = 任务对象.状态
                任务对象.状态 = 任务状态_取消中
                if 任务对象.取消事件 is not None:
                    任务对象.取消事件.set()
                try:
                    self._持久化(任务对象)
                except BaseException as 错误:  # noqa: BLE001 —— 记账后继续标记其余任务
                    任务对象.状态 = 原状态
                    if 首个异常 is None:
                        首个异常 = 错误
            if 等待秒 <= 0 and 活动快照:
                if 首个异常 is not None:
                    raise 首个异常
                return False, "关闭请求已发出，工作进程尚未确认退出，活动账本已保留供重试"
            for 任务对象 in 活动快照:
                if 任务对象.状态 in _终态:
                    continue
                try:
                    任务对象.待发布状态 = 任务状态_已取消
                    任务对象.待发布错误码 = "已取消"
                    任务对象.待发布错误说明 = "进程池关闭，任务已终止"
                    if self._终止工作器(任务对象, 截止时刻):
                        self._完成失败(
                            任务对象, 任务状态_已取消, "已取消", "进程池关闭，任务已终止")
                    else:
                        任务对象.错误码 = "资源未收敛"
                        任务对象.错误说明 = "关闭请求已发出但完整进程组未确认退出，活动账本已保留供重试"
                        self._持久化(任务对象)
                except BaseException as 错误:  # noqa: BLE001 —— 记账后继续终止其余任务
                    if 首个异常 is None:
                        首个异常 = 错误
            已收敛 = not self.活动任务表
        if not 已收敛:
            if 首个异常 is not None:
                raise 首个异常
            return False, "关闭已到硬截止，未收敛任务及资源账本已保留供重试"
        监视已停 = self._停止监视(截止时刻)
        if 首个异常 is not None:
            # 完整关闭路径（含监视停止）已走完，异常仍如实上抛：不吞掉落盘失败
            raise 首个异常
        if not 监视已停:
            return False, "工作进程已退出，但监视线程未在关闭硬截止内退出"
        return True, "任务进程池已关闭，完整工作进程组均已确认退出"

    def 关闭全部(self, *, 超时秒: float | None = None) -> tuple[bool, str]:
        return self.停止(超时秒=超时秒)
