"""收口层能力探测：内存峰值原始单位（真分配实测）、POSIX 专有能力要能力入口。

两项都拒绝「读常量当结论」：内存单位要真分配 64MB 做增量实测，POSIX 能力要
真调 要求POSIX能力 并核对抛出的异常类型是调用方能捕到的那一种。"""

from __future__ import annotations

import os

from 开发工具.环境自检.基础 import 结论_不支持, 结论_通过, 结论_警告, 自检项


def _探_内存峰值原始单位() -> 自检项:
    from 公共契约.运行时 import 平台适配

    为什么 = ("`resource.getrusage().ru_maxrss` 的单位由平台定（macOS/BSD 是字节、Linux 是 KB），"
              "搞错会让读数差 1024 倍而且没人看得出来。本项不只读单位，还真分配一大块内存"
              "做增量实测：只有单位映射与真实分配量对得上才算通过。")
    try:
        单位, 除数 = 平台适配.内存峰值原始单位()
    except 平台适配.平台不支持错误 as 错误:
        return 自检项("4.4", "平台适配.内存峰值原始单位()", 结论_不支持,
                    f"本平台明确不支持：{错误}",
                    为什么,
                    "内存峰值采样不可用（Windows 无 resource 模块）；资源诊断该项如实报不支持。",
                    {"平台": 平台适配.当前平台()})
    try:
        import resource
    except ImportError as 错误:  # 极少数构建裁掉了 resource
        return 自检项("4.4", "平台适配.内存峰值原始单位()", 结论_不支持,
                    f"平台适配声称单位是 {单位!r}/除数 {除数}，但本机导不进 resource 模块：{错误}",
                    为什么, "单位映射与真实模块不一致 → 内存采样必然崩。", {})

    前 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    大块 = bytearray(64 * 1024 * 1024)
    大块[::4096] = b"\x01" * (64 * 1024 * 1024 // 4096)  # 逐页触碰，确保真的被计入
    后 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    增量 = 后 - 前
    增量MB = 增量 / 除数 / 1024 if 除数 else -1.0
    合理 = 4.0 <= 增量MB <= 512.0  # 实际分配 64MB：合理区间给足余量，单位搞错必落在区间外
    详情 = {"单位": 单位, "除数": 除数, "分配字节": 64 * 1024 * 1024,
            "原始值增量": 增量, "按单位换算的增量MB": round(增量MB, 3),
            "判定区间MB": [4.0, 512.0]}
    del 大块
    if not 合理:
        return 自检项("4.4", "平台适配.内存峰值原始单位()", 结论_不支持,
                    f"单位映射与真实分配量对不上：声明 {单位!r}/除数 {除数}，"
                    f"实际分配 64MB 却算出 {增量MB:.3f} MB（期望 4–512 MB）",
                    为什么, "内存读数会差 1024 倍且无人察觉（正是本函数存在的理由）。", 详情)
    return 自检项("4.4", "平台适配.内存峰值原始单位()", 结论_通过,
                f"{单位!r}/除数 {除数}；实测分配 64MB → 增量 {增量} → {增量MB:.1f} MB（在 4–512 区间内）",
                为什么, "", 详情)


def _探_要求POSIX能力() -> 自检项:
    from 公共契约.运行时 import 平台适配

    为什么 = ("`os.killpg` / `os.getpgid` / `os.fork` / `resource` 这些在 Windows 上根本不存在。"
              "要求POSIX能力 是调用方统一要能力的入口：本平台没有就必须抛 平台不支持错误"
              "（而不是让 AttributeError 逸出或静默降级）。")
    详情 = {"平台": 平台适配.当前平台(), "hasattr os.fork": hasattr(os, "fork"),
            "hasattr os.killpg": hasattr(os, "killpg"), "hasattr os.getpgid": hasattr(os, "getpgid")}
    try:
        平台适配.要求POSIX能力("os.fork + os.killpg + os.getpgid")
    except 平台适配.平台不支持错误 as 错误:
        return 自检项("4.5", "平台适配.要求POSIX能力()", 结论_不支持,
                    f"本平台缺 POSIX 专有能力，函数按契约如实报『平台不支持』：{错误}",
                    为什么,
                    "依赖这些能力的调用点必须走跨平台实现（公共契约.运行时.进程终止）；"
                    "正确行为是报不支持，不是假装成功。",
                    详情)
    except Exception as 错误:  # noqa: BLE001
        return 自检项("4.5", "平台适配.要求POSIX能力()", 结论_不支持,
                    f"抛出的不是 平台不支持错误 而是 {type(错误).__name__}: {错误}（异常类型不对，调用方捕不到）",
                    为什么, "调用方的统一异常边界会漏掉这个异常类型，回收路径可能整条崩。", 详情)
    详情["实际能力"] = {"os.fork": hasattr(os, "fork"), "os.killpg": hasattr(os, "killpg"),
                     "os.getpgid": hasattr(os, "getpgid")}
    if not (hasattr(os, "fork") and hasattr(os, "killpg")):
        详情["不一致"] = "函数放行（非 Windows），但 os.fork/os.killpg 实际不存在"
        return 自检项("4.5", "平台适配.要求POSIX能力()", 结论_警告,
                    "函数按『非 Windows』放行，但本机实际缺 os.fork/os.killpg：平台判定与真实能力不符",
                    为什么, "平台判定为真但能力为假 → 调用点会拿到 AttributeError。第 6 项会实测暴露。",
                    详情)
    return 自检项("4.5", "平台适配.要求POSIX能力()", 结论_通过,
                "POSIX 专有能力放行（os.fork / os.killpg / os.getpgid 本机都在）",
                为什么, "", 详情)
