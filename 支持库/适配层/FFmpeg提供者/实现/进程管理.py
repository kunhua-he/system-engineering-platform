"""FFmpeg 外部进程受管执行核心：独立进程组+超时+取消+输出上限截断+零残留。

ffmpeg/ffprobe 属外部命令，主进程直接受管调用：
- 子进程组启动标志 独立进程组，终止时整组强杀回收（含孙进程）；
- 轮询循环同时支持 超时 与 外部取消函数，触发后强制结束子进程；
- stdout/stderr 后台线程受限读取（超限截断并继续排空防管道阻塞）；
- 成功/超时/取消/崩溃全路径回收子进程并等待读取线程结束，零残留。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable

from 公共契约.运行时 import 平台适配, 进程终止

终止宽限秒 = 1.0
轮询间隔秒 = 0.02


@dataclass
class 受管结果:
    """受管命令执行结果：成功/退出码/受限输出/截断标记/进程组id/错误码。"""

    成功: bool
    退出码: int | None = None
    标准输出: bytes = b""
    标准错误: bytes = b""
    输出截断: bool = False
    进程组id: int | None = None
    耗时秒: float = 0.0
    错误码: str = ""
    错误摘要: str = ""


def _受限读取(流, 上限: int) -> tuple[bytes, bool]:
    """读满上限后继续排空（防止管道阻塞导致进程挂死），返回 (受限内容, 截断标记)。"""
    缓冲 = bytearray()
    截断 = False
    while True:
        块 = 流.read(65536)
        if not 块:
            break
        余量 = 上限 - len(缓冲)
        if 余量 > 0:
            缓冲.extend(块[:余量])
            if len(块) > 余量:
                截断 = True
        else:
            截断 = True
    return bytes(缓冲), 截断


def 执行受管命令(命令列表: list[str], *, 超时秒: float, 最大输出字节: int,
              取消函数: Callable[[], bool] | None = None) -> 受管结果:
    """受管执行外部命令：超时/取消触发强制结束子进程；输出超限截断；失败不抛异常。

    失败映射稳定错误码：提供者不可用（启动失败）/ 超时 / 取消 / 进程崩溃（退出码非零）。
    """
    开始 = time.monotonic()
    try:
        进程 = subprocess.Popen(
            命令列表, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **平台适配.子进程组启动标志(),
        )
    except OSError as 错误:
        return 受管结果(成功=False, 错误码="提供者不可用", 错误摘要=str(错误))
    进程组id = os.getpgid(进程.pid)
    共享 = {"标准输出": b"", "标准错误": b"", "截断": False}

    def 读取流(流, 键: str) -> None:
        受限, 截断 = _受限读取(流, 最大输出字节)
        共享[键] = 受限
        if 截断:
            共享["截断"] = True

    线程列表 = [
        threading.Thread(target=读取流, args=(进程.stdout, "标准输出"), daemon=True),
        threading.Thread(target=读取流, args=(进程.stderr, "标准错误"), daemon=True),
    ]
    for 线程 in 线程列表:
        线程.start()
    截止 = time.monotonic() + 超时秒
    触发 = ""
    while 进程.poll() is None:
        if 取消函数 is not None and 取消函数():
            触发 = "取消"
            break
        if time.monotonic() >= 截止:
            触发 = "超时"
            break
        time.sleep(轮询间隔秒)
    if 触发:
        进程终止.强制结束子进程(进程, 宽限秒=终止宽限秒, 等待秒=终止宽限秒)
    退出码 = 进程.poll()
    for 线程 in 线程列表:
        线程.join(timeout=终止宽限秒 + 1.0)
    for 流 in (进程.stdout, 进程.stderr):
        if 流:
            try:
                流.close()
            except (OSError, ValueError):
                pass
    标准错误 = 共享["标准错误"]
    错误摘要 = (标准错误.decode("utf-8", errors="replace").strip() or "")[-300:]
    耗时秒 = time.monotonic() - 开始
    if 触发:
        return 受管结果(
            成功=False, 退出码=退出码, 标准输出=共享["标准输出"],
            标准错误=标准错误, 输出截断=共享["截断"], 进程组id=进程组id,
            耗时秒=耗时秒, 错误码=触发,
            错误摘要=f"{触发}: 外部命令执行被终止（限制 {超时秒} 秒）",
        )
    if 退出码 != 0:
        return 受管结果(
            成功=False, 退出码=退出码, 标准输出=共享["标准输出"],
            标准错误=标准错误, 输出截断=共享["截断"], 进程组id=进程组id,
            耗时秒=耗时秒, 错误码="进程崩溃",
            错误摘要=f"外部命令异常退出（退出码 {退出码}）: {错误摘要}",
        )
    return 受管结果(
        成功=True, 退出码=0, 标准输出=共享["标准输出"],
        标准错误=标准错误, 输出截断=共享["截断"], 进程组id=进程组id,
        耗时秒=耗时秒,
    )
