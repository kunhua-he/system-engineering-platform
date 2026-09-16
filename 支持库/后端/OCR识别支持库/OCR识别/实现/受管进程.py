"""受管进程：外部命令独立进程组受管执行（tesseract 等外部命令专用）。

start_new_session 独立进程组；终止一律 killpg（SIGTERM→宽限→SIGKILL），
杜绝孤儿进程与残留。超时、取消（threading.Event 轮询）、输出上限（后台
泵线程计数防内存爆炸）三类强制终止，分别映射稳定错误码：超时/取消/
超出限制。正常结束返回 {退出码, 标准输出, 标准错误}，由调用方按语义
分类（如信号杀死 → 进程崩溃、非零退出 → 识别失败等）。
"""

from __future__ import annotations

import subprocess
import threading
import time

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时 import 平台适配, 进程终止

默认超时秒 = 60.0
默认输出上限字节 = 32 * 1024 * 1024
终止宽限秒 = 1.0
轮询间隔秒 = 0.01


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="受管进程", 可重试=可重试)


def 终止进程组(进程: subprocess.Popen, 宽限秒: float = 终止宽限秒) -> None:
    """进程组终止（终止→宽限→强杀→复查死透）：唯一实现在 公共契约.运行时.进程终止。

    平台差异（POSIX 按进程组 / Windows 按进程树）由收口层自己判定：本处不再持有
    平台判断、信号号或 killpg 调用；保留同名同签名的薄委托，是因为既有测试
    （测试中心/支持库/测试_Tesseract提供者.py 及 OCR 调用链）按本名打桩/复用。
    """
    进程终止.强制结束子进程(进程, 宽限秒=宽限秒, 等待秒=宽限秒)


class _输出泵:
    """后台线程泵取 stdout/stderr；超上限只计数不累积（防内存爆炸）。"""

    def __init__(self, 进程: subprocess.Popen, 上限: int) -> None:
        self._进程, self._上限 = 进程, 上限
        self._输出, self._错误 = bytearray(), bytearray()
        self.超限 = False
        self._锁 = threading.Lock()
        self._线程 = []
        for 流, 缓冲 in ((进程.stdout, self._输出), (进程.stderr, self._错误)):
            线程 = threading.Thread(target=self._泵流, args=(流, 缓冲), daemon=True)
            线程.start()
            self._线程.append(线程)

    def _泵流(self, 流, 缓冲: bytearray) -> None:
        while True:
            try:
                块 = 流.read(65536)
            except (OSError, ValueError):
                return
            if not 块:
                return
            with self._锁:
                if len(缓冲) >= self._上限:
                    self.超限 = True
                else:
                    余量 = self._上限 - len(缓冲)
                    缓冲 += 块[:余量]
                    if len(块) > 余量:
                        self.超限 = True

    def 等待(self) -> None:
        for 线程 in self._线程:
            线程.join(timeout=终止宽限秒 * 2)

    def 文本(self) -> tuple[str, str]:
        return (bytes(self._输出).decode("utf-8", errors="replace"),
                bytes(self._错误).decode("utf-8", errors="replace"))


def 执行命令(
    命令列表: list[str],
    *,
    超时秒: float = 默认超时秒,
    输出上限字节: int = 默认输出上限字节,
    取消事件: threading.Event | None = None,
    工作目录: str | None = None,
) -> 结果:
    """受管执行外部命令；终止/失败路径返回稳定错误码，绝不抛异常。"""
    if (not isinstance(命令列表, list) or not 命令列表
            or not all(isinstance(项, str) and 项 for 项 in 命令列表)):
        return _失败("参数不合法", "命令列表必须是非空文本列表")
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return _失败("参数不合法", "超时秒必须是正数")
    if not isinstance(输出上限字节, int) or 输出上限字节 <= 0:
        return _失败("参数不合法", "输出上限字节必须是正整数")
    if 取消事件 is not None and not isinstance(取消事件, threading.Event):
        return _失败("参数不合法", "取消事件必须是 threading.Event 或 None")
    try:
        进程 = subprocess.Popen(
            命令列表, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=工作目录, **平台适配.子进程组启动标志(),
        )
    except OSError as 错误:
        return _失败("提供者不可用", f"无法启动外部命令: {错误}", 可重试=True)
    泵 = _输出泵(进程, 输出上限字节)
    开始 = time.monotonic()
    终止结果: 结果 | None = None
    try:
        while True:
            if 泵.超限:
                终止结果 = _失败("超出限制",
                                f"外部命令输出超过上限 {输出上限字节} 字节")
                break
            if 取消事件 is not None and 取消事件.is_set():
                终止结果 = _失败("取消", "任务已被取消", 可重试=True)
                break
            if 进程.poll() is not None:
                break
            if time.monotonic() - 开始 > 超时秒:
                终止结果 = _失败("超时", f"外部命令执行超过 {超时秒} 秒", 可重试=True)
                break
            time.sleep(轮询间隔秒)
    finally:
        if 进程.poll() is None:
            终止进程组(进程)  # 零残留：进程组必死
        泵.等待()
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            try:
                if 流 is not None:
                    流.close()
            except (OSError, ValueError):
                pass
    if 终止结果 is not None or 泵.超限:
        return 终止结果 or _失败("超出限制",
                                 f"外部命令输出超过上限 {输出上限字节} 字节")
    标准输出, 标准错误 = 泵.文本()
    return 结果.成功结果({"退出码": 进程.returncode, "标准输出": 标准输出,
                          "标准错误": 标准错误})


def 等待并收集(进程列表: list[subprocess.Popen], 超时秒: float = 10.0) -> None:
    """批量等待并强制清理子进程（测试与收口用），幂等。"""
    for 进程 in 进程列表:
        try:
            if 进程.poll() is None:
                终止进程组(进程, 宽限秒=超时秒)
        except (OSError, ValueError):
            pass
