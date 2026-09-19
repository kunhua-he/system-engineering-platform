"""第 5.2 项：真跑「优雅终止→宽限→强杀→复查」二级流程。

用一个**故意忽略 SIGTERM** 的子进程真跑：只有走完强杀升级并确认回收，才算这条流程
在本机成立（该流程是全仓进程回收的统一形状）。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from 开发工具.环境自检.基础 import 结论_不支持, 结论_通过, 自检项, _进程组启动参数


def 自检_强制结束真跑() -> 自检项:
    from 公共契约.运行时 import 平台适配, 进程终止

    为什么 = ("强制结束子进程 的『优雅终止 → 宽限 → 强杀 → 复查』二级流程是 41 处调用点的统一形状。"
              "本项用一个**故意忽略 SIGTERM** 的子进程真跑一遍：只有走完强杀升级并确认回收，"
              "才算这条流程在本机成立。")
    if not 平台适配.是POSIX():
        return 自检项("5.2", "收口层真跑：优雅→宽限→强杀升级", 结论_不支持,
                    f"平台 {平台适配.当前平台()} 无 POSIX 信号语义（SIGTERM/SIGKILL），"
                    f"二级流程无法在本机验证；该平台走 taskkill /F /T 整树终止",
                    为什么,
                    "Windows 分支从未真机验证（本仓已在模块 docstring 诚实标注）；"
                    "任务终止语义与 POSIX 不同，需真机复核。",
                    {"平台": 平台适配.当前平台()})
    临时 = Path(tempfile.mkdtemp(prefix="环境自检_回收_"))
    就绪文件 = 临时 / "就绪.txt"
    子: subprocess.Popen | None = None
    步骤: list[str] = []
    try:
        代码 = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"  # 故意忽略优雅终止
            "open(sys.argv[1], 'w').write('就绪')\n"
            "time.sleep(600)\n"
        )
        子 = subprocess.Popen(
            [sys.executable, "-c", 代码, str(就绪文件)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_进程组启动参数())
        步骤.append(f"1) 起了忽略 SIGTERM 的子进程：PID={子.pid}（等它就绪，避免抢跑成假通过）")
        截止 = time.monotonic() + 15
        while not 就绪文件.exists() and time.monotonic() < 截止 and 子.poll() is None:
            time.sleep(0.05)
        if not 就绪文件.exists():
            return 自检项("5.2", "收口层真跑：优雅→宽限→强杀升级", 结论_不支持,
                        "子进程 15 秒内没就绪（忽略 SIGTERM 的探针没起来），本项无法验证",
                        为什么, "探针自身没起来，不能拿它当通过。", {"步骤": 步骤})
        步骤.append("2) 子进程已就绪（信号处理器已装好）")
        结束 = 进程终止.强制结束子进程(子, 宽限秒=1.0, 等待秒=5.0)
        结论值 = ((结束.值 or {}).get("结论") if 结束.成功 else 结束.错误码)
        已使用强杀 = bool((结束.值 or {}).get("已使用强杀"))
        步骤.append(f"3) 强制结束子进程 → {结论值}（已使用强杀={已使用强杀}）："
                  f"{'；'.join((结束.值 or {}).get('说明表', [])) or 结束.错误说明}")
        if not 结束.成功 or 结论值 != 进程终止.结论_已终止 or not 已使用强杀:
            return 自检项("5.2", "收口层真跑：优雅→宽限→强杀升级", 结论_不支持,
                        f"二级流程不成立：结论={结论值!r}（期望 已终止）、已使用强杀={已使用强杀}",
                        为什么, "顽固子进程（忽略 SIGTERM）在本机回收不掉 → 是真实的进程泄漏。",
                        {"步骤": 步骤})
        步骤.append("4) 忽略 SIGTERM 的子进程被强杀升级并回收")
        子 = None
        return 自检项("5.2", "收口层真跑：优雅→宽限→强杀升级", 结论_通过,
                    "故意忽略 SIGTERM 的子进程走完『终止→宽限→强杀→复查』并确认回收",
                    为什么, "", {"步骤": 步骤})
    finally:
        if 子 is not None and 子.poll() is None:
            进程终止.强制结束子进程(子, 宽限秒=0.2, 等待秒=3.0)
        shutil.rmtree(临时, ignore_errors=True)
