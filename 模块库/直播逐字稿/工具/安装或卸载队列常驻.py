"""逐字稿队列常驻（LaunchAgent）安装 / 卸载 / 状态。

为什么要常驻：批量队列要跑十几小时，挂在 Hermes 会话的后台进程上会被会话变化 SIGTERM 打断；
LaunchAgent 由系统托管，异常退出自动拉起，机器重启也会回来；队列本身支持断点续跑，不重复劳动。

用法：
    python3.14 安装或卸载队列常驻.py 安装
    python3.14 安装或卸载队列常驻.py 卸载
    python3.14 安装或卸载队列常驻.py 状态
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

标签 = "com.huashi.zizhugao-queue"
工具目录 = Path("~/Documents/Hermes工作区/录音分析/直播逐字稿/工具")
源文件 = 工具目录 / f"{标签}.plist"
目标文件 = Path.home() / "Library" / "LaunchAgents" / f"{标签}.plist"
用户域 = f"gui/{os.getuid()}"
业务日志 = Path("~/Documents/Hermes工作区/录音分析/直播逐字稿/00_批量日志.log")


def 执行(命令: list[str]) -> tuple[int, str]:
    """跑一条命令，返回 (返回码, 输出)。"""
    完成 = subprocess.run(命令, capture_output=True, text=True)
    return 完成.returncode, (完成.stdout + 完成.stderr).strip()


def 安装() -> int:
    if not 源文件.is_file():
        print(f"缺 plist：{源文件}")
        return 1
    shutil.copy2(源文件, 目标文件)
    执行(["launchctl", "bootout", f"{用户域}/{标签}"])
    码, 输出 = 执行(["launchctl", "bootstrap", 用户域, str(目标文件)])
    if 码 != 0:
        print(f"装载失败：{输出}")
        return 1
    执行(["launchctl", "kickstart", "-k", f"{用户域}/{标签}"])
    print(f"已安装并启动：{标签}")
    print("  业务日志：", 业务日志)
    print("  系统输出：/tmp/逐字稿队列.log   系统错误：/tmp/逐字稿队列.err")
    print("  卸载：python3.14 安装或卸载队列常驻.py 卸载")
    return 0


def 卸载() -> int:
    执行(["launchctl", "bootout", f"{用户域}/{标签}"])
    if 目标文件.is_file():
        目标文件.unlink()
    print(f"已卸载：{标签}（已出的稿子与缓存都不受影响）")
    return 0


def 状态() -> int:
    码, 输出 = 执行(["launchctl", "print", f"{用户域}/{标签}"])
    if 码 != 0:
        print("未安装或未运行")
        return 1
    for 行 in 输出.splitlines():
        if any(键 in 行 for 键 in ("state =", "pid =", "runs =", "last exit")):
            print(" ", 行.strip())
    if 业务日志.is_file():
        尾部 = 业务日志.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
        print("  业务日志尾部：")
        for 行 in 尾部:
            print("   ", 行)
    return 0


if __name__ == "__main__":
    操作 = sys.argv[1] if len(sys.argv) > 1 else "状态"
    表 = {"安装": 安装, "卸载": 卸载, "状态": 状态}
    if 操作 not in 表:
        print("用法：python3.14 安装或卸载队列常驻.py [安装|卸载|状态]")
        sys.exit(2)
    sys.exit(表[操作]())
