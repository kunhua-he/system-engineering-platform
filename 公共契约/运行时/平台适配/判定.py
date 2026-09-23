"""平台判定（跨平台收口层的**最底层**：全仓唯一允许读 `sys.platform` / `platform.*` 的地方）。"""

from __future__ import annotations

import platform
import sys


平台表 = ("macOS", "Windows", "Linux", "未知")


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


def 当前平台标识() -> str:
    """返回**平台标识全文**（``platform.platform()`` 的原文，如 ``macOS-26.6.2-arm64-arm-64bit``）。

    这是 ``platform.platform()`` 的**唯一取值点**（#175，2026-09-21）：调用点不得自己
    ``import platform`` 读平台标识。此前 `平台控制面/包仓库/物料清单.py` 裸调
    ``platform.platform()``，属「平台判断散落在调用点」，与 #103 是同一类病。

    **为什么单独有这个原语、而不是复用 `本机系统名()`**（三者职责不同，不是三套口径）：

    · `当前平台()`   —— **分支判定用**：只读 ``sys.platform``，零系统调用，
      取值 ``macOS`` / ``Windows`` / ``Linux`` / ``未知``；
    · `本机系统名()` —— **上报用稳定名**：读 ``platform.system()`` 并归一化，
      取值 ``Darwin`` / ``Windows`` / ``Linux`` / ``未知``；
    · 本函数         —— **平台标识全文**：读 ``platform.platform()``，**含版本号与架构**。

    为什么 SBOM 不能只用 `本机系统名()`：``物料清单.json`` 的 ``目标平台`` 是**构建证据字段**，
    要能区分「同是 Darwin 的 26.5.2 与 26.6.2」「同是 macOS 的 arm64 与 x86_64」——
    只留 ``Darwin`` 会让跨机器复现核对丢掉版本与架构两维。

    **不做归一化、不做二次拼装**：既有落盘值就是 ``platform.platform()`` 的原文，
    归一化会让全部既有 ``物料清单.json`` 失配（与 `本机系统名()` 同一「零语义变化」收口口径）。
    采样为空 → 空串（fail-closed，不编造平台标识）。
    """
    return str(platform.platform() or "").strip()


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


def 支持chmod() -> bool:
    """当前平台是否支持 **POSIX 权限位语义** 的 ``os.chmod``（POSIX 系 真 / Windows 假）。

    **为什么需要它**（#172，2026-09-21）：`平台控制面/包仓库/平台客户端制品.py` 的
    ``_加固密钥权限`` 此前自己写 ``except OSError: pass  # 平台不支持 chmod 时忽略（Windows 类）``
    —— 那是「调用点自带平台判断 + 静默吞错」两件事同时发生，违反
    「平台判断只许出现在收口层」铁律（调用点没有判据来源，只能靠异常兜）。

    **为什么不用能力探测**：``os.chmod`` 在 Windows 上**存在**（只处理 ``stat.S_IWRITE`` /
    ``stat.S_IREAD`` 两个位），``hasattr(os, "chmod")`` 恒为真，探不出差异；而
    ``0o700`` / ``0o600`` / ``0o644`` 这类**权限位组合**在 Windows 上无对应语义
    （ACL 不能经 ``os.chmod`` 设置）—— 故「支持不支持」只能按平台族判定。
    该判定**只在本模块做**（收口层），调用点只拿结论、不写平台判断。

    诚实标注：Windows 分支未经真机实测（开发机为 macOS），口径来自 ``os.chmod``
    官方文档（Windows 上仅支持只读位）。
    """
    return 是POSIX()
