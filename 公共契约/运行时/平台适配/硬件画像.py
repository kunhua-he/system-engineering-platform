"""硬件画像采样（OS 差异的唯一落点）：内存容量 / 物理核数 / 处理器型号 / 图形加速 / Apple Silicon。

三态语义与 `句柄枚举目录表` 同口径：``支持=假`` 是「本平台无此能力」的显式信号，
不是「值等于 0」—— 调用方必须据此保守降级（fail-closed）。"""

from __future__ import annotations

import ctypes
import os
import re

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.平台适配.采样基元 import (
    Linux内存信息路径,
    Linux处理器信息路径,
    _执行只读采样命令,
    _读伪文件,
    system_profiler候选路径,
    sysctl候选路径,
    vm_stat候选路径,
    内存采样超时秒,
    图形采样超时秒,
)
from 公共契约.运行时.平台适配.判定 import 是Linux, 是macOS, 当前平台
from 公共契约.运行时.平台适配.准入 import 当前架构


#: Apple Silicon 架构表 —— **只用于 MLX/Metal 能力判定，不是准入表**。
#:
#: 必须与 ``正式支持矩阵`` 分开：MLX 运行时走 Metal，**仅 Apple Silicon 可用**；
#: Intel Mac / Linux / Windows 上结构性不可用（实测：Linux x86_64 装完整个闭包后
#: `import mlx.core` 仍恒报 `libmlx.so: cannot open shared object file`）。
#: 若直接复用准入矩阵，放开 Linux 后 Intel/Linux 机器会被误判成「可走 MLX」。
AppleSilicon架构表 = ("arm64", "aarch64")


#: macOS Mach VM 统计 flavor（XNU ABI 常量：HOST_VM_INFO64）。
_MACH_HOST_VM_INFO64 = 4

#: macOS 系统调用入口库（ctypes 直接加载，不起子进程）。
_libSystem路径 = "/usr/lib/libSystem.B.dylib"


class _虚拟机统计64(ctypes.Structure):
    """macOS ``vm_statistics64`` 的逐字段镜像（XNU ABI）。

    **字段顺序与类型不得改动**：ABI 只认布局，改名不影响，改序即读错。
    字段名用中文只为本仓可读性，与 XNU 头文件字段的对应见行尾注释。
    """

    _fields_ = (
        ("空闲页", ctypes.c_uint),              # free_count
        ("活跃页", ctypes.c_uint),              # active_count
        ("非活跃页", ctypes.c_uint),            # inactive_count
        ("常驻页", ctypes.c_uint),              # wire_count
        ("零填充计数", ctypes.c_uint64),        # zero_fill_count
        ("再激活计数", ctypes.c_uint64),        # reactivations
        ("换入计数", ctypes.c_uint64),          # pageins
        ("换出计数", ctypes.c_uint64),          # pageouts
        ("缺页计数", ctypes.c_uint64),          # faults
        ("写时复制缺页", ctypes.c_uint64),      # cow_faults
        ("查找计数", ctypes.c_uint64),          # lookups
        ("命中计数", ctypes.c_uint64),          # hits
        ("清除计数", ctypes.c_uint64),          # purges
        ("可回收页", ctypes.c_uint),            # purgeable_count
        ("推测页", ctypes.c_uint),              # speculative_count
        ("解压计数", ctypes.c_uint64),          # decompressions
        ("压缩计数", ctypes.c_uint64),          # compressions
        ("交换入计数", ctypes.c_uint64),        # swapins
        ("交换出计数", ctypes.c_uint64),        # swapouts
        ("压缩器占用页", ctypes.c_uint),        # compressor_page_count
        ("限流页", ctypes.c_uint),              # throttled_count
        ("外部页", ctypes.c_uint),              # external_page_count
        ("内部页", ctypes.c_uint),              # internal_page_count
        ("压缩器未压页", ctypes.c_uint64),      # total_uncompressed_pages_in_compressor
    )


def _macOS内存容量_系统调用() -> dict[str, object] | None:
    """macOS 内存容量（微秒级，纯系统调用）；任一步失败返回 None 交给子进程回退。

    **为什么有这条快速路（2026-09-21 实测）**：原实现走 `sysctl` / `vm_stat`
    **子进程**，单次约 2.5 毫秒；资源闸门要在**每次请求**上采样，2.5 毫秒会被
    放大成可观测延迟。`sysctlbyname` + `host_statistics64` 两次系统调用实测
    **约 1.2 微秒**（实测：vm_stat 2.562ms / sysctl 2.625ms 对系统调用 0.0012ms）。

    **口径与 `_macOS可用内存字节()` 完全一致，不产生第二套口径**：
    ``可用 = free + inactive + speculative + purgeable``（与 macOS 官方
    `memory_pressure` 的 available 一致）。

    **speculative 不得重复计（2026-09-21 实测）**：Mach 的 ``free_count`` **已含**
    ``speculative_count`` —— 实测 free 3257144 对 vm_stat ``Pages free`` 2685800，
    差额 571344 ≈ speculative 571290（vm_stat 把 speculative 从 free 里单列）。
    故本函数只加「非活跃页」与「可回收页」，**不再加「推测页」**；再加一次会
    系统性高估可用内存约 8.7 GB，把水位判据压低。
    """
    依据 = ("sysctlbyname hw.memsize + host_statistics64"
            "（free+inactive+purgeable；speculative 已含于 free）")
    try:
        libc = ctypes.CDLL(_libSystem路径)
    except OSError:
        return None
    总量 = ctypes.c_uint64(0)
    总量尺寸 = ctypes.c_size_t(ctypes.sizeof(ctypes.c_uint64))
    try:
        总量码 = libc.sysctlbyname(b"hw.memsize", ctypes.byref(总量),
                                  ctypes.byref(总量尺寸), None, 0)
    except AttributeError:
        return None
    if 总量码 != 0 or int(总量.value) <= 0:
        return None
    物理字节 = int(总量.value)
    try:
        libc.host_statistics64.argtypes = (
            ctypes.c_uint, ctypes.c_int,
            ctypes.POINTER(_虚拟机统计64), ctypes.POINTER(ctypes.c_uint))
        libc.host_statistics64.restype = ctypes.c_int
        libc.mach_host_self.restype = ctypes.c_uint
        统计 = _虚拟机统计64()
        计数 = ctypes.c_uint(ctypes.sizeof(_虚拟机统计64) // ctypes.sizeof(ctypes.c_uint))
        统计码 = libc.host_statistics64(libc.mach_host_self(), _MACH_HOST_VM_INFO64,
                                       ctypes.byref(统计), ctypes.byref(计数))
    except AttributeError:
        return None
    if 统计码 != 0:
        return None
    页大小 = int(os.sysconf("SC_PAGE_SIZE") or 0)
    if 页大小 <= 0:
        return None
    可用页 = 统计.空闲页 + 统计.非活跃页 + 统计.可回收页
    可用字节 = 可用页 * 页大小
    if 可用页 <= 0 or 可用字节 > 物理字节:
        return None      # 口径异常：交给回退，不回报错值（哲学第 3 条 2 项）
    return {"支持": 真, "物理字节": 物理字节, "可用字节": 可用字节,
            "依据": 依据, "原因": ""}


def _macOS可用内存字节() -> tuple[int, str]:
    """macOS 可用内存（字节）与失败原因：`vm_stat` 的 free+inactive+speculative+purgeable。

    **为什么不用 `sysctl vm.page_free_count` 单一字段**：macOS 的
    `Pages inactive` / `Pages purgeable` 都是**可立即回收**的页，只算 free
    会系统性低估可用内存（本机实测：free 25.7GB 对 四类合计 54.6GB），
    而容量高水位正是按可用内存推的，低估会把基线压得过紧。
    口径与 macOS 官方 `memory_pressure` 的 "available" 统计一致。
    """
    结果 = _执行只读采样命令(vm_stat候选路径, (), 内存采样超时秒)
    if 结果 is None or 结果[0] != 0:
        return 0, "vm_stat 不可用，可用内存按未知处理"
    页大小匹配 = re.search(r"page size of (\d+) bytes", 结果[1])
    if not 页大小匹配:
        return 0, "vm_stat 输出缺少页大小，可用内存按未知处理"
    页大小 = int(页大小匹配.group(1))
    累计页 = 0
    for 行 in 结果[1].splitlines():
        匹配 = re.match(r"([A-Za-z][A-Za-z ]*):\s+(\d+)\.", 行)
        if not 匹配:
            continue
        if 匹配.group(1).strip() in ("Pages free", "Pages inactive",
                                     "Pages speculative", "Pages purgeable"):
            累计页 += int(匹配.group(2))
    if 累计页 <= 0:
        return 0, "vm_stat 输出未解析到可用页，可用内存按未知处理"
    return 累计页 * 页大小, ""


def _Linux内存容量() -> dict[str, object]:
    """Linux 内存容量（`/proc/meminfo` 的 MemTotal / MemAvailable）。"""
    依据 = f"/proc/meminfo（{Linux内存信息路径}）"
    文本 = _读伪文件(Linux内存信息路径)
    if 文本 is None:
        return {"支持": 假, "物理字节": 0, "可用字节": 0, "依据": 依据,
                "原因": "读不到 /proc/meminfo"}
    字段: dict[str, int] = {}
    for 行 in 文本.splitlines():
        名, 分隔符, 值 = 行.partition(":")
        if not 分隔符:
            continue
        数字 = 值.strip().split()
        if not 数字:
            continue
        try:
            字段[名.strip()] = int(数字[0])
        except ValueError:
            continue
    总量 = 字段.get("MemTotal", 0) * 1024
    if 总量 <= 0:
        return {"支持": 假, "物理字节": 0, "可用字节": 0, "依据": 依据,
                "原因": "MemTotal 缺失或非整数"}
    可用 = 字段.get("MemAvailable", 0) * 1024
    原因 = "" if 可用 > 0 else "MemAvailable 缺失（内核过旧），可用内存按未知处理"
    return {"支持": 真, "物理字节": 总量, "可用字节": 可用, "依据": 依据,
            "原因": 原因}


def 内存容量信息() -> dict[str, object]:
    """物理内存与可用内存（字节）。返回 ``{支持, 物理字节, 可用字节, 依据, 原因}``。

    - macOS：`sysctl -n hw.memsize` 取物理内存；`vm_stat` 取可用内存；
    - Linux：`/proc/meminfo` 的 `MemTotal` / `MemAvailable`；
    - 其余平台：``支持=假``（显式「无此能力」，不是「内存为 0」）。

    `可用字节=0` 且 ``支持=真`` 表示「物理内存读到了、可用内存没读到」
    （此时 `原因` 非空），调用方按保守比例降级，不得当成「可用内存为零」。
    """
    if 是macOS():
        快速 = _macOS内存容量_系统调用()
        if 快速 is not None:
            return 快速
        总量 = _执行只读采样命令(sysctl候选路径, ("-n", "hw.memsize"), 内存采样超时秒)
        依据 = "sysctl -n hw.memsize + vm_stat（free+inactive+speculative+purgeable）"
        if 总量 is None or 总量[0] != 0:
            return {"支持": 假, "物理字节": 0, "可用字节": 0, "依据": 依据,
                    "原因": "sysctl 不可用或退出码非零，物理内存读取失败"}
        try:
            物理字节 = int(总量[1].strip())
        except ValueError:
            return {"支持": 假, "物理字节": 0, "可用字节": 0, "依据": 依据,
                    "原因": "hw.memsize 输出不是整数"}
        if 物理字节 <= 0:
            return {"支持": 假, "物理字节": 0, "可用字节": 0, "依据": 依据,
                    "原因": "hw.memsize 返回非正数"}
        可用字节, 可用原因 = _macOS可用内存字节()
        return {"支持": 真, "物理字节": 物理字节, "可用字节": 可用字节,
                "依据": 依据, "原因": 可用原因}
    if 是Linux():
        return _Linux内存容量()
    return {"支持": 假, "物理字节": 0, "可用字节": 0,
            "依据": f"平台 {当前平台()}", "原因": "本平台无标准库内存容量取法"}


def 物理核数信息() -> dict[str, object]:
    """物理核数（区别于 `os.cpu_count()` 给的逻辑核数）。返回 ``{支持, 物理核, 依据, 原因}``。

    - macOS：`sysctl -n hw.physicalcpu`；
    - Linux：`/proc/cpuinfo` 里 `(physical id, core id)` 去重计数；
    - 其余平台：``支持=假``。

    这个数字只用于**离散档位的核数档**（每档容量参数），不是任何硬校验的上限：
    读不到时调用方按「最小档」保守降级，不得拿逻辑核数冒充物理核数。
    """
    if 是macOS():
        结果 = _执行只读采样命令(sysctl候选路径, ("-n", "hw.physicalcpu"), 内存采样超时秒)
        依据 = "sysctl -n hw.physicalcpu"
        if 结果 is None or 结果[0] != 0:
            return {"支持": 假, "物理核": 0, "依据": 依据,
                    "原因": "sysctl 不可用或退出码非零"}
        try:
            核数 = int(结果[1].strip())
        except ValueError:
            return {"支持": 假, "物理核": 0, "依据": 依据, "原因": "输出不是整数"}
        if 核数 <= 0:
            return {"支持": 假, "物理核": 0, "依据": 依据, "原因": "返回非正数"}
        return {"支持": 真, "物理核": 核数, "依据": 依据, "原因": ""}
    if 是Linux():
        依据 = f"/proc/cpuinfo（{Linux处理器信息路径}）"
        文本 = _读伪文件(Linux处理器信息路径)
        if 文本 is None:
            return {"支持": 假, "物理核": 0, "依据": 依据, "原因": "读不到 /proc/cpuinfo"}
        对: set[tuple[str, str]] = set()
        for 块 in 文本.split("\n\n"):
            物理id = 核id = None
            for 行 in 块.splitlines():
                名, 分隔符, 值 = 行.partition(":")
                if not 分隔符:
                    continue
                名, 值 = 名.strip(), 值.strip()
                if 名 == "physical id":
                    物理id = 值
                elif 名 == "core id":
                    核id = 值
            if 物理id is not None and 核id is not None:
                对.add((物理id, 核id))
        if not 对:
            return {"支持": 假, "物理核": 0, "依据": 依据,
                    "原因": "cpuinfo 无 physical id / core id 字段（虚拟机常见）"}
        return {"支持": 真, "物理核": len(对), "依据": 依据, "原因": ""}
    return {"支持": 假, "物理核": 0, "依据": f"平台 {当前平台()}",
            "原因": "本平台无标准库物理核数取法"}


def 处理器型号信息() -> dict[str, object]:
    """处理器型号原文（画像里的「芯片」字段）。返回 ``{支持, 型号, 依据, 原因}``。

    - macOS：`sysctl -n machdep.cpu.brand_string`（Apple Silicon 上实测如 ``Apple M3 Ultra``）；
    - Linux：`/proc/cpuinfo` 首个 `model name`；
    - 其余平台：``支持=假``。

    型号只作**画像展示**（启动日志/诊断端点），不参与任何档位判定 ——
    只用于人读，故不做归一化、不改写厂商字样。
    """
    if 是macOS():
        结果 = _执行只读采样命令(sysctl候选路径, ("-n", "machdep.cpu.brand_string"),
                                  内存采样超时秒)
        依据 = "sysctl -n machdep.cpu.brand_string"
        if 结果 is None or 结果[0] != 0:
            return {"支持": 假, "型号": "", "依据": 依据,
                    "原因": "sysctl 不可用或退出码非零"}
        型号 = 结果[1].strip()
        if not 型号:
            return {"支持": 假, "型号": "", "依据": 依据, "原因": "型号输出为空"}
        return {"支持": 真, "型号": 型号, "依据": 依据, "原因": ""}
    if 是Linux():
        依据 = f"/proc/cpuinfo（{Linux处理器信息路径}）"
        文本 = _读伪文件(Linux处理器信息路径)
        if 文本 is None:
            return {"支持": 假, "型号": "", "依据": 依据, "原因": "读不到 /proc/cpuinfo"}
        for 行 in 文本.splitlines():
            名, 分隔符, 值 = 行.partition(":")
            if 分隔符 and 名.strip() == "model name" and 值.strip():
                return {"支持": 真, "型号": 值.strip(), "依据": 依据, "原因": ""}
        return {"支持": 假, "型号": "", "依据": 依据, "原因": "cpuinfo 无 model name 字段"}
    return {"支持": 假, "型号": "", "依据": f"平台 {当前平台()}",
            "原因": "本平台无标准库处理器型号取法"}


def 图形加速信息() -> dict[str, object]:
    """图形加速事实：图形芯片与 Metal 支持版本。``{支持, 图形芯片, Metal版本, 依据, 原因}``。

    - macOS：`system_profiler SPDisplaysDataType`（**较慢，实测 0.26 秒**，
      调用方必须缓存，全程只调一次）；
    - 其余平台：``支持=假``。

    ``支持=真`` 而 ``Metal版本=""`` 表示「探到了图形信息但没有 Metal 支持行」；
    ``支持=假`` 表示「探不到」——**两者对调用方是同一处置：按「无 Metal」保守降级**
    （fail-closed）。“探不到” 绝不允许被解释成 “有 Metal”。
    """
    if 是macOS():
        结果 = _执行只读采样命令(system_profiler候选路径, ("SPDisplaysDataType",),
                                  图形采样超时秒)
        依据 = "system_profiler SPDisplaysDataType"
        if 结果 is None or 结果[0] != 0:
            return {"支持": 假, "图形芯片": "", "Metal版本": "", "依据": 依据,
                    "原因": "system_profiler 不可用或退出码非零"}
        图形芯片 = ""
        Metal版本 = ""
        当前芯片 = ""
        for 行 in 结果[1].splitlines():
            名, 分隔符, 值 = 行.partition(":")
            if not 分隔符:
                if 行.strip().endswith(":") and 行.strip():
                    当前芯片 = 行.strip().rstrip(":").strip()
                continue
            名, 值 = 名.strip(), 值.strip()
            if 名 == "Chipset Model" and not 图形芯片:
                图形芯片 = 值 or 当前芯片
            elif 名 == "Metal Support" and not Metal版本:
                Metal版本 = 值
        return {"支持": 真, "图形芯片": 图形芯片, "Metal版本": Metal版本,
                "依据": 依据, "原因": "" if (图形芯片 or Metal版本) else "输出未解析到芯片/Metal 行"}
    return {"支持": 假, "图形芯片": "", "Metal版本": "", "依据": f"平台 {当前平台()}",
            "原因": "本平台无标准库图形加速取法"}


def 是否AppleSilicon() -> bool:
    """是否 Apple Silicon（macOS + ``AppleSilicon架构表`` 内的架构）。

    用 ``AppleSilicon架构表``（**不是**准入矩阵 ``正式支持矩阵``）：本函数回答的是
    「MLX/Metal 能不能用」，而准入矩阵是「这个环境有没有验收证据」——两者口径不同。
    放开 Linux/Windows 准入后若复用准入矩阵，Intel Mac 与 Linux 会被误判成可走 MLX。
    非 macOS 或架构不在表内一律返回 ``假``（不抛异常：这是画像字段，不是准入判据；
    环境准入仍由 ``校验支持范围()`` 负责）。
    """
    return 是macOS() and 当前架构() in AppleSilicon架构表
