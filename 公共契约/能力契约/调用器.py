"""能力调用器契约：模块按能力 id 调用支持库的唯一通道。

模块不 import 支持库/提供者/运行核心实现；只经本契约文件声明的
调用器接口获取"按能力 id 调用"的注入调用器。运行核心装配时调用
注册注入；未装配时第一次获取触发惰性装配（保证任意入口可用）。
"""

from __future__ import annotations

import threading
from typing import Any, Protocol


class 能力调用器(Protocol):
    """能力调用器协议：按能力 id 调用、查询历史、失败诊断。"""

    def 调用能力(self, 能力id: str, 参数: dict[str, Any] | None = None, *,
                 调用方: str = "", 项目id: str = "", 超时秒: float | None = None) -> Any: ...

    def 幂等重放(self, 能力id: str, 参数: dict[str, Any]) -> bool: ...

    def 查询调用历史(self, 上限: int = 50) -> list[dict[str, Any]]: ...

    def 最近失败(self, 上限: int = 10) -> list[dict[str, Any]]: ...

    def 回答九问(self, 能力id: str, 错误码: str) -> dict[str, str]: ...


_全局调用器: 能力调用器 | None = None
_全局锁 = threading.Lock()
_惰性装配函数: Any = None


def 注册能力调用器(调用器: 能力调用器 | None) -> None:
    """运行核心装配后注册/卸载全局调用器（None 表示卸载）。"""
    global _全局调用器
    with _全局锁:
        _全局调用器 = 调用器


def 设置惰性装配函数(函数) -> None:
    """运行核心注册惰性装配钩子：首次获取调用器且未装配时调用。"""
    global _惰性装配函数
    with _全局锁:
        _惰性装配函数 = 函数


def 获取能力调用器() -> 能力调用器:
    """模块实现内获取注入的能力调用器。

    未装配时触发一次惰性装配（注册表+调用器注入），保证任意入口
    首次调用即得权威注册表；失败抛出明确错误，禁止绕过。
    """
    global _全局调用器
    with _全局锁:
        if _全局调用器 is not None:
            return _全局调用器
        惰性装配 = _惰性装配函数
    if 惰性装配 is not None:
        惰性装配()
        with _全局锁:
            if _全局调用器 is not None:
                return _全局调用器
    raise RuntimeError(
        "能力调用器未注入：模块必须由加载器装配后调用，"
        "禁止直接导入支持库/提供者绕过能力调用服务"
    )
