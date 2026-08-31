"""独立任务进程：每个任务使用独立进程，支持真实超时、取消和回收。"""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

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


class 资源繁忙错误(Exception):
    """提交任务超过进程池有界容量时的统一资源繁忙错误，区分"忙"与"失败"。"""

    def __init__(self, 消息: str = "") -> None:
        super().__init__(消息 or "任务进程池资源繁忙，拒绝提交新任务")


def _执行任务进程入口(进程组就绪事件: Any, 发送连接: Any, 函数: Callable,
                    请求: dict[str, Any], 取消事件: Any) -> None:
    """先建立独立会话/进程组，再允许能力启动任何后代进程。"""
    if hasattr(os, "setsid"):
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
        try:
            self.进程上下文 = multiprocessing.get_context("fork")
        except ValueError as 错误:
            raise RuntimeError("当前平台不支持可继承中文能力注册表的独立任务进程") from 错误

    def 注册执行函数(self, 能力id: str, 函数: Callable) -> None:
        with self.锁:
            self.执行函数表[能力id] = 函数

    def 提交(self, *, 能力id: str, 参数: dict | None = None, 项目id: str = "",
             用户id: str = "", 请求id: str = "", 超时秒: float = 10.0) -> 独立任务:
        """有界提交：活动进程数达到上限时排队等待，超容量或超截止返回资源繁忙错误。"""
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
            if 任务对象 in self.等待队列:
                self.等待队列.remove(任务对象)
            接收连接, 发送连接 = self.进程上下文.Pipe(duplex=False)
            取消事件 = self.进程上下文.Event()
            进程组就绪事件 = self.进程上下文.Event()
            请求 = {"任务id": 任务对象.任务id, "能力id": 能力id, "参数": 参数 or {}}
            进程 = self.进程上下文.Process(
                target=_执行任务进程入口,
                args=(进程组就绪事件, 发送连接, 函数, 请求, 取消事件),
                name=f"系统级任务-{任务对象.任务id}",
                daemon=True,
            )
            任务对象.接收连接 = 接收连接
            任务对象.取消事件 = 取消事件
            任务对象.进程组就绪事件 = 进程组就绪事件
            任务对象.进程 = 进程
            任务对象.截止时刻 = time.monotonic() + 任务对象.超时秒
            任务对象.状态 = 任务状态_运行中
            进程.start()
            任务对象.进程组id = 进程.pid
            发送连接.close()
            self.任务表[任务对象.任务id] = 任务对象
            self.活动任务表[任务对象.任务id] = 任务对象
            self._持久化(任务对象)
            self.提交条件.notify_all()
        self._确保监视线程()
        return 任务对象

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
        """单次轮询：推进状态，但任何资源回收都不得越过调用方给定的硬截止。"""
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
        if 连接 is not None and 连接.poll():
            try:
                响应 = json.loads(连接.recv_bytes().decode("utf-8"))
            except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError):
                响应 = None
            with self.锁:
                if 任务对象.状态 in _终态:
                    return
                if 响应 is None:
                    退出码 = 进程.exitcode if 进程 is not None else None
                    self._完成失败(
                        任务对象, 任务状态_崩溃, "崩溃",
                        f"工作进程异常退出（退出码 {退出码}）", 截止时刻=截止时刻)
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
            return
        with self.锁:
            if 任务对象.状态 in _终态:
                return
            if time.monotonic() >= 任务对象.截止时刻:
                self._完成失败(
                    任务对象, 任务状态_超时, "超时",
                    f"任务执行超过 {任务对象.超时秒} 秒", 截止时刻=截止时刻)
            elif 进程 is not None and not 进程.is_alive():
                退出码 = 进程.exitcode
                self._完成失败(
                    任务对象, 任务状态_崩溃, "崩溃",
                    f"工作进程异常退出（退出码 {退出码}）", 截止时刻=截止时刻)

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
        if not 进程组id or not hasattr(os, "killpg"):
            return False
        try:
            os.killpg(进程组id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _进程组已就绪(self, 任务对象: 独立任务) -> bool:
        事件 = 任务对象.进程组就绪事件
        return bool(事件 is not None and 事件.is_set() and hasattr(os, "killpg"))

    def _工作器存活(self, 任务对象: 独立任务) -> bool:
        if self._进程组已就绪(任务对象):
            return self._进程组存活(任务对象.进程组id)
        进程 = 任务对象.进程
        return bool(进程 is not None and 进程.is_alive())

    def _发送工作器信号(self, 任务对象: 独立任务, 信号值: int) -> None:
        进程 = 任务对象.进程
        if self._进程组已就绪(任务对象) and 任务对象.进程组id:
            # 绝不向主进程所在组发送信号；就绪事件只在子进程 setsid 后置位。
            if 任务对象.进程组id != os.getpgrp():
                try:
                    os.killpg(任务对象.进程组id, 信号值)
                except (ProcessLookupError, PermissionError, OSError):
                    # 进程组可能在存活检查与发信号之间退出；EPERM 也不能
                    # 被解释成信号已送达，后续仍以存活复查决定是否收敛。
                    pass
                return
        if 进程 is None or not 进程.is_alive():
            return
        try:
            if 信号值 == signal.SIGKILL and hasattr(进程, "kill"):
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
        self._发送工作器信号(任务对象, signal.SIGTERM)
        优雅截止 = min(截止时刻, time.monotonic() + min(0.2, 剩余秒 * 0.4))
        if not self._等待工作器退出(任务对象, 优雅截止):
            self._发送工作器信号(任务对象, signal.SIGKILL)
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
            任务对象.状态 = 任务状态_取消中
            if 任务对象.取消事件 is not None:
                任务对象.取消事件.set()
            等待秒 = self.终止截止秒 if 等待截止秒 is None else max(0.0, float(等待截止秒))
            self._持久化(任务对象)
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
        for 任务对象 in list(self.等待队列):
            self._完成失败(任务对象, 任务状态_已取消, "已取消", 原因)
        self.等待队列.clear()
        self.提交条件.notify_all()

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
        """关闭进程池；所有任务共用一个硬截止，失败保留活动账本供重试。"""
        等待秒 = self.关闭截止秒 if 超时秒 is None else max(0.0, float(超时秒))
        截止时刻 = time.monotonic() + 等待秒
        with self.锁:
            self.已停止 = True
            self._拒绝等待队列("进程池关闭，排队任务未执行")
            活动快照 = list(self.活动任务表.values())
            for 任务对象 in 活动快照:
                if 任务对象.状态 not in _终态:
                    任务对象.状态 = 任务状态_取消中
                    if 任务对象.取消事件 is not None:
                        任务对象.取消事件.set()
                    self._持久化(任务对象)
            if 等待秒 <= 0 and 活动快照:
                return False, "关闭请求已发出，工作进程尚未确认退出，活动账本已保留供重试"
            for 任务对象 in 活动快照:
                if 任务对象.状态 in _终态:
                    continue
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
            已收敛 = not self.活动任务表
        if not 已收敛:
            return False, "关闭已到硬截止，未收敛任务及资源账本已保留供重试"
        if not self._停止监视(截止时刻):
            return False, "工作进程已退出，但监视线程未在关闭硬截止内退出"
        return True, "任务进程池已关闭，完整工作进程组均已确认退出"

    def 关闭全部(self, *, 超时秒: float | None = None) -> tuple[bool, str]:
        return self.停止(超时秒=超时秒)
