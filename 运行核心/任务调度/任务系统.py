"""统一异步任务系统：以独立任务进程执行并原子持久化任务状态。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from 运行核心.任务调度.任务进程 import 任务进程池

状态_等待中 = "等待中"
状态_运行中 = "运行中"
状态_成功 = "成功"
状态_失败 = "失败"
状态_取消中 = "取消中"
状态_已取消 = "已取消"
状态_超时 = "超时"
状态_崩溃 = "崩溃"

_终态 = {状态_成功, 状态_失败, 状态_已取消, 状态_超时, 状态_崩溃}


@dataclass
class 任务:
    任务id: str
    能力id: str
    状态: str = 状态_等待中
    进度: float = 0.0
    结果: Any = None
    错误码: str = ""
    错误说明: str = ""
    创建时间: str = ""
    完成时间: str = ""
    请求id: str = ""
    项目id: str = ""
    用户id: str = ""
    取消标记: bool = False

    def 转字典(self) -> dict[str, Any]:
        return {
            "任务id": self.任务id, "能力id": self.能力id, "状态": self.状态,
            "进度": self.进度, "结果": self.结果, "错误码": self.错误码,
            "错误说明": self.错误说明, "创建时间": self.创建时间,
            "完成时间": self.完成时间, "请求id": self.请求id,
            "项目id": self.项目id, "用户id": self.用户id, "取消标记": self.取消标记,
        }


class 任务系统:
    """任务门面：独立进程执行、并发安全查询、原子快照持久化。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        self.存储目录 = 存储目录 or Path(self.默认存储目录())
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.任务表: dict[str, 任务] = {}
        self.执行函数表: dict[str, Callable] = {}
        self.锁 = threading.RLock()
        self.进程池 = 任务进程池(存储目录=self.存储目录 / "进程任务")
        self.加载()

    @staticmethod
    def 默认存储目录() -> str:
        return os.environ.get("系统库任务目录", str(Path(tempfile.gettempdir()) / "系统级支持库_任务"))

    def 加载(self) -> None:
        文件 = self.存储目录 / "任务.jsonl"
        if not 文件.is_file():
            return
        with self.锁:
            for 行 in 文件.read_text(encoding="utf-8").splitlines():
                try:
                    数据 = json.loads(行)
                    任务对象 = 任务(**{键: 值 for 键, 值 in 数据.items() if 键 in 任务.__dataclass_fields__})
                    if 任务对象.状态 in (状态_等待中, 状态_运行中, 状态_取消中):
                        任务对象.状态 = 状态_崩溃
                        任务对象.错误码 = "崩溃"
                        任务对象.错误说明 = "进程重启，任务未完成"
                        任务对象.完成时间 = time.strftime("%Y-%m-%d %H:%M:%S")
                    self.任务表[任务对象.任务id] = 任务对象
                except (json.JSONDecodeError, TypeError):
                    continue
            self._保存已加锁()

    def 保存(self) -> None:
        with self.锁:
            self._保存已加锁()

    def _保存已加锁(self) -> None:
        # 调用者销毁临时存储后，后台同步线程必须结束，不能重建已清理目录。
        if not self.存储目录.is_dir():
            return
        目标 = self.存储目录 / "任务.jsonl"
        临时路径: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.存储目录,
                                             prefix=".任务.", suffix=".tmp", delete=False) as 输出:
                临时路径 = 输出.name
                for 任务对象 in self.任务表.values():
                    输出.write(json.dumps(任务对象.转字典(), ensure_ascii=False) + "\n")
                输出.flush()
                os.fsync(输出.fileno())
            os.replace(临时路径, 目标)
        finally:
            if 临时路径 and os.path.exists(临时路径):
                os.unlink(临时路径)

    def 注册执行函数(self, 能力id: str, 函数: Callable) -> None:
        with self.锁:
            self.执行函数表[能力id] = 函数
            self.进程池.注册执行函数(能力id, 函数)

    def 提交(self, *, 能力id: str, 参数: dict | None = None, 请求id: str = "",
             项目id: str = "", 用户id: str = "", 超时秒: float = 5.0) -> 任务:
        独立对象 = self.进程池.提交(
            能力id=能力id, 参数=参数, 请求id=请求id,
            项目id=项目id, 用户id=用户id, 超时秒=超时秒,
        )
        任务对象 = 任务(
            任务id=独立对象.任务id, 能力id=能力id, 状态=独立对象.状态,
            创建时间=独立对象.创建时间, 请求id=请求id, 项目id=项目id, 用户id=用户id,
        )
        with self.锁:
            self.任务表[任务对象.任务id] = 任务对象
            self._保存已加锁()
        threading.Thread(target=self._同步任务, args=(任务对象.任务id,), daemon=True).start()
        return 任务对象

    def _同步任务(self, 任务id: str) -> None:
        while True:
            独立对象 = self.进程池.查询(任务id)
            with self.锁:
                任务对象 = self.任务表[任务id]
                self._应用独立状态已加锁(任务对象, 独立对象)
                self._保存已加锁()
                if 任务对象.状态 in _终态:
                    return
            time.sleep(0.01)

    @staticmethod
    def _应用独立状态已加锁(任务对象: 任务, 独立对象: Any) -> None:
        任务对象.状态 = 独立对象.状态
        任务对象.进度 = 独立对象.进度
        任务对象.结果 = 独立对象.结果
        任务对象.错误码 = 独立对象.错误码
        任务对象.错误说明 = 独立对象.错误说明
        任务对象.完成时间 = 独立对象.完成时间
        任务对象.取消标记 = 独立对象.状态 in (状态_取消中, 状态_已取消)

    def 查询(self, 任务id: str) -> 任务:
        # 查询直接取独立进程权威状态，不能依赖后台同步线程的调度时机。
        独立对象 = self.进程池.查询(任务id)
        with self.锁:
            任务对象 = self.任务表.get(任务id)
            if 任务对象 is None:
                raise KeyError(f"未知任务id: {任务id}")
            self._应用独立状态已加锁(任务对象, 独立对象)
            if 任务对象.状态 in _终态:
                self._保存已加锁()
            return 任务对象

    def 查询状态(self, 任务id: str) -> str:
        return self.查询(任务id).状态

    def 查询进度(self, 任务id: str) -> float:
        return self.查询(任务id).进度

    def 取消(self, 任务id: str) -> tuple[bool, str]:
        with self.锁:
            任务对象 = self.任务表.get(任务id)
            if 任务对象 is None:
                return False, f"未知任务id: {任务id}"
            if 任务对象.状态 in _终态:
                return True, f"任务已处于终态 {任务对象.状态}（取消幂等）"
            任务对象.取消标记 = True
            任务对象.状态 = 状态_取消中
            self._保存已加锁()
        成功, 消息 = self.进程池.取消(任务id)
        独立对象 = self.进程池.查询(任务id)
        with self.锁:
            任务对象.状态 = 独立对象.状态
            任务对象.错误码 = 独立对象.错误码
            任务对象.错误说明 = 独立对象.错误说明
            任务对象.完成时间 = 独立对象.完成时间
            任务对象.进度 = 独立对象.进度
            self._保存已加锁()
        return 成功, 消息

    def 查询诊断(self, 任务id: str) -> dict[str, Any]:
        任务对象 = self.查询(任务id)
        return {"任务id": 任务对象.任务id, "状态": 任务对象.状态,
                "错误码": 任务对象.错误码, "错误说明": 任务对象.错误说明,
                "能力id": 任务对象.能力id, "请求id": 任务对象.请求id}

    def 更新进度(self, 任务id: str, 进度: float) -> None:
        with self.锁:
            任务对象 = self.任务表.get(任务id)
            if 任务对象 is not None:
                任务对象.进度 = min(1.0, max(0.0, float(进度)))
                self._保存已加锁()

    def 活动任务数(self) -> int:
        return self.进程池.活动进程数()

    def 关闭全部(self) -> None:
        self.进程池.关闭全部()
