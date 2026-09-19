"""第 6 项：POSIX 专有参数与调用（dir_fd= / preexec_fn / os.fork）真调真判。

三项都只影响明确的调用点（构建机路径防护、子进程资源上限、进程数上限探测），
在非 POSIX 平台应如实报【不支持】，而不是崩或假装成功。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from 开发工具.环境自检.基础 import 结论_不支持, 结论_通过, 自检项


def 自检_dirfd() -> 自检项:
    为什么 = ("`dir_fd=` / `src_dir_fd=` / `dst_dir_fd=` 是 POSIX 专有参数，Windows 上会"
              "`NotImplementedError`。`客户端/构建平台客户端.py` 用它做路径逃逸/符号链接竞态防护"
              "（os.mkdir/os.open/os.stat/os.replace/os.unlink 全程带 dir_fd），是**构建机**工具。")
    详情 = {"os.supports_dir_fd 可用": hasattr(os, "supports_dir_fd"),
            "open 支持 dir_fd": bool(os.open in os.supports_dir_fd)
            if hasattr(os, "supports_dir_fd") else None}
    临时 = Path(tempfile.mkdtemp(prefix="环境自检_dirfd_"))
    try:
        目录fd = os.open(临时, os.O_RDONLY)
        try:
            名字 = "探针文件.txt"
            文件fd = os.open(名字, os.O_CREAT | os.O_WRONLY, 0o644, dir_fd=目录fd)
            os.close(文件fd)
            状态 = os.stat(名字, dir_fd=目录fd, follow_symlinks=False)
            os.replace(名字, 名字, src_dir_fd=目录fd, dst_dir_fd=目录fd)  # 同源同目标，不改内容
            os.unlink(名字, dir_fd=目录fd)
            详情["实测"] = "os.open/os.stat/os.replace/os.unlink 带 dir_fd 全部成功"
            详情["文件大小"] = 状态.st_size
        finally:
            os.close(目录fd)
    except (NotImplementedError, TypeError, AttributeError, OSError) as 错误:
        详情["实测异常"] = f"{type(错误).__name__}: {错误}"
        return 自检项("6.1", "POSIX 专有参数 dir_fd=", 结论_不支持,
                    f"本平台不可用：{type(错误).__name__}: {错误}",
                    为什么,
                    "只影响**构建机**工具（客户端/构建平台客户端.py：打包平台客户端制品）；"
                    "平台本体的装配与运行不受影响。要出制品请在本机改造成不带 dir_fd 的走路（或换 POSIX 机器构建）。",
                    详情)
    finally:
        shutil.rmtree(临时, ignore_errors=True)
    return 自检项("6.1", "POSIX 专有参数 dir_fd=", 结论_通过,
                "os.open/os.stat/os.replace/os.unlink 带 dir_fd 实测通过", 为什么, "", 详情)


def 自检_preexec_fn() -> 自检项:
    为什么 = ("`preexec_fn` 也是 POSIX 专有（Windows 上 Popen 直接 `ValueError: preexec_fn is not "
              "supported on Windows platforms`）。仓库两处真调用：`平台控制面/提供者/资源硬限制.py`"
              "（用它在子进程内施加 CPU/文件大小/进程数 RLIMIT 上限）、"
              "`技能库/后端/技能库/实现/技能库.py`（技能执行的资源预算）。")
    子 = None
    try:
        子 = subprocess.Popen(
            # 故意用 preexec_fn：本项要验的就是「本平台到底支不支持它」，
            # 不是要真施加资源限制（多线程下它不安全，这也是仓库里两处真调用点的已知约束）。
            [sys.executable, "-c", "pass"], preexec_fn=lambda: None,  # noqa: PLW1509
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (ValueError, NotImplementedError, OSError) as 错误:
        return 自检项("6.2", "POSIX 专有参数 preexec_fn=", 结论_不支持,
                    f"本平台不可用：{type(错误).__name__}: {错误}",
                    为什么,
                    "资源上限（RLIMIT）无法在子进程内施加 → 资源硬限制在 Windows 上不可强制"
                    "（该模块自己也有『如实报告不可强制』的口径）。",
                    {"异常类型": type(错误).__name__, "异常": str(错误)})
    try:
        退出码 = 子.wait(timeout=30)
    except subprocess.TimeoutExpired:
        子.kill()
        return 自检项("6.2", "POSIX 专有参数 preexec_fn=", 结论_不支持,
                    "带 preexec_fn 的子进程 30 秒没退出（父进程路径不可靠）",
                    为什么, "子进程启动路径不可靠 → 资源受限子进程可能挂住装配/调用。", {})
    return 自检项("6.2", "POSIX 专有参数 preexec_fn=", 结论_通过,
                f"带 preexec_fn 的 Popen 真起子进程并回收（退出码 {退出码}）", 为什么, "",
                {"退出码": 退出码})


def 自检_os_fork() -> 自检项:
    为什么 = ("`os.fork` 在 Windows 上不存在。真调用点是 `平台控制面/提供者/资源硬限制.py`"
              "的 RLIMIT_NPROC 强制探测（fork 被 EAGAIN 拒绝才算上限生效）；"
              "该函数自己按 `hasattr(os, \"fork\")` 如实返回探测不通过。")
    if not hasattr(os, "fork"):
        return 自检项("6.3", "POSIX 专有 os.fork", 结论_不支持,
                    "本平台没有 os.fork（Windows 无 fork 概念）",
                    为什么, "RLIMIT_NPROC 不可强制（探测如实报不通过，不是缺陷）。",
                    {"hasattr os.fork": False, "hasattr os.killpg": hasattr(os, "killpg")})
    try:
        子进程号 = os.fork()
    except OSError as 错误:
        return 自检项("6.3", "POSIX 专有 os.fork", 结论_不支持,
                    f"os.fork 存在但调用失败：{type(错误).__name__}: {错误}",
                    为什么, "fork 不可用 → RLIMIT_NPROC 无法验证。",
                    {"异常类型": type(错误).__name__, "异常": str(错误)})
    if 子进程号 == 0:
        os._exit(0)  # 子进程：立刻退出，不碰父进程的任何缓冲区
    os.waitpid(子进程号, 0)
    return 自检项("6.3", "POSIX 专有 os.fork", 结论_通过,
                f"真 fork 出一个子进程并 waitpid 回收（子进程号 {子进程号}）", 为什么, "",
                {"子进程号": 子进程号, "hasattr os.killpg": hasattr(os, "killpg")})
