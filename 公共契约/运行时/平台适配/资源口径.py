"""资源与句柄口径三原语：内存峰值单位 / 句柄枚举目录 / 子进程组启动标志。"""

from __future__ import annotations

import subprocess
import sys

from 公共契约.运行时.平台适配.判定 import 是Windows, 平台不支持错误


#: POSIX 进程句柄枚举目录候选（按优先级）：Linux 走 ``/proc`` 伪文件系统，
#: macOS/BSD 走 ``/dev/fd`` 设备目录；两者都是「当前进程已打开句柄」的目录视图。
POSIX句柄目录表 = ("/proc/self/fd", "/dev/fd")

#: 微软 WinAPI ``CreateProcess`` 的 ``CREATE_NEW_PROCESS_GROUP`` 固定值（0x00000200）。
#: 真实 Windows 上 ``subprocess.CREATE_NEW_PROCESS_GROUP`` 恒存在；此处仅作极端缺失时的
#: 回退值——用官方文档固定值而非 0，避免默默丢掉「独立进程组」语义。
Windows新建进程组标志 = 0x00000200


def 内存峰值原始单位() -> tuple[str, int]:
    """``resource.getrusage(RUSAGE_SELF).ru_maxrss`` 的原始单位与到 KB 的换算除数。

    该字段的单位**由平台定、调用点无法可靠推断**：macOS/BSD 系返回**字节**
    （要 ``/1024`` 才是 KB），Linux 返回 **KB**（本身即 KB）。调用方按
    ``原始值 / 除数`` 得 KB，再 ``/1024`` 得 MB。

    返回 ``(单位名, 除数)``，如 ``("字节", 1024)`` / ``("KB", 1)``。

    **不认识的平台显式报不支持**（``平台不支持错误``）：猜「一律当 KB」会让读数差
    1024 倍且没人看得出来。Windows 无 ``resource`` 模块，同样走这条报错路径。
    """
    标志 = sys.platform
    if 标志.startswith("win"):
        raise 平台不支持错误("内存峰值采样（getrusage）：Windows 无 resource 模块")
    if 标志 == "darwin" or 标志.startswith(("freebsd", "openbsd", "netbsd", "dragonfly")):
        return ("字节", 1024)  # BSD 系 ru_maxrss 单位是字节
    if 标志.startswith("linux"):
        return ("KB", 1)  # Linux ru_maxrss 单位是 KB
    raise 平台不支持错误(
        f"内存峰值采样（getrusage）：平台 {标志!r} 的 ru_maxrss 单位无权威定义，"
        f"拒绝按其他平台猜换算系数"
    )


def 句柄枚举目录表() -> tuple[str, ...]:
    """返回可直接 ``os.listdir`` 的当前进程句柄目录候选（按优先级；可能为空元组）。

    POSIX → ``/proc/self/fd``（Linux）、``/dev/fd``（macOS/BSD），二者都真实反映
    当前进程已打开的句柄（含标准三句柄）。

    Windows → **空元组**：Windows 没有 ``/proc`` 或 ``/dev`` 等价目录，真实句柄数
    只能经 ``NtQuerySystemInformation`` 之类的系统调用枚举（本层不引第三方、不做
    系统调用级实现）。**空元组是「本平台无此能力」的显式信号，不是「句柄数为 0」**：
    调用方必须据此**明确报不支持**，不得静默跳过采样，也不得报一个 0 冒充真实值。
    """
    if 是Windows():
        return ()
    return POSIX句柄目录表


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
