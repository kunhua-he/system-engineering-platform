"""采样底座：只读命令的有界执行与伪文件的有界读取，以及 macOS 采样命令候选路径表。

只提供「拿到事实」的机制，不做任何平台判断（平台差异在 `硬件画像.py`）。"""

from __future__ import annotations

import subprocess
from pathlib import Path


# ── 硬件画像采样（OS 差异的**唯一**落点）─────────────────────────
#
# 口径（决策记录 `0045` §五「零新增第三方依赖的取法」）：硬件画像要
# 「只准标准库」，但每个字段的**取法**本身就是平台差异 —— macOS 走
# `sysctl` / `vm_stat` / `system_profiler`，Linux 走 `/proc` 伪文件，
# Windows 两者都没有。按本模块既定纪律（**平台差异只在本模块判断，
# 调用点不许写 `sys.platform`、不许自带平台分支**），这些取法一律收口
# 到这里：上层 `支持库/适配层/硬件画像探针.py` 只拿事实，既不碰命令名，
# 也不判断自己跑在哪个平台。
#
# **三态语义**（与 `句柄枚举目录表` 同口径）：``支持=假`` 是「本平台无此
# 能力」的**显式信号**，不是「值等于 0」—— 调用方必须据此保守降级
# （fail-closed），不得把 0 当成真实读数。这与 `内存峰值原始单位` 那种
# 「不认识就抛异常」不同，原因是：画像探针跑在**启动期诊断路径**上，
# 采样失败绝不能拖垮启动；失败必须在返回值里显名（``原因`` 字段），
# 由调用方决定降级策略，而不是让异常替调用方做决定。
#
# **诚实标注**：`Linux` 分支与 `句柄枚举目录表` 的既有标注同一处境 ——
# 开发机为 macOS，Linux 取法（`/proc/meminfo`、`/proc/cpuinfo`）只按
# 内核文档写就，**未经真机实测**；`Windows` 分支明确返回「不支持」，
# 不猜、不降级成别的语义。

#: 内存/处理核采样命令的超时秒（`sysctl`/`vm_stat` 都是毫秒级返回，留足裕量）
内存采样超时秒 = 5.0
#: 图形加速采样命令的超时秒（`system_profiler` 明显更慢，实测 0.26 秒，留足裕量）
图形采样超时秒 = 8.0
#: 采样命令标准输出的**有界**上限字节（只解析首几十行，不把整份输出读进内存）
采样命令输出上限字节 = 256 * 1024
#: `/proc` 伪文件读取的**有界**上限字节（内核生成，大小固定，有界只为可证）
伪文件读取上限字节 = 256 * 1024
#: macOS 采样命令候选绝对路径（按优先级；用绝对路径而不是 `shutil.which`，
#: 避免 PATH 被调用方进程污染后取到另一个同名可执行文件）
sysctl候选路径 = ("/usr/sbin/sysctl", "/usr/bin/sysctl")
vm_stat候选路径 = ("/usr/bin/vm_stat", "/usr/sbin/vm_stat")
system_profiler候选路径 = ("/usr/sbin/system_profiler", "/usr/bin/system_profiler")
#: Linux 伪文件路径
Linux内存信息路径 = "/proc/meminfo"
Linux处理器信息路径 = "/proc/cpuinfo"


def _执行只读采样命令(候选路径表: tuple[str, ...], 参数表: tuple[str, ...],
                     超时秒: float) -> tuple[int, str] | None:
    """按候选绝对路径逐个尝试执行只读采样命令；全部不可用/失败返回 ``None``。

    输出**有界**（超 `采样命令输出上限字节` 即截断），失败一律收敛为 ``None``
    而不抛异常 —— 采样是只读诊断动作，任何失败都必须是「拿不到事实」，
    不能变成「调用方崩了」。
    """
    for 路径 in 候选路径表:
        if not Path(路径).is_file():
            continue
        try:
            完成 = subprocess.run([路径, *参数表], capture_output=True, timeout=超时秒)
        except (OSError, subprocess.TimeoutExpired):
            continue
        return int(完成.returncode), 完成.stdout[:采样命令输出上限字节].decode(
            "utf-8", errors="replace")
    return None


def _读伪文件(路径: str) -> str | None:
    """有界读一个伪文件（前 `伪文件读取上限字节` 字节）；读不到返回 ``None``。"""
    try:
        with open(路径, "rb") as 流:
            数据 = 流.read(伪文件读取上限字节)
    except OSError:
        return None
    return 数据.decode("utf-8", errors="replace")
