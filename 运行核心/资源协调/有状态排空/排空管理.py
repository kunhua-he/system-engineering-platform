"""有状态排空：并发安全计数、真实终止回调与资源归零验证。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class 排空结果:
    成功: bool = False
    步骤列表: list[str] = field(default_factory=list)
    未完成任务: list[str] = field(default_factory=list)
    强制终止: bool = False
    诊断记录: str = ""


class 排空管理器:
    """停止新请求后等待活动资源归零，超时只在真实回收后成功。"""

    def __init__(self, 排空超时秒: float = 3.0, 允许强制终止: bool = True) -> None:
        self.排空超时秒 = max(0.0, float(排空超时秒))
        self.允许强制终止 = 允许强制终止
        self.活动请求数 = 0
        self.活动任务数 = 0
        self.活动连接数 = 0
        self.活动句柄数 = 0
        self.锁 = threading.RLock()
        self.条件 = threading.Condition(self.锁)
        self.停止接收新请求 = False
        self.强制终止器: list[tuple[str, Callable[[], Any]]] = []
        self.诊断历史: list[str] = []

    def 注册强制终止器(self, 名称: str, 终止函数: Callable[[], Any]) -> None:
        """注册真正释放任务、连接或句柄的终止函数。"""
        with self.锁:
            self.强制终止器.append((名称, 终止函数))

    def 活动总数(self) -> int:
        with self.锁:
            return self._活动总数已加锁()

    def _活动总数已加锁(self) -> int:
        return self.活动请求数 + self.活动任务数 + self.活动连接数 + self.活动句柄数

    def _变化(self) -> None:
        self.条件.notify_all()

    def 开始请求(self) -> bool:
        with self.条件:
            if self.停止接收新请求:
                return False
            self.活动请求数 += 1
            self._变化()
            return True

    def 结束请求(self) -> None:
        with self.条件:
            self.活动请求数 = max(0, self.活动请求数 - 1)
            self._变化()

    def 开始任务(self) -> bool:
        with self.条件:
            if self.停止接收新请求:
                return False
            self.活动任务数 += 1
            self._变化()
            return True

    def 结束任务(self) -> None:
        with self.条件:
            self.活动任务数 = max(0, self.活动任务数 - 1)
            self._变化()

    def 记录连接(self, 数量: int = 1) -> bool:
        with self.条件:
            if 数量 < 0 or self.停止接收新请求:
                return False
            self.活动连接数 += 数量
            self._变化()
            return True

    def 释放连接(self, 数量: int = 1) -> None:
        with self.条件:
            self.活动连接数 = max(0, self.活动连接数 - max(0, 数量))
            self._变化()

    def 记录句柄(self, 数量: int = 1) -> bool:
        with self.条件:
            if 数量 < 0 or self.停止接收新请求:
                return False
            self.活动句柄数 += 数量
            self._变化()
            return True

    def 释放句柄(self, 数量: int = 1) -> None:
        with self.条件:
            self.活动句柄数 = max(0, self.活动句柄数 - max(0, 数量))
            self._变化()

    def _未完成列表已加锁(self) -> list[str]:
        return [
            f"活动请求 {self.活动请求数}", f"活动任务 {self.活动任务数}",
            f"活动连接 {self.活动连接数}", f"活动句柄 {self.活动句柄数}",
        ]

    def _执行强制终止(self, 结果: 排空结果) -> None:
        结果.强制终止 = True
        错误列表: list[str] = []
        with self.锁:
            终止器列表 = list(self.强制终止器)
        for 名称, 终止函数 in 终止器列表:
            try:
                终止函数()
                结果.步骤列表.append(f"已执行强制终止: {名称}")
            except Exception as 错误:  # noqa: BLE001 - 必须继续执行其余资源终止器
                错误列表.append(f"{名称}: {错误}")
        验证截止 = time.monotonic() + min(1.0, max(0.1, self.排空超时秒))
        with self.条件:
            while self._活动总数已加锁() > 0 and time.monotonic() < 验证截止:
                self.条件.wait(timeout=min(0.05, max(0.0, 验证截止 - time.monotonic())))
            剩余 = self._活动总数已加锁()
            结果.未完成任务 = self._未完成列表已加锁() if 剩余 else []
        if 剩余 == 0 and not 错误列表:
            结果.成功 = True
            结果.步骤列表.append("强制终止后资源已验证归零")
            结果.诊断记录 += "；强制终止完成，资源计数已归零"
        else:
            结果.成功 = False
            详情 = ", ".join(结果.未完成任务)
            错误详情 = f"；终止错误: {'; '.join(错误列表)}" if 错误列表 else ""
            结果.诊断记录 += f"；强制终止后资源未归零: {详情}{错误详情}"

    def 排空(self) -> 排空结果:
        结果 = 排空结果()
        with self.条件:
            self.停止接收新请求 = True
            结果.步骤列表.append("停止接收新请求")
            截止 = time.monotonic() + self.排空超时秒
            while self._活动总数已加锁() > 0:
                剩余秒 = 截止 - time.monotonic()
                if 剩余秒 <= 0:
                    结果.未完成任务 = self._未完成列表已加锁()
                    结果.诊断记录 = f"排空超时（> {self.排空超时秒} 秒）: {', '.join(结果.未完成任务)}"
                    self.诊断历史.append(结果.诊断记录)
                    break
                self.条件.wait(timeout=min(0.05, 剩余秒))
            else:
                结果.步骤列表.extend(["活动请求归零", "任务完成或取消", "连接已关闭", "资源句柄已释放"])
                结果.成功 = True
                return 结果
        if self.允许强制终止:
            self._执行强制终止(结果)
        else:
            结果.成功 = False
        with self.锁:
            if 结果.诊断记录 and (not self.诊断历史 or self.诊断历史[-1] != 结果.诊断记录):
                self.诊断历史.append(结果.诊断记录)
        return 结果

    def 状态快照(self) -> dict[str, Any]:
        with self.锁:
            return {
                "活动请求数": self.活动请求数, "活动任务数": self.活动任务数,
                "活动连接数": self.活动连接数, "活动句柄数": self.活动句柄数,
                "停止接收新请求": self.停止接收新请求,
                "排空超时秒": self.排空超时秒,
            }
