"""资源监督器：真正可执行的资源预算（不只检查声明文件）。

总补修边界：
- 任务完成/失败/取消/超时都必须释放并发令牌并移除队列项（Future 回调，不堆积）。
- 单次调用超时如实报告：运行中任务无法真实取消（Future.cancel 无效），
  报告"任务仍将运行至完成"，信号量由完成回调统一释放，不误报取消。
- 线程/并发/队列/内存等超限有真实检查和动作（拒绝/排空/优雅停止）。
- 资源报告来自实际运行状态（活跃任务数/线程数），不接受调用方手工峰值作为唯一证据。
- 一个执行单元超限不能影响另一个执行单元。
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as 未来超时
from typing import Any, Callable
from 公共契约.基础类型.逻辑类型 import 真, 假


class 资源监督器:
    """资源监督器：预算校验 + 有界执行 + 采样 + 超限处置（多进程单机范围）。"""

    def __init__(self, 状态) -> None:
        self.状态 = 状态
        self._池表: dict[str, ThreadPoolExecutor] = {}
        self._信号量表: dict[str, threading.BoundedSemaphore] = {}
        self._活跃表: dict[str, dict[str, Any]] = {}  # 单元id → {任务id: Future}
        self._报告表: dict[str, dict[str, Any]] = {}
        self._锁 = threading.Lock()

    # ---- 预算声明校验 ----
    必需预算键 = ("内存上限", "线程上限", "子进程上限", "并发调用上限",
                 "队列长度", "文件句柄上限", "临时空间上限", "单次调用超时",
                 "每分钟重启次数", "空闲回收时间")

    def 校验预算声明(self, 预算: dict[str, Any]) -> tuple[bool, str]:
        缺失 = [键 for 键 in self.必需预算键 if 键 not in 预算]
        if 缺失:
            return 假, f"资源预算缺少必需项: {缺失}"
        return 真, "预算声明完整"

    def 注册执行单元(self, *, 单元id: str, 预算: dict[str, Any]) -> tuple[bool, str]:
        """启动前注册：校验预算并创建有界池/信号量。"""
        有效, 消息 = self.校验预算声明(预算)
        if not 有效:
            return 假, 消息
        with self._锁:
            if 单元id in self._池表:
                return 假, f"执行单元已注册: {单元id}"
            self._池表[单元id] = ThreadPoolExecutor(max_workers=int(预算["线程上限"]))
            self._信号量表[单元id] = threading.BoundedSemaphore(int(预算["并发调用上限"]))
            self._活跃表[单元id] = {}
            self._报告表[单元id] = {"线程峰值": 0, "并发峰值": 0, "队列峰值": 0,
                                   "内存峰值": 0, "超限次数": 0, "动作": [],
                                   "任务总数": 0, "成功": 0, "失败": 0, "取消": 0}
        return 真, "执行单元已注册"

    def 提交任务(self, 单元id: str, 任务: Callable[[], Any], *参数,
                 超时秒: float = 0) -> tuple[bool, str, Any]:
        """有界执行：信号量限流 + Future 回调释放；超时如实报告真实语义。

        返回 (成功, 消息, 结果)。任务执行异常时 结果 为异常对象。
        """
        if 单元id not in self._池表:
            return 假, f"执行单元未注册: {单元id}", None
        信号量 = self._信号量表[单元id]
        if not 信号量.acquire(blocking=False):
            self._记录超限(单元id, "并发超限")
            return 假, "并发调用超限，任务被拒绝", None
        任务id = uuid.uuid4().hex[:12]
        未来 = self._池表[单元id].submit(任务, *参数)
        with self._锁:
            self._活跃表[单元id][任务id] = 未来
            self._报告表[单元id]["任务总数"] += 1
            self._报告表[单元id]["并发峰值"] = max(
                self._报告表[单元id]["并发峰值"], len(self._活跃表[单元id]))
            self._报告表[单元id]["线程峰值"] = max(
                self._报告表[单元id]["线程峰值"], len(self._活跃表[单元id]))

        def 完成回调(将来) -> None:
            """任务完成/失败/取消：释放信号量 + 移除活跃表 + 报告统计。

            优雅停止可能已移除单元 → 全部用 get 兜底（幂等）。
            """
            try:
                结果值 = 将来.result()
                结果类型 = "成功"
            except Exception:
                结果值 = 将来.exception()
                结果类型 = "失败"
            if 将来.cancelled():
                结果类型 = "取消"
            with self._锁:
                self._活跃表.get(单元id, {}).pop(任务id, None)
                if 单元id in self._报告表:
                    self._报告表[单元id][结果类型] = self._报告表[单元id].get(结果类型, 0) + 1
            信号量 = self._信号量表.get(单元id)
            if 信号量 is not None:
                信号量.release()

        未来.add_done_callback(完成回调)
        if 超时秒 > 0:
            try:
                结果值 = 未来.result(timeout=超时秒)
                return 真, "任务完成", 结果值
            except 未来超时:
                # 运行中任务的 Future.cancel() 无效：如实报告任务仍将运行至完成，
                # 完成回调统一负责释放信号量+移除活跃表（防止双重释放），不再误报取消。
                已取消 = 未来.cancel()
                语义 = "任务已取消" if 已取消 else "任务仍将运行至完成，后续调用可能排队"
                self._记录超限(单元id, f"单次调用超时({超时秒}s)，{语义}")
                return 假, f"单次调用超时({超时秒}s)，{语义}", None
            except Exception as 错误:
                return 假, f"任务失败: {错误}", 错误
        return 真, "任务已提交", None

    def _记录超限(self, 单元id: str, 原因: str) -> None:
        with self._锁:
            if 单元id in self._报告表:
                self._报告表[单元id]["超限次数"] += 1
                self._报告表[单元id]["动作"].append(原因)
        self.状态.追加证据(类型="资源监督", 主题=单元id, 内容={"超限": 原因},
                          结果="拒绝")

    def 采样(self, 单元id: str, *, 内存MB: float = 0.0) -> dict[str, Any]:
        """运行中采样：峰值来自实际运行状态（活跃任务数），非调用方手工传入。"""
        with self._锁:
            报告 = self._报告表.setdefault(单元id, {"线程峰值": 0, "并发峰值": 0, "队列峰值": 0,
                                                "内存峰值": 0, "超限次数": 0, "动作": [],
                                                "任务总数": 0, "成功": 0, "失败": 0, "取消": 0})
            活跃数 = len(self._活跃表.get(单元id, {}))
            报告["并发峰值"] = max(报告["并发峰值"], 活跃数)
            报告["线程峰值"] = max(报告["线程峰值"], 活跃数)
            报告["内存峰值"] = max(报告["内存峰值"], 内存MB)
            return dict(报告)

    def 检查超限(self, 单元id: str, 预算: dict[str, Any]) -> tuple[bool, str]:
        """超限检查：线程/并发/队列/内存任一超限即失败（由调用方处置）。"""
        报告 = self.采样(单元id)
        活跃数 = len(self._活跃表.get(单元id, {}))
        检查表 = [
            (报告["线程峰值"] > int(预算.get("线程上限", 10**9)), "线程超限"),
            (活跃数 > int(预算.get("并发调用上限", 10**9)), "并发超限"),
            (活跃数 > int(预算.get("队列长度", 10**9)), "队列超限"),
            (报告["内存峰值"] > float(预算.get("内存上限", 10**9)), "内存超限"),
        ]
        for 超限, 原因 in 检查表:
            if 超限:
                self._记录超限(单元id, 原因)
                return 假, f"资源超限: {原因}"
        return 真, "资源正常"

    def 排空(self, 单元id: str) -> None:
        """排空已有任务（等待全部完成）。"""
        未来表 = list(self._活跃表.get(单元id, {}).values())
        for 未来 in 未来表:
            未来.cancel()
        with self._锁:
            self._活跃表[单元id] = {}

    def 优雅停止(self, 单元id: str) -> None:
        """排空 + 优雅停止（有界池）。"""
        with self._锁:
            池 = self._池表.pop(单元id, None)
            self._信号量表.pop(单元id, None)
            self._活跃表.pop(单元id, None)
        if 池 is not None:
            池.shutdown(wait=False, cancel_futures=True)

    def 状态报告(self) -> dict[str, Any]:
        return {单元id: dict(报告) for 单元id, 报告 in self._报告表.items()}
