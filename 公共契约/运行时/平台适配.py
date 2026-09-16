"""跨平台平台适配：平台判定 / 虚拟环境解释器相对路径 / 子进程组启动标志。

背景（华哥 2026-09-16 裁决：底座做完整跨平台）：底座此前在 **Windows 11 / AMD64** 上
完全跑不起来，根因之一是「POSIX 布局被硬编码」——POSIX 的虚拟环境解释器是
``venv/bin/python3``，Windows 上真实布局是 ``venv/Scripts/python.exe``；POSIX 用
``start_new_session=True`` 开独立进程组，Windows 用 ``creationflags=CREATE_NEW_PROCESS_GROUP``。

本模块是**全平台唯一实现**（哲学第 8 条唯一性判定②：同一件事两种语义 → 同一份实现 +
模式变量）。后续批次把 6 处硬编码 ``bin/python3`` 与全部 ``start_new_session=True``
调用点切到本模块，调用点不再自带平台分支。

**设计约束**

1. **只依赖标准库**（``sys`` / ``subprocess`` / ``pathlib``），不引入第三方。
2. **平台判定在「调用时」读取** ``sys.platform``，不在导入时冻结——这样测试可以用
   monkeypatch 把整个模块切到 Windows 形态验证分支选择，也为将来可能的平台探测留口。
3. **平台不支持的能力显式报错**（``平台不支持错误``），绝不静默降级成别的语义。

**诚实标注：本模块的 Windows 分支未经真机实测**（开发机为 macOS）。Windows 分支的
判定逻辑仅通过 monkeypatch 模拟 ``sys.platform == "win32"`` 做过分支选择验证，
真实 Windows 上的行为需在 Windows 11 / AMD64 机器上复核。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

平台表 = ("macOS", "Windows", "Linux", "未知")

#: POSIX 虚拟环境解释器相对路径（``python -m venv`` 的固定布局）
POSIX解释器相对路径 = "bin/python3"
#: Windows 虚拟环境解释器相对路径（``python -m venv`` 的固定布局）
Windows解释器相对路径 = "Scripts/python.exe"

#: 微软 WinAPI ``CreateProcess`` 的 ``CREATE_NEW_PROCESS_GROUP`` 固定值（0x00000200）。
#: 真实 Windows 上 ``subprocess.CREATE_NEW_PROCESS_GROUP`` 恒存在；此处仅作极端缺失时的
#: 回退值——用官方文档固定值而非 0，避免默默丢掉「独立进程组」语义。
Windows新建进程组标志 = 0x00000200


class 平台不支持错误(RuntimeError):
    """调用方请求了当前平台不存在的能力。

    单独定义类型（而非抛 ``RuntimeError``/``AttributeError``）是为了让调用方能在统一的
    异常边界里精确捕获「平台不支持」，与「参数错误」「权限错误」区分开。
    """


def 原始平台标志() -> str:
    """返回 ``sys.platform`` 原始值（``darwin``/``win32``/``linux``…），仅用于诊断与日志。"""
    return sys.platform


def 当前平台() -> str:
    """返回人类可读的当前平台名：``macOS`` / ``Windows`` / ``Linux`` / ``未知``。

    只依据 ``sys.platform`` 判定，不调用 ``platform.system()``（后者有子进程/系统调用
    成本且在某些容器里返回宿主系统名），也不引入第三方。

    ``cygwin``/``freebsd`` 等未列入的平台返回 ``未知``——但 ``是POSIX()`` 仍为真，
    调用方应按能力探测（``hasattr(os, "killpg")``）而非按名字硬判。
    """
    标志 = sys.platform
    if 标志.startswith("win"):
        return "Windows"
    if 标志 == "darwin":
        return "macOS"
    if 标志.startswith("linux"):
        return "Linux"
    return "未知"


def 是Windows() -> bool:
    """是否 Windows（``sys.platform`` 以 ``win`` 开头，含 ``win32`` / ``win_amd64`` 等变体）。"""
    return sys.platform.startswith("win")


def 是macOS() -> bool:
    """是否 macOS（``sys.platform == "darwin"``）。"""
    return sys.platform == "darwin"


def 是Linux() -> bool:
    """是否 Linux（``sys.platform`` 以 ``linux`` 开头）。"""
    return sys.platform.startswith("linux")


def 是POSIX() -> bool:
    """是否 POSIX 系（非 Windows）。

    与 ``是Windows()`` 严格互补，保证两个分支「必有其一命中」，不留无主区间。
    """
    return not 是Windows()


def 虚拟环境解释器相对路径() -> str:
    """返回虚拟环境内解释器相对其根的路径（无前导分隔符）。

    POSIX → ``bin/python3``；Windows → ``Scripts/python.exe``。

    供后续批次替换 ``运行核心/运行环境管理器/环境管理器.py`` 第 323/410/619/683/684 行与
    ``强制校验.py`` 第 281 行的硬编码 ``目标 / "bin" / "python3"``。
    """
    if 是Windows():
        return Windows解释器相对路径
    return POSIX解释器相对路径


def 虚拟环境解释器路径(环境根: str | Path) -> Path:
    """把虚拟环境根目录拼成解释器的完整路径（只拼路径，不校验存在、不创建）。

    ``环境根`` 可以是 ``str`` 或 ``Path``；返回 ``Path``。是否真实存在由调用方用
    ``.is_file()`` 判定（现有调用点就是这么用的，见环境管理器第 684 行）。
    """
    return Path(环境根) / 虚拟环境解释器相对路径()


def 子进程组启动标志() -> dict[str, object]:
    """返回让子进程独占一个进程组的 ``subprocess`` 关键字参数（供 ``**`` 展开）。

    - POSIX：``{"start_new_session": True}``（``setsid`` 独立会话+进程组，组号 == 组长 PID）
    - Windows：``{"creationflags": CREATE_NEW_PROCESS_GROUP}``

    用法：``subprocess.Popen(命令, **子进程组启动标志())``。

    Windows 分支优先取 ``subprocess.CREATE_NEW_PROCESS_GROUP``；该属性缺失或非正数时
    回退到官方文档固定值 ``Windows新建进程组标志``（不静默丢成 0——那会让子进程留在父
    进程组里，Ctrl 事件与终止范围都会错）。
    """
    if 是Windows():
        标志值 = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if isinstance(标志值, bool) or not isinstance(标志值, int) or 标志值 <= 0:
            标志值 = Windows新建进程组标志
        return {"creationflags": 标志值}
    return {"start_new_session": True}


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


__all__ = [
    "平台表",
    "POSIX解释器相对路径",
    "Windows解释器相对路径",
    "Windows新建进程组标志",
    "平台不支持错误",
    "原始平台标志",
    "当前平台",
    "是Windows",
    "是macOS",
    "是Linux",
    "是POSIX",
    "虚拟环境解释器相对路径",
    "虚拟环境解释器路径",
    "子进程组启动标志",
    "要求POSIX能力",
]
