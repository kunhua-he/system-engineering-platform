"""非阻塞真读一次（socket 层，**绝不 MSG_PEEK**；POSIX 走 ``MSG_DONTWAIT``，Windows 临时置非阻塞）。"""

from __future__ import annotations

import socket
from typing import Any

from 公共契约.运行时.平台适配.判定 import 平台不支持错误


#: 非阻塞真读一次的缺省单次读上限字节（与既有 `消费上行字节` 的取值一致）
非阻塞读上限字节 = 4096


def 非阻塞真读一次(连接: Any, 上限字节: int = 非阻塞读上限字节) -> bytes:
    """对 socket 连接做**非阻塞真读一次**；返回本次读到的字节（``b""`` 表示对端已关闭）。

    无数据可读时抛 ``BlockingIOError``（与 ``socket`` 非阻塞读的既有语义一致，
    调用方按「暂无数据」处置，不当作断开）。**绝不用 ``MSG_PEEK`` 偷看**：
    偷看不从内核缓冲区移除数据，会让 ``select`` 恒判可读、监视线程 100% 占核空转。

    **为什么必须收口在这里**（#173，2026-09-21）：``socket.MSG_DONTWAIT`` 是 **POSIX 专有常量**，
    Windows 上 ``socket`` 模块根本没有该属性 —— 直接访问即抛 ``AttributeError``。
    此前 `运行核心/统一网关/传输/流式HTTP.py` 裸用它，在 Windows 上会让 SSE 断开
    监视线程**抛异常逸出 daemon 线程**（只留 stderr traceback）：断开清理完全不触发、
    有界信号量拖到 30 秒超时才释放。

    取法按**能力探测**（``getattr(socket, "MSG_DONTWAIT", None)``）而不是平台名判断，
    与本模块「只读属性目录树删除」一节同一纪律：

    - 有 ``MSG_DONTWAIT``（POSIX）→ ``recv(上限字节, MSG_DONTWAIT)``，零额外状态变更；
    - 无 ``MSG_DONTWAIT``（Windows）→ 临时 ``setblocking(False)`` 读一次，
      **读完恢复原超时设置**（不改变调用方持有的连接状态）；无数据时同样抛
      ``BlockingIOError``，与 POSIX 分支语义逐字一致。

    连接对象既不支持 ``MSG_DONTWAIT`` 也不支持 ``setblocking`` 时显式抛
    ``平台不支持错误``（不静默降级成阻塞读 —— 那会把监视线程永久挂死）。
    """
    标记 = getattr(socket, "MSG_DONTWAIT", None)
    if 标记 is not None:
        return 连接.recv(上限字节, 标记)
    设非阻塞 = getattr(连接, "setblocking", None)
    if 设非阻塞 is None:
        raise 平台不支持错误(
            "本平台无 socket.MSG_DONTWAIT，且连接对象不支持 setblocking，"
            "无法做非阻塞真读一次；请改用 select 轮询路径"
        )
    取超时 = getattr(连接, "gettimeout", None)
    原超时 = 取超时() if 取超时 is not None else None
    设超时 = getattr(连接, "settimeout", None)
    try:
        设非阻塞(False)
        return 连接.recv(上限字节)
    finally:
        if 原超时 is None:
            设非阻塞(True)
        elif 设超时 is not None:
            设超时(原超时)
