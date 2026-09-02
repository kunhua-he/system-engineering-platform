"""统一有界输入输出：读取达到上限后继续排空，避免管道阻塞和内存失控。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable


默认读取块大小 = 65536
默认JSONL读取上限字节 = 4 * 1024 * 1024
默认JSONL读取上限记录 = 2000
默认JSONL文件上限字节 = 8 * 1024 * 1024
默认子进程输出上限字节 = 256 * 1024


def 受限读取(
    流: Any, 上限字节: int, *, 块大小: int = 默认读取块大小,
    数据回调: Callable[[bytes], None] | None = None,
    超限回调: Callable[[], None] | None = None,
) -> tuple[bytes, bool]:
    """流式读取并排空输入，返回（上限内字节、是否超限）。"""
    上限 = int(上限字节)
    if 上限 < 1:
        raise ValueError("读取上限必须大于 0")
    块大小 = max(1024, int(块大小))
    缓冲 = bytearray()
    已读字节 = 0
    超限 = False
    while True:
        块 = 流.read(块大小)
        if not 块:
            break
        已读字节 += len(块)
        if 数据回调 is not None:
            数据回调(块)
        if len(缓冲) < 上限:
            剩余 = 上限 - len(缓冲)
            缓冲.extend(块[:剩余])
        if 已读字节 > 上限:
            if not 超限:
                超限 = True
                if 超限回调 is not None:
                    超限回调()
    return bytes(缓冲), 超限


def 读取文件(路径: str | Path, 上限字节: int) -> tuple[bytes, bool]:
    """有界读取文件；调用方负责把超限转换为结构化错误。"""
    with Path(路径).open("rb") as 文件:
        return 受限读取(文件, 上限字节)


def 读取JSONL(
    路径: str | Path, *, 最大字节数: int = 默认JSONL读取上限字节,
    最大记录数: int = 默认JSONL读取上限记录,
) -> tuple[list[dict[str, Any]], bool]:
    """从 JSONL 尾部有界读取，返回（合法记录、是否截断）。"""
    文件 = Path(路径)
    if not 文件.is_file():
        return [], False
    字节上限 = max(1024, int(最大字节数))
    记录上限 = max(1, int(最大记录数))
    文件大小 = 文件.stat().st_size
    起点 = max(0, 文件大小 - 字节上限)
    记录列表: list[dict[str, Any]] = []
    with 文件.open("rb") as 流:
        流.seek(起点)
        if 起点:
            流.readline()
        for 原始行 in 流:
            try:
                记录 = json.loads(原始行.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(记录, dict):
                记录列表.append(记录)
            if len(记录列表) >= 记录上限:
                return 记录列表, True
    return 记录列表, 起点 > 0


def 追加JSONL(
    路径: str | Path, 记录: dict[str, Any], *,
    最大文件字节数: int = 默认JSONL文件上限字节, 轮转数量: int = 2,
    强制落盘: bool = False,
) -> None:
    """有界追加 JSONL；达到上限时保留有限份轮转文件。"""
    文件 = Path(路径)
    文件.parent.mkdir(parents=True, exist_ok=True)
    if 文件.is_file() and 文件.stat().st_size >= max(1024, int(最大文件字节数)):
        轮转数量 = max(1, int(轮转数量))
        for 序号 in range(轮转数量 - 1, 0, -1):
            旧文件 = 文件.with_name(f"{文件.name}.{序号}")
            新文件 = 文件.with_name(f"{文件.name}.{序号 + 1}")
            if 旧文件.is_file():
                新文件.unlink(missing_ok=True)
                旧文件.replace(新文件)
        文件.with_name(f"{文件.name}.1").unlink(missing_ok=True)
        文件.replace(文件.with_name(f"{文件.name}.1"))
    with 文件.open("a", encoding="utf-8") as 输出:
        输出.write(json.dumps(记录, ensure_ascii=False) + "\n")
        if 强制落盘:
            输出.flush()
            import os
            os.fsync(输出.fileno())


def 受限通信(
    进程: Any, *, 输入: bytes | None = None, 超时秒: float,
    输出上限字节: int = 默认子进程输出上限字节,
    终止回调: Callable[[], None] | None = None,
) -> tuple[bytes, bytes, bool, bool]:
    """有界读写子进程管道，返回（stdout、stderr、是否超时、是否超限）。"""
    if 进程.stdin is not None:
        if 输入:
            进程.stdin.write(输入)
            进程.stdin.flush()
        进程.stdin.close()

    结果: dict[str, bytearray] = {"输出": bytearray(), "错误": bytearray()}
    超限事件 = threading.Event()
    读取线程: list[threading.Thread] = []

    def 读取(名称: str, 流: Any) -> None:
        if 流 is None:
            return
        内容, _超限 = 受限读取(
            流, 输出上限字节, 超限回调=超限事件.set,
        )
        结果[名称].extend(内容)

    for 名称, 流 in (("输出", 进程.stdout), ("错误", 进程.stderr)):
        线程 = threading.Thread(target=读取, args=(名称, 流), daemon=True,
                              name=f"受限通信-{名称}")
        线程.start()
        读取线程.append(线程)

    截止 = time.monotonic() + max(0.0, float(超时秒))
    已超时 = False
    while 进程.poll() is None:
        if 超限事件.is_set():
            break
        if time.monotonic() >= 截止:
            已超时 = True
            break
        time.sleep(0.05)

    if (已超时 or 超限事件.is_set()) and 终止回调 is not None:
        终止回调()
    for 线程 in 读取线程:
        线程.join(timeout=5)
    for 流 in (进程.stdout, 进程.stderr):
        if 流 is None:
            continue
        try:
            流.close()
        except OSError:
            pass
    return bytes(结果["输出"]), bytes(结果["错误"]), 已超时, 超限事件.is_set()
