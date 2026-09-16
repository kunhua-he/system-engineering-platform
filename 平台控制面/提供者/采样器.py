"""真实资源采样器提供者：内存/文件句柄/临时空间，全部来自真实系统状态。

- 采样内存(): resource.getrusage(RUSAGE_SELF).ru_maxrss 实际峰值
  （macOS 为字节、Linux 为 KB，按平台换算为 MB）
- 采样文件句柄(): 枚举 /proc/self/fd（Linux）或 /dev/fd（macOS）实际句柄数
- 采样临时空间(目录): os.path.getsize 对目录内全部文件求和（真实磁盘占用）
- 组合报告(监督器报告, 临时目录): 真实采样 + 资源监督器峰值（线程/并发/队列），
  供资源监督器对外报告使用。任何采样失败都如实标注，不伪装数值。

统一结果固定包含：成功、值、错误码、错误说明。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

from 公共契约.运行时 import 平台适配

句柄目录表 = ("/proc/self/fd", "/dev/fd")  # Linux / macOS 真实句柄枚举目录


def 采样内存() -> dict:
    """真实内存峰值：getrusage RU_MAXRSS（macOS 字节 / Linux KB，换算为 MB）。

    ``resource`` 是 POSIX 专有模块（Windows 上根本不存在，顶层导入会让 import 本模块即崩），
    因此在真正取用它的本函数内惰性导入；非 POSIX 平台**显式报不支持**（抛 平台不支持错误），
    不静默返回假数值、也不静默跳过采样。
    """
    平台适配.要求POSIX能力("resource 内存峰值采样（getrusage）")
    from resource import RUSAGE_SELF, getrusage  # 惰性导入：POSIX 专有
    原始值 = getrusage(RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":  # macOS：字节
        原始单位, 峰值MB = "字节", 原始值 / 1024 / 1024
    else:  # Linux 等：KB
        原始单位, 峰值MB = "KB", 原始值 / 1024
    return {"成功": True, "值": round(峰值MB, 2), "原始值": 原始值,
            "原始单位": 原始单位, "错误码": "", "错误说明": ""}


def 采样文件句柄() -> dict:
    """真实文件句柄数：枚举当前进程句柄目录（/proc/self/fd 或 /dev/fd）。"""
    for 目录 in 句柄目录表:
        try:
            return {"成功": True, "值": len(os.listdir(目录)), "来源": 目录,
                    "错误码": "", "错误说明": ""}
        except OSError:
            continue
    return {"成功": False, "值": -1, "来源": "", "错误码": "句柄枚举失败",
            "错误说明": "无法枚举文件句柄：/proc/self/fd 与 /dev/fd 均不可用"}


def 采样临时空间(目录) -> dict:
    """真实临时空间占用：os.path.getsize 对目录内全部文件求和（字节）。"""
    根 = os.fspath(目录)
    if not os.path.isdir(根):
        return {"成功": False, "值": 0, "文件数": 0, "错误码": "目录不可用",
                "错误说明": f"目录不存在或不可读: {根}"}
    总字节, 文件数 = 0, 0
    for 当前目录, 子目录表, 文件表 in os.walk(根):
        for 文件名 in 文件表:
            路径 = os.path.join(当前目录, 文件名)
            try:
                总字节 += os.path.getsize(路径)
                文件数 += 1
            except OSError:
                continue  # 枚举后被删除等竞态：跳过，不伪装
    return {"成功": True, "值": 总字节, "文件数": 文件数,
            "错误码": "", "错误说明": ""}


报告键表 = ("成功", "内存峰值MB", "文件句柄数", "临时空间字节",
           "线程峰值", "并发峰值", "队列峰值", "单元表", "采样时间", "错误说明")


def 组合报告(监督器报告=None, 临时目录=None) -> dict:
    """组合资源监督器报告：真实采样（内存/句柄/临时空间）+ 监督器峰值。

    监督器报告 为 资源监督.状态报告() 的输出（单元id → 单元报告）；
    线程/并发/队列峰值取全部执行单元的最大值，内存峰值与真实采样取大。
    """
    内存 = 采样内存()
    句柄 = 采样文件句柄()
    临时 = 采样临时空间(临时目录 if 临时目录 is not None else tempfile.gettempdir())
    单元表 = dict(监督器报告 or {})
    if 单元表 and not all(isinstance(项, dict) for 项 in 单元表.values()):
        单元表 = {"": 单元表}  # 兼容直接传入单个执行单元报告
    峰值表 = {"线程峰值": 0, "并发峰值": 0, "队列峰值": 0, "内存峰值": 0.0}
    for 单元报告 in 单元表.values():
        for 键 in 峰值表:
            try:
                峰值表[键] = max(峰值表[键], float(单元报告.get(键, 0)))
            except (TypeError, ValueError):
                continue
    失败表 = [项["错误说明"] for 项 in (内存, 句柄, 临时) if not 项["成功"]]
    return {
        "成功": not 失败表,
        "内存峰值MB": round(max(内存["值"], 峰值表["内存峰值"]), 2),
        "文件句柄数": 句柄["值"],
        "临时空间字节": 临时["值"],
        "线程峰值": int(峰值表["线程峰值"]),
        "并发峰值": int(峰值表["并发峰值"]),
        "队列峰值": int(峰值表["队列峰值"]),
        "单元表": 单元表,
        "采样时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "错误说明": "；".join(失败表),
    }
