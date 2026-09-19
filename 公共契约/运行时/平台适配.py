"""跨平台平台适配：平台判定 / 虚拟环境解释器相对路径 / 子进程组启动标志。

背景（华哥 2026-09-16 裁决：底座做完整跨平台）：底座此前在 **Windows 11 / AMD64** 上
完全跑不起来，根因之一是「POSIX 布局被硬编码」——POSIX 的虚拟环境解释器是
``venv/bin/python3``，Windows 上真实布局是 ``venv/Scripts/python.exe``；POSIX 用
``start_new_session=True`` 开独立进程组，Windows 用 ``creationflags=CREATE_NEW_PROCESS_GROUP``。

本模块是**全平台唯一实现**（哲学第 8 条唯一性判定②：同一件事两种语义 → 同一份实现 +
模式变量）。后续批次把 6 处硬编码 ``bin/python3`` 与全部 ``start_new_session=True``
调用点切到本模块，调用点不再自带平台分支。

**设计约束**

1. **不引入第三方**：只用标准库（``sys`` / ``subprocess`` / ``platform`` / ``pathlib`` /
   ``re``）与**同一 ``公共契约`` 根内**的 `基础类型.逻辑类型`（中文逻辑字面量 `真`/`假`，
   见《类型目录》：正式代码一律从该模块取，不散写英文 ``True``/``False``）。
2. **平台判定在「调用时」读取** ``sys.platform``，不在导入时冻结——这样测试可以用
   monkeypatch 把整个模块切到 Windows 形态验证分支选择，也为将来可能的平台探测留口。
3. **平台不支持的能力显式报错**（``平台不支持错误``），绝不静默降级成别的语义。

**诚实标注：本模块的 Windows 分支未经真机实测**（开发机为 macOS）。Windows 分支的
判定逻辑仅通过 monkeypatch 模拟 ``sys.platform == "win32"`` 做过分支选择验证，
真实 Windows 上的行为需在 Windows 11 / AMD64 机器上复核。

**诚实标注（转写后端，2026-09-19 新增）**：`转写后端()` / `转写后端库名()` 的
**Windows / Linux → ``faster-whisper``** 这一支**同样未经真机实测** —— 开发机为 macOS，
本次只做了 monkeypatch 分支选择验证（``win32`` / ``linux`` / ``darwin`` 三态）。
真实 Windows / Linux 上的「依赖可装性 + 转写可用性」必须由真机取证补：
阿里云 Linux（x86_64 / Python 3.14）与 GitHub Actions Windows runner。
**不许把「代码写好了」当成「Windows / Linux 能跑了」**——那是把文档里的跨平台
误读成已验收的跨平台（与既有 Windows 分支同一诚实口径，见 README《当前支持矩阵》）。

**诚实标注（调用点行为分叉收口，2026-09-19 新增）**：本节四个新原语
（`多进程启动上下文()` / `拆分命令文本()` / `进程内存RSS字节()` / `平台稳定缓存根()`）的
**Windows / Linux 分支同样未经真机实测**（开发机为 macOS），只做了 monkeypatch 分支
选择验证（见 `测试中心/运行核心/测试_跨平台收口原语.py`）。它们的**POSIX / macOS 分支
是本机真跑**（fork 上下文、shlex posix 语义、`ps -o rss=`、`~/Library/Caches` 布局）。
真机取证仍待 GitHub Actions Windows runner 与阿里云 Linux。
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.诊断.忽略记录 import 记录忽略

平台表 = ("macOS", "Windows", "Linux", "未知")

#: POSIX 虚拟环境解释器相对路径（``python -m venv`` 的固定布局）
POSIX解释器相对路径 = "bin/python3"
#: Windows 虚拟环境解释器相对路径（``python -m venv`` 的固定布局）
Windows解释器相对路径 = "Scripts/python.exe"

#: POSIX 进程句柄枚举目录候选（按优先级）：Linux 走 ``/proc`` 伪文件系统，
#: macOS/BSD 走 ``/dev/fd`` 设备目录；两者都是「当前进程已打开句柄」的目录视图。
POSIX句柄目录表 = ("/proc/self/fd", "/dev/fd")

#: 微软 WinAPI ``CreateProcess`` 的 ``CREATE_NEW_PROCESS_GROUP`` 固定值（0x00000200）。
#: 真实 Windows 上 ``subprocess.CREATE_NEW_PROCESS_GROUP`` 恒存在；此处仅作极端缺失时的
#: 回退值——用官方文档固定值而非 0，避免默默丢掉「独立进程组」语义。
Windows新建进程组标志 = 0x00000200


class 平台不支持错误(RuntimeError):
    """调用方请求了当前平台不存在的能力。

    单独定义类型（而非抛 ``RuntimeError``/``AttributeError``）是为了让调用方能在统一的
    异常边界里精确捕获「平台不支持」，与「参数错误」「权限错误」区分开。
    """


def 原始平台标志() -> str:
    """返回 ``sys.platform`` 原始值（``darwin``/``win32``/``linux``…），仅用于诊断与日志。"""
    return sys.platform


def 本机系统名() -> str:
    """返回**归一化后的系统名稳定值**：``Darwin`` / ``Windows`` / ``Linux`` / ``未知``。

    这是 ``platform.system()`` 的**唯一取值点**（第一轮《审计_平台判断越界_20260919》
    §三 E-1）：全仓 8 处 ``platform.system()`` 裸取值一律改调本函数（#103 已实测替换），
    调用点不再自己读系统名，也不各自决定「macOS 写作 Darwin 还是 macOS」。

    **与 `当前平台()` 的关系**（两个口径并存是**有意的**，不是双口径）：

    · `当前平台()` —— **判断用**的人类可读名（``macOS``/``Windows``/``Linux``/``未知``），
      只读 ``sys.platform``，零系统调用；分支判定一律用它。
    · 本函数 —— **上报用**的稳定名，读 ``platform.system()`` 并归一化。为什么上报不能直接用
      `当前平台()`：既有落盘证据（`运行核心/环境指纹` 的 ``os`` 字段、`系统信息.获取操作系统信息`
      的 ``系统`` 字段、验证场景断言 ``"系统": "Darwin"``、`环境管理器.计算环境摘要` 的 ``os``
      字段（参与**受管环境目录名**））全部是 ``Darwin`` 这一取值，改成 ``macOS`` 会让全部既有
      证据失配、并把已构建的受管环境判成「摘要不符」。归一到 ``Darwin`` 是**零语义变化**的收口：
      macOS 上 ``platform.system()`` 本来就返回 ``Darwin``。

    **归一化规则**（只收敛写法变体，不做模糊匹配、不猜）：``darwin``/``mac os x`` 系 → ``Darwin``；
    ``windows`` 系 → ``Windows``；``linux`` 系 → ``Linux``；其余原值返回，空值 → ``未知``（fail-closed，
    不编造平台名）。

    **与 `运行核心/运行环境管理器/强制校验._归一化系统名` 的关系**：那一个是**历史锁兼容**
    补丁——它要处理的是**锁文件里**的历史写法（``macOS（Darwin 26.5.2）`` 带括号版本后缀、
    ``darwin``、``macos`` 三态混写），输入是不可控的落盘文本；本函数处理的是**本机真实系统名**，
    输入是 ``platform.system()`` 本身。两者**不是同一件事**：本函数是「本机系统名的唯一口径」，
    `_归一化系统名` 是「历史锁内的系统名写法归一」。有了本函数之后 `_归一化系统名` 的职责收窄为
    **只归一键内值**（本机侧不再经过它），但**不许直接删**——旧锁仍在库里，删了会让历史锁判不匹配。

    只依据 ``platform.system()``，不引入第三方、不派生进程。
    """
    名 = str(platform.system() or "").strip()
    if not 名:
        return "未知"
    小写 = 名.lower()
    if 小写.startswith("darwin") or 小写.startswith("mac"):
        return "Darwin"
    if 小写.startswith("win"):
        return "Windows"
    if 小写.startswith("linux"):
        return "Linux"
    return 名


def 当前平台() -> str:
    """返回人类可读的当前平台名：``macOS`` / ``Windows`` / ``Linux`` / ``未知``。

    只依据 ``sys.platform`` 判定，不调用 ``platform.system()``（后者有子进程/系统调用
    成本且在某些容器里返回宿主系统名），也不引入第三方。

    ``cygwin``/``freebsd`` 等未列入的平台返回 ``未知``——但 ``是POSIX()`` 仍为真，
    调用方应按能力探测（``hasattr(os, "killpg")``）而非按名字硬判。
    """
    标志 = sys.platform
    if 标志.startswith("win"):
        return "Windows"
    if 标志 == "darwin":
        return "macOS"
    if 标志.startswith("linux"):
        return "Linux"
    return "未知"


def 是Windows() -> bool:
    """是否 Windows（``sys.platform`` 以 ``win`` 开头，含 ``win32`` / ``win_amd64`` 等变体）。"""
    return sys.platform.startswith("win")


def 是macOS() -> bool:
    """是否 macOS（``sys.platform == "darwin"``）。"""
    return sys.platform == "darwin"


def 是Linux() -> bool:
    """是否 Linux（``sys.platform`` 以 ``linux`` 开头）。"""
    return sys.platform.startswith("linux")


def 是POSIX() -> bool:
    """是否 POSIX 系（非 Windows）。

    与 ``是Windows()`` 严格互补，保证两个分支「必有其一命中」，不留无主区间。
    """
    return not 是Windows()


def 虚拟环境解释器相对路径() -> str:
    """返回虚拟环境内解释器相对其根的路径（无前导分隔符）。

    POSIX → ``bin/python3``；Windows → ``Scripts/python.exe``。

    供后续批次替换 ``运行核心/运行环境管理器/环境管理器.py`` 第 323/410/619/683/684 行与
    ``强制校验.py`` 第 281 行的硬编码 ``目标 / "bin" / "python3"``。
    """
    if 是Windows():
        return Windows解释器相对路径
    return POSIX解释器相对路径


def 虚拟环境解释器路径(环境根: str | Path) -> Path:
    """把虚拟环境根目录拼成解释器的完整路径（只拼路径，不校验存在、不创建）。

    ``环境根`` 可以是 ``str`` 或 ``Path``；返回 ``Path``。是否真实存在由调用方用
    ``.is_file()`` 判定（现有调用点就是这么用的，见环境管理器第 684 行）。
    """
    return Path(环境根) / 虚拟环境解释器相对路径()


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


#: 正式支持矩阵（**准入唯一口径**）：平台名 → 该平台下**有真机证据**的架构元组。
#:
#: 只写实测/验收过的组合，不为未验收环境背书；未列入的平台或架构一律拒绝启动
#: （fail-closed，不静默降级）。
#:
#: 真机证据（2026-09-19，均可复跑：`gh workflow run cross-platform-deploy-verify.yml`）：
#:   - ``macOS / arm64``   —— 开发机 + GitHub Actions 干净 runner **双证**：
#:     环境自检 21/21、装配冒烟 699 能力 / 跳过 0。
#:   - ``Linux / x86_64``  —— GitHub Actions `ubuntu-latest` + 阿里云 ECS
#:     （Alibaba Cloud Linux 4）**双证**：环境自检 21/21、装配 699 / 跳过 0。
#:   - ``Windows / AMD64`` —— GitHub Actions `windows-latest`：装配 699 / 跳过 0；
#:     环境自检 10/21，其余 11 项**均为 Windows 本就没有的 POSIX 能力**
#:     （`os.fork` / 进程组号 / `preexec_fn` / `dir_fd` / `resource` / `/proc` / POSIX 信号），
#:     按契约如实报「不支持」，**不是缺陷**。
#:
#: **不在表内 = 没有证据**（如 macOS/x86_64、Linux/aarch64、Windows/ARM64 未实测），
#: 想放开必须先在该平台留下上面那套证据，再入表。
正式支持矩阵: dict[str, tuple[str, ...]] = {
    "macOS": ("arm64", "aarch64"),
    "Linux": ("x86_64",),
    "Windows": ("AMD64",),
}

#: Apple Silicon 架构表 —— **只用于 MLX/Metal 能力判定，不是准入表**。
#:
#: 必须与 ``正式支持矩阵`` 分开：MLX 运行时走 Metal，**仅 Apple Silicon 可用**；
#: Intel Mac / Linux / Windows 上结构性不可用（实测：Linux x86_64 装完整个闭包后
#: `import mlx.core` 仍恒报 `libmlx.so: cannot open shared object file`）。
#: 若直接复用准入矩阵，放开 Linux 后 Intel/Linux 机器会被误判成「可走 MLX」。
AppleSilicon架构表 = ("arm64", "aarch64")


def 当前架构() -> str:
    """返回 ``platform.machine()`` 的原始值（``arm64`` / ``x86_64`` …）；采样为空时返回空串。

    与 ``运行核心/环境指纹``、``运行核心/运行环境管理器`` 是同一份采样口径
    （依赖锁的 `环境.CPU` 字段就是它），故不另写第二套判定。
    """
    return str(platform.machine() or "").strip()


def 校验支持范围(用途: str = "") -> None:
    """要求当前环境在正式支持矩阵内；不在则抛 ``平台不支持错误``（fail-closed，不降级）。

    支持范围 = ``正式支持矩阵``（**准入唯一口径**）：每个平台名下只列**有真机证据**的架构。
    当前入表：macOS/arm64、Linux/x86_64、Windows/AMD64（证据见 ``正式支持矩阵`` 注释，
    均可由 `gh workflow run cross-platform-deploy-verify.yml` 复跑）。
    未列入的组合（macOS/x86_64、Linux/aarch64、Windows/ARM64…）一律**拒绝启动**：
    它们没有验收记录，静默放行等于把「文档里写了跨平台」当成「跨平台可用」。

    平台判断只在本模块做（跨平台收口层），调用点不得自己写 ``sys.platform`` /
    ``platform.machine()``。
    """
    平台名 = 当前平台()
    架构 = 当前架构()
    允许架构 = 正式支持矩阵.get(平台名, ())
    if 架构 in 允许架构:
        return
    场景 = f"（用途：{用途}）" if 用途 else ""
    入表说明 = "、".join(f"{名}/{'/'.join(架构表)}" for 名, 架构表 in 正式支持矩阵.items())
    raise 平台不支持错误(
        f"当前环境不在支持范围内{场景}：本平台当前支持 {入表说明}"
        f"（均为真机实测取证，见 README《当前支持矩阵》）；"
        f"当前环境为 {平台名} / {架构 or '架构未知'}（sys.platform={sys.platform!r}），"
        f"不在表内一律拒绝启动，不做静默降级。"
        f"若要在其它平台或架构运行，请先在该平台跑通并留下证据"
        f"（环境自检 + 装配冒烟 + 发布门禁，见 README《当前支持矩阵》），"
        f"再把该组合入表；不得以「文档里写了跨平台」代替实测。"
    )


def 脚本入口准入(用途: str) -> None:
    """脚本入口专用准入：不在支持范围内则**打印中文原因并以退出码 1 结束进程**。

    判定口径**完全来自** ``校验支持范围()`` —— 本函数不重复任何平台判断，
    只做「入口层」的翻译：把 ``平台不支持错误`` 转成**一句中文支持范围说明 + 退出码 1**。
    换平台的人因此拿到的是「只支持 macOS / arm64」，而不是某个底层 ``ImportError``
    （README《当前支持矩阵》对入口的承诺即指此）。

    **必须在任何装配导入之前调用**：换平台时项目内导入会先炸，准入放后面等于
    永远拿不到自己的报错。

    只接**会起服务 / 发起系统变更的顶层脚本入口**（如网关、MCP 薄壳、构建脚本、热接入）；
    只读工具与「换平台时正需要跑的自检工具」（``开发工具/环境自检.py``）**不接** ——
    把排查手段一起拦掉，等于换来平台的人拿到报错却失去诊断入口。
    """
    try:
        校验支持范围(用途=用途)
    except 平台不支持错误 as 错误:
        # flush：入口可能被外部限时拉起，不 flush 会在管道/重定向下丢掉这句唯一线索。
        print(f"启动被拒绝（环境准入不通过）：{错误}", flush=True)
        sys.exit(1)


def 要求POSIX能力(能力名: str) -> None:
    """显式要求当前平台具备某项 POSIX 专有能力；不满足即抛 ``平台不支持错误``。

    用于 ``os.killpg`` / ``os.getpgid`` / ``os.fork`` / ``resource`` 这类 Windows 上
    **根本不存在** 的能力——调用方要么走跨平台实现，要么明确报不支持，
    **不允许** 让 ``AttributeError`` 逸出或静默降级。
    """
    if 是Windows():
        raise 平台不支持错误(
            f"当前平台为 Windows，不支持 POSIX 专有能力「{能力名}」；"
            f"请改用 公共契约.运行时.进程终止 的跨平台实现"
        )


# ── 只读属性目录树删除（**同一件事的唯一实现**，哲学第 8 条唯一性判定②）──────
#
# 起因（2026-09-19 H 路收口）：POSIX 上父目录无写位（如 `0o555` 的中间目录）时，
# `shutil.rmtree` / `shutil.move` 会抛 `PermissionError`；Windows 上只读属性
# （`pip` 自带 license 文件就是）同样阻断删除。此前**每个调用点各写一份兜底**，
# 或干脆不写 —— 前者是第二份实现（哲学第 1.2 条），后者把失败留给用户。
#
# 本节的三个原语是**全仓唯一实现**：调用点一律改走它们，不许自带 `try/except chmod`
# 分叉。平台差异**不做平台名判断**，只用能力探测（`os.access(父, os.W_OK)`）与
# `os.chmod(..., stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)` —— 后者在 POSIX
# 上同样合法（清掉只读位不改变可删除性），故一份实现跨平台。

#: `清只读后删除树` 的留痕位置前缀（`记录忽略` 的位置串以它为根，供查询与门禁识别）
清只读删除留痕前缀 = "平台适配.清只读后删除树"


def 清除只读属性(路径: str | Path) -> None:
    """清掉路径（文件或目录）的只读属性；失败**原样报错**，不降级。

    **为什么需要它**：Windows 上 `venv` 建出来的环境里，`pip` 自带的 license
    文件（`Lib/site-packages/pip-*.dist-info/licenses/**`）带**只读属性**，
    `shutil.rmtree` 内部的 `os.unlink` 会抛 `PermissionError`（POSIX 上同样的文件
    能直接删，所以这是平台差异）。

    **一份实现跨平台**：`os.chmod(路径, stat.S_IWRITE)` 在 POSIX 上同样合法
    （清掉只读位不改变可删除性），因此本函数**不含任何平台判断**。
    """
    try:
        os.chmod(路径, stat.S_IWRITE)
    except OSError as 错误:
        raise OSError(f"清除只读属性失败（{路径}）: {错误}") from 错误


def _确保目录可写(目录: Path) -> None:
    """让**目录**可读可写可执行（在其中增/删/改名条目都需要）；已可写则不动。

    目录得同时可读可执行才谈得上遍历条目，不能只加写位 —— 这就是本函数与
    `清除只读属性`（对单个条目只清只读位）分开的原因。
    """
    if not os.access(目录, os.W_OK):
        os.chmod(目录, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)


def 确保可删(路径: str | Path) -> None:
    """让「删除 路径」这件事可做：清掉路径自身的只读位，并确保**父目录可写**。

    两件事都需要，缺一不可：

    - **路径自身只读**（Windows 只读属性 / POSIX 无写位）→ `os.unlink` 拒绝；
    - **父目录不可写**（POSIX 删除条目要求父目录有写位，`0o555` 的目录就删不掉
      里面的东西）→ `os.unlink`/`os.rmdir` 同样拒绝。

    平台差异用**能力探测**（`os.access(父, os.W_OK)`）而不是平台名判断，
    所以一份实现跨平台、调用点无分叉。
    """
    目标 = Path(路径)
    父目录 = 目标.parent
    if 父目录 != 目标:
        _确保目录可写(父目录)
    清除只读属性(目标)


def 移动并可删(源: str | Path, 目标: str | Path) -> None:
    """把 源 移动到 目标；只读属性/父目录无写位造成的 `PermissionError` 时先清只读再重试。

    **为什么需要它（`shutil.move` 与删除不是同一件事）**：改名要的是**源与落点的父目录**
    有写位，而不是「源文件自身可写」；所以这里**不清源文件自身的只读位**（对文件做
    `os.chmod(路径, stat.S_IWRITE)` 会把它的读/执行位一起抹掉，移动后权限被改，
    远超「修权限」的本意）。落点若已存在且只读（Windows 上 `MoveFileEx` 拒绝覆盖
    只读目标），则清它的只读位——它本来就要被替换掉。

    语义与 `清只读后删除树` 同款：默认**失败原样抛 `OSError`**（点名源与落点），
    不返回布尔、不吞异常；只在第一次真的抛 `PermissionError` 时才做上面两件事并重试一次。
    """
    源路径 = Path(源)
    目标路径 = Path(目标)
    落点 = (目标路径 / 源路径.name) if 目标路径.is_dir() else 目标路径

    try:
        shutil.move(str(源路径), str(目标路径))
        return
    except PermissionError as 首次错误:
        try:
            _确保目录可写(源路径.parent)
            _确保目录可写(落点.parent)
            if 落点.exists() and 落点.is_file():
                清除只读属性(落点)
            shutil.move(str(源路径), str(目标路径))
        except OSError as 重试错误:
            raise OSError(
                f"清只读后重试移动仍失败（{源路径} → {落点}）: {重试错误}") from 重试错误
        return
    except OSError as 错误:
        raise OSError(f"移动失败（{源路径} → {落点}）: {错误}") from 错误


def 清只读并确保可删(路径: str | Path) -> None:
    """让「删除 路径」可做（唯一实现的**薄别名**，语义与 `确保可删` 逐字相同）。

    存在的理由：`开发文档/未完成事项.md` 登记本项债务时把补口函数名写成
    `清只读并确保可删(路径) -> None`。为免「文档里的名字在实现里查不到」，
    这里按最小接口把它作为**别名**列出 —— 同一份实现，不是第二条腿。
    """
    确保可删(路径)


def 清只读后删除树(目录: Path, *, 忽略失败: bool = 假) -> None:
    """删除目录树；遇只读属性造成的 `PermissionError` 时先清只读再重试删除。

    判定依据不靠注释靠真实副作用：钩子只在 `rmtree` **真的**抛 `PermissionError`
    时才动。POSIX 上通常不触发（同样的文件在 POSIX 上能直接删），Windows 上由
    `os.unlink`/`os.rmdir` 触发，正是要修的那条路径。

    语义：

    - ``忽略失败=假``（默认）：清只读后仍失败就**原样抛出**，错误说明点名路径与原因
      —— 不许宽 `except` 吞错。
    - ``忽略失败=真``：逐条经 `记录忽略` 留痕（可查询），并**额外检查目录是否真的删干净**；
      残留同样留痕。这修掉了原先 `rmtree(..., ignore_errors=True)` 的缺陷：
      它**连残留都不留痕**，事后无法判断「本来就没东西」还是「删失败了」。
    """
    目录 = Path(目录)

    def _清只读后重试(函数, 路径, 异常) -> None:
        """rmtree 的 onexc 钩子：非 PermissionError 不越权处理，其余先清只读再重试。"""
        if not isinstance(异常, PermissionError):
            if 忽略失败:
                记录忽略(清只读删除留痕前缀, 异常)
                return
            raise 异常
        try:
            确保可删(路径)
            结果 = 函数(路径)
            if 函数 is os.scandir and 结果 is not None:
                结果.close()  # 官方配方会漏关的迭代器，这里显式关掉
        except OSError as 重试错误:
            if 忽略失败:
                记录忽略(清只读删除留痕前缀 + ".重试", 重试错误)
                return
            raise OSError(f"清只读后重试删除仍失败（{路径}）: {重试错误}") from 重试错误

    try:
        shutil.rmtree(目录, onexc=_清只读后重试)
    except OSError as 错误:
        if not 忽略失败:
            raise
        记录忽略(清只读删除留痕前缀, 错误)
    if 忽略失败 and 目录.exists():
        记录忽略(清只读删除留痕前缀 + ".残留",
                 f"删除流程已返回但目录仍在（有内容未删净）: {目录}")


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


# ── 转写后端选择（**同一份实现 + 模式变量**，哲学第 8 条②）──────────────
#
# 口径与依据（2026-09-19）：Apple Silicon（macOS + arm64）上 `mlx-whisper` 的 MLX
# 运行时走 **Metal**，是平台专有能力；其余平台（Windows / Linux）**结构性不可用** ——
# 阿里云 Linux x86_64 / Python 3.14 实测：`pip install mlx-whisper==0.4.3` 能把整个
# 闭包装完（含 torch 526MB），但 `import mlx.core` 恒报
# `ImportError: libmlx.so: cannot open shared object file: No such file or directory`
# （wheel 内只有 1 个 `.so`：`mlx/core.cpython-314-x86_64-linux-gnu.so`，
# **不存在 libmlx.so 文件**）⇒ 不是装依赖能解决的问题，只能在**后端**上分叉。
# 实测反向：`faster-whisper==1.2.1` 在 Linux x86_64 + Python 3.14 上可装可用
# （`ctranslate2` 4.8.2，不依赖 Metal）。
#
# **这是「同一份实现 + 模式变量」，不是第二条腿**（第 1.2① / 2.4① 内部第二执行腿：
# 禁止）：转写链路仍然只有一条 —— `支持库/后端/转写支持库/转写` 与
# `支持库/适配层/MLXWhisper提供者` 各一处子进程解析，两份都按本模块的 `转写后端()`
# 选后端；后端调用差异**吸收在子进程解析内部**，对外返回结构
# （`值.文本` / `值.语言` / `值.模型名` / `值.分段`）与全部错误码**逐字不变**，
# 调用方零改动。平台差异只在本模块判断（跨平台收口铁律：调用点不许写 `sys.platform`）。

#: 转写后端标识表：识别到的后端标识 → 该后端的适用平台口径（**别名/反查名**，供机器校验）。
转写后端标识表 = {
    "mlx": "Apple Silicon（macOS + arm64）专有：mlx-whisper 的 MLX 运行时走 Metal",
    "faster-whisper": "Windows / Linux（含非 arm64 的 macOS）：ctranslate2 后端，不依赖 Metal",
}

#: 后端标识 → 子进程内要加载的第三方模块名（**反查表**，供机器校验与实现侧取值）。
转写后端库名表 = {
    "mlx": "mlx_whisper",
    "faster-whisper": "faster_whisper",
}

#: 后端标识字面量（避免实现侧散写字符串；标识值本身是本模块对外契约，不得改字）
转写后端标识_MLX = "mlx"
转写后端标识_FASTER_WHISPER = "faster-whisper"


def 转写后端() -> str:
    """返回当前平台的转写后端标识：Apple Silicon → ``mlx``；其余平台 → ``faster-whisper``。

    判定依据（**全平台唯一一处**，调用点不得自己写 `sys.platform`）：
    `是否AppleSilicon()` 为真 → ``mlx``（用 `AppleSilicon架构表`，**不是**准入矩阵
    `正式支持矩阵`——MLX 只认 Apple Silicon，与「该平台有没有验收证据」是两回事）；
    其余一律 ``faster-whisper``。

    **为什么不是「不认识就抛异常」**：本函数是**后端选择器**，不是环境准入判据 ——
    准入仍由 `校验支持范围()` 负责（fail-closed，按 `正式支持矩阵` 放行）。这里回答的是
    「该加载哪个后端」，在 Windows / Linux 上给出 ``faster-whisper`` 是**正确结论**，
    不是静默降级（第 3.2 条）：真正的可用性由两件事实决定，本函数都不假装知道 ——
    ① 依赖锁按 `适用平台` 过滤后该后端的依赖是否装得上；② 子进程内真实 `import`
    是否成功。库装载不上就返回 `提供者不可用`，**绝不伪装可用、绝不模拟转写成功**。

    与 `平台表` 的对照：``macOS`` 但非 arm64（Intel Mac）返回 ``faster-whisper``
    —— MLX 需要 Apple Silicon，Intel Mac 上结构性不可用；故本函数与
    「Apple Silicon → mlx」严格互补，不留无主区间。

    **诚实标注：Windows / Linux 分支未经真机实测**（开发机为 macOS，仅做
    monkeypatch 分支选择验证；见模块文件头与 README《当前支持矩阵》）。
    """
    if 是否AppleSilicon():
        return 转写后端标识_MLX
    return 转写后端标识_FASTER_WHISPER


def 转写后端库名(后端标识: str = "") -> str:
    """把后端标识翻成子进程内要 ``import`` 的第三方模块名；**不认识的标识返回空串**。

    省略 `后端标识` 时取当前平台的 `转写后端()`。反查表 `转写后端库名表` 是唯一
    定义处，本函数是它的唯一取值出口（实现侧一处取值，不散写模块名字符串）。

    **不认识的标识返回空串**（fail-closed，不猜）：调用方据此明确报 `提供者不可用`；
    猜一个模块名去 import 会让错误码从「提供者不可用」漂成别的语义，违反第 3.2 条。
    """
    return 转写后端库名表.get((后端标识 or 转写后端()).strip(), "")


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


__all__ = [
    "平台表",
    "POSIX解释器相对路径",
    "Windows解释器相对路径",
    "POSIX句柄目录表",
    "Windows新建进程组标志",
    "平台不支持错误",
    "原始平台标志",
    "本机系统名",
    "当前平台",
    "是Windows",
    "是macOS",
    "是Linux",
    "是POSIX",
    "虚拟环境解释器相对路径",
    "虚拟环境解释器路径",
    "内存峰值原始单位",
    "句柄枚举目录表",
    "子进程组启动标志",
    "要求POSIX能力",
    "正式支持矩阵",
    "AppleSilicon架构表",
    "当前架构",
    "校验支持范围",
    "脚本入口准入",
    # 2026-09-18 H 簇补列：硬件画像采样的四个取法与 Apple Silicon 判定是**新公开原语**
    # （`支持库/适配层/硬件画像探针.py` 跨层调用它们），未列入 `__all__` 时型检会报
    # `reportAttributeAccessIssue`（运行时可用，但公开面自述与实际不符）。
    # 与 `进程终止.py` 补 `__all__` 同一处置：新原语必须同时进公开面。
    "内存容量信息",
    "物理核数信息",
    "处理器型号信息",
    "图形加速信息",
    "是否AppleSilicon",
    # 2026-09-19 转写后端选择（跨平台双后端）：`转写后端`/`转写后端库名` 是两处转写
    # 提供者的**新公开原语**（`支持库/适配层/MLXWhisper提供者` 与
    # `支持库/后端/转写支持库/转写` 的实现跨层调用它们），未列入 `__all__` 时型检会报
    # `reportAttributeAccessIssue`（运行时可用，但公开面自述与实际不符）——
    # 与 2026-09-18 硬件画像四原语补列同一处置：新原语必须同时进公开面。
    "转写后端标识表",
    "转写后端库名表",
    "转写后端标识_MLX",
    "转写后端标识_FASTER_WHISPER",
    "转写后端",
    "转写后端库名",
    # 2026-09-19 调用点行为分叉收口：`任务进程.py` / `进程管理.py` / `容量基线.py` /
    # `运行缓存.py` 四处调用点改调这四个新原语（跨层调用），同一处置 —— 必须进公开面。
    "多进程启动上下文",
    "拆分命令文本",
    "进程内存RSS字节",
    "平台稳定缓存根",
    "ps候选路径",
    "缺省缓存应用名",
    # 2026-09-19 H 路「含只读属性的目录树删除」收口：本模块是这三个原语的**唯一实现**
    # （`远程镜像` 改薄委托、全仓调用点改调它们）。未列入 `__all__` 时型检会报
    # `reportAttributeAccessIssue`（运行时可用，但公开面自述与实际不符）——
    # 与既有补列同一处置：新原语必须同时进公开面。
    "清只读删除留痕前缀",
    "清除只读属性",
    "确保可删",
    "清只读并确保可删",
    "清只读后删除树",
    "移动并可删",
]
