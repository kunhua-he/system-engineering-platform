"""调用点行为分叉的四个收口原语：多进程启动上下文 / 拆分命令文本 / 进程内存RSS字节 / 平台稳定缓存根，
外加 `经shell命令表`（`sh -c` 与 `cmd /c` 的平台语义差异）。"""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.平台适配.采样基元 import _读伪文件, 内存采样超时秒
from 公共契约.运行时.平台适配.判定 import (
    是Linux,
    是POSIX,
    是Windows,
    是macOS,
    当前平台,
)


# ── 调用点行为分叉的四个收口原语（2026-09-19 补）────────────────────
#
# 起因：第一轮《审计_平台判断越界_20260919》判出 3 处「调用点自己带平台分支」+
# 1 处「收口层之外的第三平台判定层」。判据是华哥 2026-09-16 裁决的**实质**口径
# （`开发文档/项目说明.md` §4 第 1065 行）：「调用点不许写平台判断；某处必须加平台
# 判断才能改通时，报回来补收口层，**不许就地分叉**」。
#
# 四处调用点即使只经本模块取平台值（`是Windows()` / `是macOS()` / `是POSIX()`），
# **分支动作仍由调用点自己决定** —— 那是「同一件事两种语义」的第二份实现，按哲学
# 第 8 条唯一性判定② 必须收敛成「同一份实现 + 模式变量」。故按审计件最小改法在
# **本模块**补四个原语，四处调用点只留一次取值：
#
#   B1-1 `任务进程.py`   → `多进程启动上下文()`（fork / spawn 选择）
#   B1-2 `进程管理.py`   → `拆分命令文本()`（shlex posix 口径）
#   B1-3 `容量基线.py`   → `进程内存RSS字节()`（ps vs /proc 取法）
#   B2-1 `运行缓存.py`   → `平台稳定缓存根()`（第三平台判定层，platform.system() 退场）
#
# 三态口径说明：`进程内存RSS字节()` 用返回值显名原因（`(0, 原因)`）而不是抛异常 ——
# 与 `内存容量信息()` 同款 **fail-closed**：它是**启动期容量基线**的采样路径，采样
# 失败绝不能拖垮启动；但**也不许把 0 当成真实读数**，调用方必须据 `原因` 显名降级。

#: macOS 进程信息命令候选绝对路径（按优先级；用绝对路径而不是 `shutil.which`，
#: 避免 PATH 被调用方进程污染后取到另一个同名可执行文件）
ps候选路径 = ("/bin/ps", "/usr/bin/ps")
#: Linux 进程状态伪文件目录（`/proc/<pid>/status` 的父目录）
Linux进程目录 = "/proc"
#: 平台级稳定缓存目录的应用子目录名（`平台稳定缓存根()` 的缺省应用名）
缺省缓存应用名 = "系统工程平台"


def 多进程启动上下文() -> tuple[Any, bool]:
    """返回 `(multiprocessing 上下文, 执行器是否必须显式序列化)`。

    - POSIX 优先 ``fork``：子进程继承父进程里**已注册的中文能力表**，执行器可直接传
      函数对象（第二个返回值 ``假``）；
    - 非 POSIX（Windows 上 ``multiprocessing`` **只有 spawn**）→ ``spawn``：子进程是
      全新解释器，执行器必须经 pickle 显式送达（第二个返回值 ``真``）；
    - **自称 POSIX 却不提供 fork 的受限构建** → 退回 ``spawn``，由执行器序列化补齐能力。

    **为什么必须收口在这里**：`get_context("fork")` 在 Windows 上抛 ``ValueError``
    —— 旧实现把这段选择留在调用点，一旦就地写错就把 `启动运行核心网关.py` 在**导入期**
    直接打死；而且 fork / spawn 直接决定「中文能力表能不能被继承」，是同一件事的两种
    语义，属哲学第 8 条② 必须「同一份实现 + 模式变量」的对象。

    ``multiprocessing`` 首次导入成本不低，故在本函数内**惰性导入**（本函数每个进程池
    只调一次，不落在导入期）。
    """
    import multiprocessing

    if 是POSIX():
        try:
            return multiprocessing.get_context("fork"), 假
        except ValueError:
            pass
    return multiprocessing.get_context("spawn"), 真


def _剥成对引号(项: str) -> str:
    """剥掉 `posix=False` 拆分留下的成对首尾引号（`"a b"` → `a b`）。"""
    if len(项) >= 2 and 项[0] == 项[-1] and 项[0] in ("'", '"'):
        return 项[1:-1]
    return 项


def 拆分命令文本(命令: str) -> list[str]:
    """把命令文本拆成参数表：POSIX 用 ``shlex.split()``，Windows 用 ``posix=False`` + 剥成对引号。

    **B-28（本仓实测坑）**：POSIX 模式下 ``shlex.split`` 把反斜杠当**转义符**，Windows
    路径 ``C:\\tools\\app.exe`` 会被拆成 ``C:oolsapp.exe``（``\\t`` / ``\\a`` 被吞）。
    因此：

    - Windows：``posix=False``（反斜杠是普通字符、引号由 shlex 保留）→ 再剥成对引号；
      真实最终引用由 ``subprocess``（``list2cmdline``）在启动时负责；
    - POSIX：保留 posix 语义（反斜杠就是转义符，与真实 shell 一致）；需要保留反斜杠的
      场景用引号包裹（``执行命令("echo 'C:\\\\tools\\\\app.exe'")``）。

    **为什么必须收口在这里**：`posix=` 口径是**平台语义差异**（同一份命令文本，两个平台
    的合法拆词结果不同），不是调用方的业务判断。留在调用点会让「执行命令」的入参解释
    随平台漂移，而对外契约里看不出来。

    非法引号等 `ValueError` **原样逸出**（不吞）：调用方按「参数不合法」处置，收口层
    不替调用方决定错误码。
    """
    if 是Windows():
        return [_剥成对引号(项) for 项 in shlex.split(命令, posix=False)]
    return shlex.split(命令)


def 经shell命令表(命令: str, 追加参数: list | None = None) -> list[str]:
    """把「一条 shell 命令串」包成**本平台 shell 解释器**的 argv（`经shell` 形态的唯一实现）。

    为什么必须收口在这里：`sh -c` 是 **POSIX 语法**，Windows 的等价物是 `cmd /c`；
    「同一份命令串该交给哪个解释器、用什么开关」是**平台语义差异**，不是调用方的业务判断。
    留在调用点（如 `进程管理.执行命令` 的 `经shell=真` 分支）会让「经 shell 执行」的含义
    随平台漂移，而对外契约里看不出来 —— 与 `拆分命令文本()` / `子进程组启动标志()`
    同一处置（2026-09-23 补 shell 形态时新增）。

    - POSIX：``["/bin/sh", "-c", 命令]``（``/bin/sh`` 是 POSIX 保证存在的路径，不依赖 PATH）
    - Windows：``[解释器, "/c", 命令]``，解释器取 ``COMSPEC``，缺失回退 ``cmd.exe``

    `追加参数` 原样拼在「解释器 + 开关 + 命令串」之后：POSIX 下成为 ``sh -c`` 脚本的
    ``$0``/``$1``…（只在调用方明确要传位置参数时才用；普通调用别传）。
    """
    if 是Windows():
        解释器 = os.environ.get("COMSPEC") or "cmd.exe"
        return [解释器, "/c", 命令] + list(追加参数 or [])
    return ["/bin/sh", "-c", 命令] + list(追加参数 or [])


def _macOS进程RSS字节(进程ID: int, ps命令: str | None) -> tuple[int, str]:
    """macOS 取法：``ps -o rss= -p <pid>``（**单位 KB**，本函数换算成字节）。

    失败原因按**真实阶段**分类，不把「ps 命令不在」与「该 pid 查不到」报成同一句话：
    前者要运维装/指对 ps，后者是进程已消失（同一句会把排查方向带偏）。
    """
    候选 = (ps命令,) if ps命令 else ps候选路径
    已试 = 0
    退出码非零 = 0
    for 路径 in 候选:
        if not Path(路径).is_file():
            continue
        已试 += 1
        try:
            完成 = subprocess.run([路径, "-o", "rss=", "-p", str(进程ID)],
                                 capture_output=True, text=True, timeout=内存采样超时秒)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if 完成.returncode != 0:
            退出码非零 += 1
            continue
        try:
            千字节 = int(完成.stdout.strip())
        except ValueError:
            continue
        if 千字节 < 0:
            continue
        return 千字节 * 1024, ""
    if 已试 == 0:
        return 0, f"ps 命令不可用（候选路径均不存在：{list(候选)}）"
    if 退出码非零:
        return 0, f"ps 查询失败（退出码非零：{进程ID} 可能已不存在或无权查询）"
    return 0, f"ps 输出不可解析为整数（候选：{list(候选)}）"


def _Linux进程RSS字节(进程ID: int) -> tuple[int, str]:
    """Linux 取法：``/proc/<pid>/status`` 的 ``VmRSS``（**单位 kB**，本函数换算成字节）。"""
    状态路径 = Path(Linux进程目录) / str(进程ID) / "status"
    if not 状态路径.is_file():
        return 0, f"读不到 {状态路径}（该 pid 不在 /proc，或无权限）"
    文本 = _读伪文件(str(状态路径))
    if 文本 is None:
        return 0, f"读不到 {状态路径}"
    for 行 in 文本.splitlines():
        if not 行.startswith("VmRSS:"):
            continue
        数字 = 行.split()[1:2]
        if not 数字:
            continue
        try:
            return int(数字[0]) * 1024, ""
        except ValueError:
            return 0, f"{状态路径} 的 VmRSS 不是整数：{数字[0]!r}"
    return 0, f"{状态路径} 无 VmRSS 字段"


def 进程内存RSS字节(进程ID: Any, *, ps命令: str | None = None) -> tuple[int, str]:
    """当前某个进程的常驻内存（RSS，**字节**）与失败原因：``(字节, "")`` / ``(0, 原因)``。

    三态 fail-closed 口径（与 `内存容量信息()` 同款）：

    - ``(字节, "")`` —— 采到了真实读数；
    - ``(0, 原因)`` —— **没采到**，`原因` 非空且必须被调用方显名（**不许**把 0 当真实读数，
      也不许把 ``支持=假`` 式的能力缺失伪装成「内存占用为零」）。

    取法（**平台差异的唯一落点**）：

    - macOS：``ps -o rss= -p <pid>``（KB → 字节）；
    - Linux：``/proc/<pid>/status`` 的 ``VmRSS``（kB → 字节）；
    - 其余平台（Windows 既无 ``ps`` 也无 ``/proc``）：显名 ``(0, 原因)``，不猜、不降级成
      别的语义。**注**：旧调用点把「非 macOS」当成「有 ``/proc``」，Windows 靠
      ``is_file()`` 兜底落进错误分支 —— 那是不收口留下的隐蔽风险，本函数按三分支显式判定。

    `ps命令` 是**取法覆盖**（运维/测试可指向另一个 ps 可执行文件），**只在 macOS 取法上
    生效**；其它平台的取法与 ``ps`` 命令无关，给了也如实不使用（不静默改变语义）。
    """
    if isinstance(进程ID, bool) or not isinstance(进程ID, int) or 进程ID <= 0:
        return 0, f"进程ID 非法（必须是正整数）：{进程ID!r}"
    if 是Windows():
        return 0, "本平台（Windows）既无 ps 也无 /proc，无标准库进程内存 RSS 取法"
    if 是macOS():
        return _macOS进程RSS字节(进程ID, ps命令)
    if 是Linux():
        return _Linux进程RSS字节(进程ID)
    return 0, f"平台 {当前平台()} 无标准库进程内存 RSS 取法"


def 平台稳定缓存根(应用名: str = 缺省缓存应用名,
                  环境: Mapping[str, str] | None = None) -> Path:
    """返回**不依赖制品安装路径**的平台级稳定缓存根：``<平台缓存目录>/<应用名>/运行缓存``。

    平台口径（**这是全仓唯一一处**；此前 `公共契约/运行时/运行缓存.py` 用
    ``platform.system()`` 硬判三平台，成了铁律点名的**第三处平台判定落点**，并造出
    「``当前平台()`` 给 ``macOS``、``platform.system()`` 给 ``Darwin``」两套平台名口径）：

    - Windows：``%LOCALAPPDATA%`` → ``%TEMP%`` → ``<用户目录>/AppData/Local``；
    - macOS：``$HOME/Library/Caches``；
    - 其余（Linux 及未列入的 POSIX，与旧实现的「非 Windows 非 Darwin」口径逐字一致）：
      ``$XDG_CACHE_HOME`` → ``$HOME/.cache``。

    `环境` 缺省取 ``os.environ``（供测试注入）；**只解析路径，不创建目录**（与
    `解析运行缓存根()` 同一纪律）。返回值**不做** ``expanduser()`` / ``resolve()``：
    那是调用方对「是否已是最终根」的决定，收口层不替调用方决定。
    """
    表 = os.environ if 环境 is None else 环境
    名称 = str(应用名 or "").strip() or 缺省缓存应用名
    if 是Windows():
        基础 = 表.get("LOCALAPPDATA") or 表.get("TEMP")
        if not 基础:
            基础 = str(Path.home() / "AppData" / "Local")
        return Path(基础) / 名称 / "运行缓存"
    if 是macOS():
        用户目录 = 表.get("HOME") or str(Path.home())
        return Path(用户目录) / "Library" / "Caches" / 名称 / "运行缓存"
    基础 = 表.get("XDG_CACHE_HOME")
    if 基础:
        return Path(基础) / 名称 / "运行缓存"
    用户目录 = 表.get("HOME") or str(Path.home())
    return Path(用户目录) / ".cache" / 名称 / "运行缓存"
