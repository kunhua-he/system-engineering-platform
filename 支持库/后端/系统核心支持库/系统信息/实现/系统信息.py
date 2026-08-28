"""系统信息原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：操作系统/CPU/内存/磁盘/进程信息查询（参考易语言系统核心支持库）。
纯标准库，不做业务逻辑；只读查询不修改系统状态。
"""

from __future__ import annotations

import json
import os
import platform
import socket

from 公共契约.基础类型.结果类型 import 结果



降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程）

def 获取操作系统信息() -> 结果:
    """操作系统信息。返回 {系统, 版本, 架构, 主机名, Python版本}。"""
    return 结果.成功结果({
        "系统": platform.system(),
        "版本": platform.release(),
        "完整版本": platform.version(),
        "架构": platform.machine(),
        "处理器": platform.processor(),
        "主机名": socket.gethostname(),
        "Python版本": platform.python_version(),
    })


def 获取CPU信息() -> 结果:
    """CPU 信息。返回 {物理核数, 逻辑核数, 使用率}。"""
    import subprocess
    负载 = None
    try:
        # macOS 用 sysctl 取负载
        运行结果 = subprocess.run(["sysctl", "-n", "vm.loadavg"], capture_output=True, text=True, timeout=3)
        if 运行结果.returncode == 0:
            负载 = 运行结果.stdout.strip().split()
    except Exception as 错误:
        降级记录表.append(str(错误))
    return 结果.成功结果({
        "物理核数": os.cpu_count() or 0,
        "逻辑核数": os.cpu_count() or 0,
        "负载均值": 负载,
    })


def 获取内存信息() -> 结果:
    """内存信息。返回 {总量, 可用量, 已用量}（字节）。"""
    try:
        import subprocess
        运行结果 = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3)
        总量 = int(运行结果.stdout.strip()) if 运行结果.returncode == 0 else 0
    except Exception:
        总量 = 0
    # macOS 可用内存近似（物理内存 - 压缩内存，仅提示）
    return 结果.成功结果({"总量字节": 总量, "可用字节": None, "已用字节": None,
                            "说明": "macOS 可用/已用内存需经 vm_stat 计算"})


def 获取磁盘信息(路径: str = None) -> 结果:
    """磁盘信息。返回 {总量, 可用, 已用}（字节）。"""
    import shutil
    目标 = 路径 or "/"
    try:
        使用 = shutil.disk_usage(目标)
        return 结果.成功结果({"路径": 目标, "总量字节": 使用.total,
                                "可用字节": 使用.free, "已用字节": 使用.used})
    except OSError as 错误:
        return 结果.失败("路径不合法", f"无法获取磁盘信息: {错误}", 来源="系统信息")


def 获取进程列表(排序: str = None) -> 结果:
    """进程列表。返回 {进程数, 进程列表}。"""
    import subprocess
    方式 = (排序 or "cpu").strip()
    参数 = ["ps", "axo", "pid,pcpu,pmem,comm", "-r"] if 方式 == "cpu" else ["ps", "axo", "pid,pcpu,pmem,comm"]
    try:
        运行结果 = subprocess.run(参数, capture_output=True, text=True, timeout=5)
        if 运行结果.returncode != 0:
            return 结果.失败("执行失败", 运行结果.stderr.strip(), 来源="系统信息")
        行列表 = 运行结果.stdout.strip().split("\n")
        if len(行列表) < 2:
            return 结果.成功结果({"进程数": 0, "进程列表": []})
        进程列表 = []
        for 行 in 行列表[1:]:
            部分 = 行.split()
            if len(部分) >= 4:
                进程列表.append({"PID": 部分[0], "CPU%": 部分[1], "内存%": 部分[2], "命令": " ".join(部分[3:])})
        return 结果.成功结果({"进程数": len(进程列表), "进程列表": 进程列表[:200]})
    except Exception as 错误:
        return 结果.失败("执行失败", str(错误), 来源="系统信息")
