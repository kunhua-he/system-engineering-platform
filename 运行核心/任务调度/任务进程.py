"""独立任务进程：每个任务使用独立进程，支持真实超时、取消和回收。"""

from __future__ import annotations

import json
import multiprocessing
import os
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
        self.接收连接: Any = None
        self.取消事件: Any = None
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
    """每任务独立进程；fork 继承已注册函数，连接中只传 JSON 字节。"""

    def __init__(self, *, 工作器路径: Path | None = None, 存储目录: Path | None = None,
                 解释器: str | None = None) -> None:
        self.工作器路径 = 工作器路径
        self.解释器 = 解释器
        self.存储目录 = 存储目录 or Path(tempfile.gettempdir()) / "系统级支持库_任务进程"
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.任务表: dict[str, 独立任务] = {}
        self.执行函数表: dict[str, Callable] = {}
        self.锁 = threading.RLock()
        try:
            self.进程上下文 = multiprocessing.get_context("fork")
        except ValueError as 错误:
            raise RuntimeError("当前平台不支持可继承中文能力注册表的独立任务进程") from 错误

    def 注册执行函数(self, 能力id: str, 函数: Callable) -> None:
        with self.锁:
            self.执行函数表[能力id] = 函数

    def 提交(self, *, 能力id: str, 参数: dict | None = None, 项目id: str = "",
             用户id: str = "", 请求id: str = "", 超时秒: float = 10.0) -> 独立任务:
        任务对象 = 独立任务(能力id=能力id, 项目id=项目id, 用户id=用户id,
                         请求id=请求id, 超时秒=超时秒)
        with self.锁:
            self.任务表[任务对象.任务id] = 任务对象
            函数 = self.执行函数表.get(能力id)
            if 函数 is None:
                self._完成失败(任务对象, 任务状态_失败, "能力不存在", f"任务能力未注册: {能力id}")
                return 任务对象
            接收连接, 发送连接 = self.进程上下文.Pipe(duplex=False)
            取消事件 = self.进程上下文.Event()
            请求 = {"任务id": 任务对象.任务id, "能力id": 能力id, "参数": 参数 or {}}
            进程 = self.进程上下文.Process(
                target=执行单次任务,
                args=(发送连接, 函数, 请求, 取消事件),
                name=f"系统级任务-{任务对象.任务id}",
                daemon=True,
            )
            任务对象.接收连接 = 接收连接
            任务对象.取消事件 = 取消事件
            任务对象.进程 = 进程
            任务对象.状态 = 任务状态_运行中
            进程.start()
            发送连接.close()
            self._持久化(任务对象)
        threading.Thread(target=self._监视任务, args=(任务对象,), daemon=True).start()
        return 任务对象

    def _监视任务(self, 任务对象: 独立任务) -> None:
        截止 = time.monotonic() + 任务对象.超时秒
        响应: dict[str, Any] | None = None
        while time.monotonic() < 截止:
            with self.锁:
                if 任务对象.状态 in _终态:
                    return
                if 任务对象.状态 == 任务状态_取消中:
                    self._终止工作器(任务对象)
                    self._完成失败(任务对象, 任务状态_已取消, "已取消", "任务已取消")
                    return
                进程 = 任务对象.进程
                连接 = 任务对象.接收连接
            if 连接 is not None and 连接.poll(0.02):
                try:
                    响应 = json.loads(连接.recv_bytes().decode("utf-8"))
                except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError):
                    响应 = None
                break
            if 进程 is None or (not 进程.is_alive() and not (连接 and 连接.poll())):
                break
        with self.锁:
            if 任务对象.状态 in _终态:
                return
            if 任务对象.状态 == 任务状态_取消中:
                self._终止工作器(任务对象)
                self._完成失败(任务对象, 任务状态_已取消, "已取消", "任务已取消")
            elif 响应 is None and time.monotonic() >= 截止:
                self._终止工作器(任务对象)
                self._完成失败(任务对象, 任务状态_超时, "超时", f"任务执行超过 {任务对象.超时秒} 秒")
            elif 响应 is None:
                退出码 = 任务对象.进程.exitcode if 任务对象.进程 else None
                self._终止工作器(任务对象)
                self._完成失败(任务对象, 任务状态_崩溃, "崩溃", f"工作进程异常退出（退出码 {退出码}）")
            elif 响应.get("取消"):
                self._终止工作器(任务对象)
                self._完成失败(任务对象, 任务状态_已取消, "已取消", "任务已取消")
            elif 响应.get("成功", False):
                任务对象.结果 = 响应.get("值")
                self._完成(任务对象, 任务状态_成功)
            else:
                self._完成失败(任务对象, 任务状态_失败,
                              响应.get("错误码", "内部错误"), 响应.get("错误说明", "任务执行失败"))

    def _完成失败(self, 任务对象: 独立任务, 状态: str, 错误码: str, 错误说明: str) -> None:
        任务对象.错误码 = 错误码
        任务对象.错误说明 = 错误说明
        self._完成(任务对象, 状态)

    def _完成(self, 任务对象: 独立任务, 最终状态: str) -> None:
        # 终态是对外承诺：先确认工作器退出并释放通信资源，再发布终态。
        self._回收工作器(任务对象)
        任务对象.状态 = 最终状态
        任务对象.进度 = 1.0
        任务对象.完成时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        self._持久化(任务对象)

    def _终止工作器(self, 任务对象: 独立任务) -> None:
        if 任务对象.取消事件 is not None:
            任务对象.取消事件.set()
        进程 = 任务对象.进程
        if 进程 is not None and 进程.is_alive():
            进程.terminate()
            进程.join(timeout=0.5)
            if 进程.is_alive() and hasattr(进程, "kill"):
                进程.kill()
                进程.join(timeout=0.5)
        self._回收工作器(任务对象)

    def _回收工作器(self, 任务对象: 独立任务) -> None:
        进程 = 任务对象.进程
        if 进程 is not None:
            if 进程.is_alive():
                进程.join(timeout=0.5)
            # 工作器已经交付结果却未自行退出时，不能把活进程留给调用者。
            if 进程.is_alive():
                进程.terminate()
                进程.join(timeout=0.5)
            if 进程.is_alive() and hasattr(进程, "kill"):
                进程.kill()
                进程.join(timeout=0.5)
            if not 进程.is_alive():
                进程.join(timeout=0)
        if 任务对象.接收连接 is not None:
            try:
                任务对象.接收连接.close()
            except OSError:
                pass
            任务对象.接收连接 = None

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

    def 取消(self, 任务id: str) -> tuple[bool, str]:
        with self.锁:
            任务对象 = self.查询(任务id)
            if 任务对象.状态 in _终态:
                return True, f"任务已处于终态 {任务对象.状态}（取消幂等）"
            任务对象.状态 = 任务状态_取消中
            if 任务对象.取消事件 is not None:
                任务对象.取消事件.set()
            self._终止工作器(任务对象)
            self._完成失败(任务对象, 任务状态_已取消, "已取消", "任务已取消并终止工作进程")
            return True, "任务已取消，工作进程已终止"

    def 查询诊断(self, 任务id: str) -> dict[str, Any]:
        任务对象 = self.查询(任务id)
        return {"任务id": 任务id, "状态": 任务对象.状态, "错误码": 任务对象.错误码,
                "错误说明": 任务对象.错误说明, "能力id": 任务对象.能力id}

    def 活动进程数(self) -> int:
        with self.锁:
            return sum(1 for 任务对象 in self.任务表.values()
                       if 任务对象.进程 is not None and 任务对象.进程.is_alive())

    def 关闭全部(self) -> None:
        with self.锁:
            for 任务对象 in list(self.任务表.values()):
                if 任务对象.状态 not in _终态:
                    任务对象.状态 = 任务状态_取消中
                    self._终止工作器(任务对象)
                    self._完成失败(任务对象, 任务状态_已取消, "已取消", "进程池关闭，任务已终止")
