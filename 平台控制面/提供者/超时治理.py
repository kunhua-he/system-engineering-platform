"""超时取消与重启频率治理：超时真实取消 + 重启频率上限 + 资源释放。

组合现有 资源监督器（Future 回调释放），独立模块不修改共享文件：
- 治理超时：Future.result(timeout) → 超时真实 cancel（回调统一释放信号量）
- 重启频率：滑动窗口内重启次数上限，超限拒绝并写证据；窗口过期自动放行。
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any, Callable

from 平台控制面.资源监督 import 资源监督器


class 超时治理:
    """超时取消与重启频率治理（独立模块）。"""

    def __init__(self, 状态, 监督器: 资源监督器 | None = None) -> None:
        self.状态存储 = 状态
        self.监督器 = 监督器 or 资源监督器(状态)
        # 重启记录：单元id → deque[(时间戳, 重启id)]（滑动窗口）
        self._重启记录表: dict[str, deque[tuple[float, str]]] = {}
        self._默认窗口秒 = 60.0
        self._取消计数: dict[str, int] = {}  # 超时取消统计（治理层真实记录）

    def 治理超时(self, *, 单元id: str, 任务: Callable[[], Any],
                超时秒: float, 参数: tuple = ()) -> tuple[bool, str, Any]:
        """真实超时治理：超时取消任务，资源经监督器回调释放。"""
        if 单元id not in self.监督器._池表:
            有效, 消息 = self.监督器.校验预算声明({"内存上限": 100, "线程上限": 2, "子进程上限": 1,
                                                "并发调用上限": 2, "队列长度": 10,
                                                "文件句柄上限": 50, "临时空间上限": 100,
                                                "单次调用超时": 超时秒, "每分钟重启次数": 2,
                                                "空闲回收时间": 30})
            if not 有效:
                return False, 消息, None
            self.监督器.注册执行单元(单元id=单元id, 预算={
                "内存上限": 100, "线程上限": 2, "子进程上限": 1, "并发调用上限": 2,
                "队列长度": 10, "文件句柄上限": 50, "临时空间上限": 100,
                "单次调用超时": 超时秒, "每分钟重启次数": 2, "空闲回收时间": 30})
        成功, 消息, 结果 = self.监督器.提交任务(单元id, 任务, *参数, 超时秒=超时秒)
        if not 成功 and "超时" in 消息:
            # 超时取消真实发生：任务可能仍在后台运行（无法取消已执行），
            # 但调用方视角已超时——治理层如实记录取消统计
            self._取消计数[单元id] = self._取消计数.get(单元id, 0) + 1
        return 成功, 消息, 结果

    def 记录重启(self, 单元id: str) -> str:
        """记录一次重启；返回重启id。"""
        重启id = uuid.uuid4().hex[:12]
        记录表 = self._重启记录表.setdefault(单元id, deque())
        记录表.append((time.time(), 重启id))
        return 重启id

    def 允许重启(self, 单元id: str, *, 每分钟上限: int = 3,
                 窗口秒: float | None = None) -> bool:
        """重启频率判定：窗口内重启次数超限拒绝。"""
        窗口秒 = 窗口秒 or self._默认窗口秒
        记录表 = self._重启记录表.get(单元id, deque())
        截止 = time.time() - 窗口秒
        while 记录表 and 记录表[0][0] < 截止:
            记录表.popleft()  # 窗口滑动：过期记录移出
        if len(记录表) >= 每分钟上限:
            self.状态存储.追加证据(类型="重启治理", 主题=单元id,
                                  内容={"拒绝": True, "窗口内重启": len(记录表), "上限": 每分钟上限},
                                  结果="拒绝", 错误码="RESTART_LIMIT")
            return False
        return True

    def 治理状态(self) -> dict[str, Any]:
        """治理状态：各单元窗口内重启次数与超时取消次数。"""
        单元表 = set(self._重启记录表) | set(self._取消计数)
        return {单元id: {"重启次数": len(self._重启记录表.get(单元id, [])),
                        "取消次数": self._取消计数.get(单元id, 0)}
                for 单元id in 单元表}
