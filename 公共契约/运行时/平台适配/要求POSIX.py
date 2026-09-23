"""显式要求 POSIX 专有能力（`os.killpg` / `os.fork` / `resource` 这类 Windows 上不存在的能力）。"""

from __future__ import annotations

from 公共契约.运行时.平台适配.判定 import 是Windows, 平台不支持错误


def 要求POSIX能力(能力名: str) -> None:
    """显式要求当前平台具备某项 POSIX 专有能力；不满足即抛 ``平台不支持错误``。

    用于 ``os.killpg`` / ``os.getpgid`` / ``os.fork`` / ``resource`` 这类 Windows 上
    **根本不存在** 的能力——调用方要么走跨平台实现，要么明确报不支持，
    **不允许** 让 ``AttributeError`` 逸出或静默降级。
    """
    if 是Windows():
        raise 平台不支持错误(
            f"当前平台为 Windows，不支持 POSIX 专有能力「{能力名}」；"
            f"请改用 公共契约.运行时.进程终止 的跨平台实现"
        )
