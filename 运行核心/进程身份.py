"""进程身份：进程id/启动指纹/项目id/所有者/实例id/最后心跳。

进程 id 被系统复用时不能误认成原进程：以 启动指纹（进程创建时间戳 +
实例随机数）区分，pid 相同但指纹不同即视为不同进程。
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# 进程存活探测的跨平台实现只在 公共契约/运行时/ 收口层；本文件不裸调 os.kill。
from 公共契约.运行时 import 进程终止
from 公共契约.基础类型.逻辑类型 import 真, 假


@dataclass
class 进程身份:
    """一个进程的唯一身份。"""

    进程id: int = 0
    启动指纹: str = ""
    项目id: str = ""
    所有者: str = ""
    实例id: str = ""
    最后心跳: float = 0.0

    def 身份键(self) -> str:
        """跨进程唯一身份键（pid + 启动指纹）。"""
        return f"{self.进程id}:{self.启动指纹}"

    def 转字典(self) -> dict[str, Any]:
        return {
            "进程id": self.进程id, "启动指纹": self.启动指纹, "项目id": self.项目id,
            "所有者": self.所有者, "实例id": self.实例id, "最后心跳": self.最后心跳,
            "身份键": self.身份键(),
        }


def 创建进程身份(*, 项目id: str = "", 所有者: str = "") -> 进程身份:
    """创建当前进程身份：pid + 启动指纹（进程创建时间 + 实例随机数）。"""
    启动指纹 = f"{time.time_ns():x}-{uuid.uuid4().hex[:8]}"
    return 进程身份(
        进程id=os.getpid(),
        启动指纹=启动指纹,
        项目id=项目id,
        所有者=所有者,
        实例id=uuid.uuid4().hex[:12],
        最后心跳=time.time(),
    )


def 心跳(身份: 进程身份) -> None:
    """更新最后心跳。"""
    身份.最后心跳 = time.time()


def 进程存活(身份: 进程身份, 心跳超时秒: float = 15.0) -> bool:
    """按心跳判断进程是否存活（pid 复用不误认：指纹一致才视为同进程）。"""
    return (time.time() - 身份.最后心跳) <= 心跳超时秒


def 系统进程存在(进程id: int) -> bool:
    """查询操作系统中的进程是否仍存在，不发送终止信号。

    探测一律经跨平台收口层：原先按 0 号信号裸探活在 Windows 上不是探活，
    而是 ``TerminateProcess``——会把被查的进程真杀掉（且其它 OSError 还会逸出）。
    ``进程终止.进程存活`` 按平台选 WinAPI 或 POSIX 探活，非法入参返回 False 不抛。
    """
    if 进程id <= 0:
        return 假
    return 进程终止.进程存活(进程id)
