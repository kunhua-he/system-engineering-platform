"""跨平台进程组终止：把「终止进程组 / 进程存活」收口为唯一实现，异常全部转明确结果。

背景（华哥 2026-09-16 裁决：底座做完整跨平台）：底座 **41/42 个文件** 直接调用
``os.killpg`` / ``signal.SIGKILL`` / ``os.fork``，这些在 Windows 上**不存在**；且多数
``except`` 元组不含 ``AttributeError`` → 进程不回收，异常还会逃出统一结果。本模块把
「终止」与「存活判定」各收成一份跨平台实现，后续批次逐个替换调用点。

**对外契约（关键）**

- 公开函数**永不抛异常**：``AttributeError`` / ``ProcessLookupError`` / ``PermissionError`` /
  ``OSError`` / ``subprocess`` 各类失败一律收口成 ``结果``（失败时错误码 + 中文说明），
  调用方只需看 ``结果.成功``。
- **幂等**：目标进程已不存在时视为**成功**（结论 ``进程不存在``），不报错——回收逻辑
  可以放心重复跑。
- **无权限**（``PermissionError``，典型：不在同一用户下的进程）是**明确失败**，错误码
  ``无权限``，绝不当成功；也不静默降级成「已清理」。
- **不静默降级**：平台能力缺失时给出 ``不支持``/``终止失败`` 与具体原因，而不是假装成功。

**平台分支**

- POSIX：``os.getpgid`` 判组长身份 → 是组长用 ``os.killpg`` 整组终止，**不是组长**时退化
  为 ``os.kill`` 单进程（避免误伤同组其他进程）。
- Windows：``taskkill /F /T /PID`` 按父子关系终止整棵进程树；``taskkill`` 不可用时
  回退 ``os.kill(pid, SIGTERM)``（Windows 上语义即 ``TerminateProcess``）**并在说明里
  如实写明该回退及其局限**，不伪装成整组终止。

**诚实标注：本模块的 Windows 分支未经真机实测**（开发机为 macOS）。Windows 分支仅通过
monkeypatch 模拟 ``sys.platform == "win32"`` + 伪 ``taskkill`` 返回值验证了分支选择与
结果收口，真实 Windows 11 / AMD64 上的行为需真机复核。
"""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import time
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

来源 = "进程终止"

#: 终止宽限秒：先「终止」（POSIX SIGTERM / Windows taskkill 不带 /F）后等这么久
终止宽限秒 = 1.0
#: 默认等待上限：强杀后等进程消失的总时长
默认等待秒 = 5.0
#: 存活轮询间隔
轮询间隔秒 = 0.05

信号表 = ("终止", "强杀")

结论_已终止 = "已终止"
结论_已终止_回退 = "已终止（回退）"
结论_进程不存在 = "进程不存在"
结论_无权限 = "无权限"
结论_不支持 = "不支持"
结论_参数错误 = "参数错误"
结论_终止失败 = "终止失败"
结论_仍存活 = "仍存活"

# Windows 进程存活探测用的 WinAPI 常量（微软文档固定值）
_Windows同步访问 = 0x00100000  # SYNCHRONIZE
_Windows等待超时 = 0x00000102  # WAIT_TIMEOUT
_Windows拒绝访问 = 5  # ERROR_ACCESS_DENIED


# --------------------------------------------------------------------------- #
# 内部：把已知异常收成 (结论, 说明)，不抛
# --------------------------------------------------------------------------- #

def _失败结果(
    错误码: str, 消息: str, *, 详情: dict[str, Any] | None = None
) -> 结果[dict[str, Any]]:
    return 结果.失败(
        错误码, 消息, 来源=来源, 可重试=(错误码 == 结论_终止失败), 详情=详情 or {}
    )


def _组装(
    结论: str, 进程ID: int, 信号: str, 说明: str, *, 已发出信号: bool
) -> 结果[dict[str, Any]]:
    """把 (结论, 说明) 组装成 ``结果``：成功类结论走成功结果，失败类结论走失败结果。"""
    值 = {
        "结论": 结论,
        "进程ID": 进程ID,
        "信号": 信号,
        "平台": _当前平台名(),
        "已发出信号": 已发出信号,
        "说明": 说明,
    }
    if 结论 in (结论_已终止, 结论_已终止_回退, 结论_进程不存在):
        return 结果.成功结果(值)
    return _失败结果(结论, 说明, 详情=值)


def _当前平台名() -> str:
    # 延迟导入：避免上游包初始化顺序问题（平台适配本身无依赖，此处只为稳妥）
    from 公共契约.运行时.平台适配 import 当前平台

    return 当前平台()


def _是Windows() -> bool:
    from 公共契约.运行时.平台适配 import 是Windows

    return 是Windows()


def _是POSIX() -> bool:
    from 公共契约.运行时.平台适配 import 是POSIX

    return 是POSIX()


def _Windows内核() -> Any:
    """取 ``kernel32`` 句柄；ctypes/WinAPI 不可用时抛 ``平台不支持错误``（显式，不静默）。

    单独抽函数是为了让测试可以 monkeypatch ``ctypes.windll`` 模拟 Windows。
    """
    import ctypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        from 公共契约.运行时.平台适配 import 平台不支持错误

        raise 平台不支持错误("当前环境无 ctypes.windll，无法调用 Windows 进程存活探测")
    return windll.kernel32


# --------------------------------------------------------------------------- #
# 进程存活
# --------------------------------------------------------------------------- #

def 进程存活(进程ID: int) -> bool:
    """跨平台判定进程是否存在（True 表示存在）。

    - POSIX：``os.kill(pid, 0)``——存在返回 True；``ProcessLookupError`` → False；
      ``PermissionError`` → True（进程存在但无权限发信号）。
    - Windows：``OpenProcess(SYNCHRONIZE)`` + ``WaitForSingleObject``——**绝不能**用
      ``os.kill(pid, 0)``：Windows 上 ``os.kill`` 对非控制台信号走 ``TerminateProcess``，
      会真的把目标**杀掉**。

    语义边界（如实说明）：**僵尸进程计为存活**（POSIX 下 ``os.kill(pid, 0)`` 对僵尸仍成功），
    这是本函数作为「纯谓词」的诚实语义。要判「死透并回收」，请用 ``subprocess.Popen.poll()``
    （句柄路径）或让 ``强制结束子进程`` / ``等待进程消失`` 处理（裸进程号路径下它们会先
    ``waitpid`` 回收自有子进程）。

    非法入参（非整数 / 布尔 / ≤0）一律返回 False，不抛异常。

    唯一的显式报错情形：环境自称 Windows（``sys.platform`` 以 ``win`` 开头）却取不到
    ``ctypes.windll``——真实 Windows 上不可能发生，属环境损坏。此时抛 ``平台不支持错误``
    而**不**静默返回 False（返回 False 会把活着的进程谎报成「不存在」，是危险的静默降级）。
    """
    if isinstance(进程ID, bool) or not isinstance(进程ID, int) or 进程ID <= 0:
        return False
    if _是Windows():
        return _Windows进程存活(进程ID)
    return _POSIX进程存活(进程ID)


def _POSIX进程存活(进程ID: int) -> bool:
    try:
        os.kill(进程ID, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as 错误:
        # 个别平台把 ESRCH/EPERM 以裸 OSError 抛出
        if 错误.errno == errno.ESRCH:
            return False
        if 错误.errno == errno.EPERM:
            return True
        return False
    except AttributeError:
        # 理论上不可达（POSIX 必有 os.kill）；显式收口而不是让异常逸出
        return False


def _Windows进程存活(进程ID: int) -> bool:
    """Windows 存活探测：句柄可开且未进入已结束态即为存活。

    ``OpenProcess`` 失败时用 ``GetLastError`` 区分「不存在」与「拒绝访问」：
    拒绝访问说明进程确实在（只是我们没权限），必须报存活，不能当成已退出。
    """
    内核 = _Windows内核()
    句柄 = 内核.OpenProcess(_Windows同步访问, False, 进程ID)
    if not 句柄:
        错误码 = _取Windows最后错误(内核)
        return 错误码 == _Windows拒绝访问
    try:
        等待结果 = 内核.WaitForSingleObject(句柄, 0)
    finally:
        内核.CloseHandle(句柄)
    return 等待结果 == _Windows等待超时


def _取Windows最后错误(内核: Any) -> int:
    取错误 = getattr(内核, "GetLastError", None)
    if 取错误 is None:
        return 0
    try:
        return int(取错误())
    except (TypeError, ValueError):
        # 伪句柄/模拟内核可能不支持，按「未知错误」处理（调用方按不存在收口）
        return 0


def _回收自有子进程(进程ID: int) -> bool:
    """POSIX：若该 PID 是**本进程**的子进程且已变成僵尸，立即回收（``waitpid WNOHANG``）。

    返回是否完成回收（True 即该 PID 已从系统消失）。

    **为什么必须有这一步**：``强制结束子进程`` 接受裸 ``int`` 进程号时，调用方通常没有
    ``Popen`` 句柄可 ``poll()``；子进程被信号杀死后不会自己消失，而是变成**僵尸等待父进程
    回收**，而 ``进程存活``（对僵尸返回 True，这是它如实的语义）就会一直报「活着」，导致
    本该成功的回收被误判为 ``仍存活``。既然调用方把裸进程号交给我们，回收责任就在我们。

    安全性：``waitpid`` 只对**自有子进程**有效；目标不是自有子进程时抛
    ``ChildProcessError`` → 返回 False，不会误伤别人的进程。Windows 无 ``os.waitpid``
    也返回 False（Windows 无僵尸概念，不需要此步）。
    """
    if not hasattr(os, "waitpid"):
        return False
    try:
        已回收PID, _状态 = os.waitpid(进程ID, os.WNOHANG)
    except ChildProcessError:
        return False
    except OSError as 错误:
        if 错误.errno == errno.ECHILD:
            return False
        return False
    return 已回收PID == 进程ID


def 等待进程消失(进程ID: int, 超时秒: float = 默认等待秒) -> bool:
    """轮询等待进程消失；返回是否已消失（超时返回 False）。不抛异常。"""
    if isinstance(超时秒, bool) or not isinstance(超时秒, (int, float)) or 超时秒 < 0:
        return False
    截止 = time.monotonic() + float(超时秒)
    while True:
        if not 进程存活(进程ID):
            return True
        if time.monotonic() >= 截止:
            return False
        time.sleep(轮询间隔秒)


# --------------------------------------------------------------------------- #
# 终止进程组
# --------------------------------------------------------------------------- #

def 终止进程组(进程ID: int, *, 信号: str = "强杀") -> 结果[dict[str, Any]]:
    """终止进程（POSIX 整组 / Windows 整树），返回 ``结果``，**永不抛异常**。

    入参
        ``进程ID``：目标进程号；必须是正整数（布尔/浮点/字符串拒绝，不做静默转换）。
        ``信号``：``"强杀"``（默认，POSIX SIGKILL / Windows ``taskkill /F``）
                  或 ``"终止"``（POSIX SIGTERM / Windows ``taskkill`` 不带 ``/F``）。

    返回
        ``结果.值`` 为字典：``{结论, 进程ID, 信号, 平台, 已发出信号, 说明}``。
        成功类结论：``已终止`` / ``已终止（回退）`` / ``进程不存在``（幂等）。
        失败类结论：``无权限`` / ``不支持`` / ``参数错误`` / ``终止失败``（错误码即结论）。

    注意：本函数**只发信号 / 只发终止命令，不等待、不验证进程真的消失**。要「确认死透」
    请配合 ``等待进程消失``，或直接用 ``强制结束子进程``（内置等待与复查）。
    """
    if 信号 not in 信号表:
        return _失败结果(结论_参数错误, f"信号必须是 {信号表} 之一，收到: {信号!r}")
    if isinstance(进程ID, bool) or not isinstance(进程ID, int) or 进程ID <= 0:
        return _失败结果(
            结论_参数错误,
            f"进程ID 必须是正整数，收到 {type(进程ID).__name__}: {进程ID!r}",
        )

    强杀 = 信号 == "强杀"
    try:
        if _是Windows():
            结论, 说明 = _Windows终止进程组(进程ID, 强杀=强杀)
        elif hasattr(os, "killpg"):
            结论, 说明 = _POSIX终止进程组(进程ID, 强杀=强杀)
        else:
            # 既非 Windows 又无 os.killpg：明确报不支持，不给「已清理」的假象
            结论, 说明 = (
                结论_不支持,
                f"平台 {sys.platform} 既非 Windows 也无 os.killpg，无法终止进程组",
            )
    except Exception as 错误:  # noqa: BLE001
        # 显式收口（不是静默兜底）：异常类型与内容都进「说明」和详情，调用方看得见
        结论 = 结论_终止失败
        说明 = f"终止进程组时出现未预期异常 {type(错误).__name__}: {错误}"
    return _组装(
        结论, 进程ID, 信号, 说明, 已发出信号=结论 in (结论_已终止, 结论_已终止_回退)
    )


def _POSIX终止进程组(进程ID: int, *, 强杀: bool) -> tuple[str, str]:
    """POSIX 分支：组长用 killpg 整组，非组长退化为单进程 kill。返回 (结论, 说明)。"""
    信号号 = signal.SIGKILL if 强杀 else signal.SIGTERM
    信号名 = "SIGKILL" if 强杀 else "SIGTERM"
    try:
        组号 = os.getpgid(进程ID)
    except ProcessLookupError:
        return (结论_进程不存在, f"PID {进程ID} 不存在（取进程组失败），无需终止")
    except PermissionError:
        return (结论_无权限, f"无权查询 PID {进程ID} 的进程组，无法终止")
    except OSError as 错误:
        if 错误.errno == errno.ESRCH:
            return (结论_进程不存在, f"PID {进程ID} 不存在（{错误}）")
        if 错误.errno == errno.EPERM:
            return (结论_无权限, f"无权查询 PID {进程ID} 的进程组（{错误}）")
        return (结论_终止失败, f"取 PID {进程ID} 进程组失败: {错误.strerror or 错误}")
    except AttributeError as 错误:
        # os.getpgid 在 Windows 上不存在——走到这里说明平台判定与实际不符
        return (结论_不支持, f"当前环境缺少 os.getpgid: {错误}")

    if 组号 == 进程ID:
        目标 = os.killpg
        描述 = f"进程组 {进程ID}（组长即目标）"
    else:
        目标 = os.kill
        描述 = f"单进程 {进程ID}（非组长，组号 {组号}，不整组以免误伤同组进程）"
    try:
        目标(进程ID, 信号号)
        return (结论_已终止, f"已向{描述}发送 {信号名}")
    except ProcessLookupError:
        return (结论_进程不存在, f"{描述} 已不存在，{信号名} 未生效（幂等）")
    except PermissionError:
        return (结论_无权限, f"无权向{描述}发送 {信号名}")
    except OSError as 错误:
        if 错误.errno == errno.ESRCH:
            return (结论_进程不存在, f"{描述} 已不存在（{错误}）")
        if 错误.errno == errno.EPERM:
            return (结论_无权限, f"无权向{描述}发送 {信号名}（{错误}）")
        return (结论_终止失败, f"向{描述}发送 {信号名} 失败: {错误.strerror or 错误}")
    except AttributeError as 错误:
        return (结论_不支持, f"当前环境缺少所需终止接口: {错误}")


def _Windows终止进程组(进程ID: int, *, 强杀: bool) -> tuple[str, str]:
    """Windows 分支：``taskkill``（强杀加 ``/F``）终止整棵进程树。返回 (结论, 说明)。"""
    参数 = ["taskkill"]
    if 强杀:
        参数.append("/F")
    参数 += ["/T", "/PID", str(进程ID)]
    动作 = "taskkill /F /T" if 强杀 else "taskkill /T"
    try:
        运行 = subprocess.run(
            参数, capture_output=True, text=True, timeout=默认等待秒, check=False
        )
    except FileNotFoundError:
        return _Windows回退单进程(进程ID)
    except subprocess.TimeoutExpired:
        return (
            结论_终止失败,
            f"{动作} 超时（{默认等待秒} 秒）未返回，PID {进程ID} 状态未知",
        )
    except (OSError, subprocess.SubprocessError) as 错误:
        return (结论_终止失败, f"{动作} 无法执行: {type(错误).__name__}: {错误}")

    输出 = ((运行.stdout or "") + (运行.stderr or "")).strip()
    if 运行.returncode == 0:
        尾巴 = f"：{输出}" if 输出 else ""
        return (结论_已终止, f"{动作} 已终止 PID {进程ID} 的进程树{尾巴}")
    小写 = 输出.lower()
    无实例标记 = ("no running instance", "not found", "找不到", "没有运行")
    if 运行.returncode == 128 or any(标记 in 小写 for 标记 in 无实例标记):
        return (
            结论_进程不存在,
            f"PID {进程ID} 无运行实例（{动作} 退出码 {运行.returncode}）",
        )
    无权限标记 = ("access is denied", "拒绝访问", "access denied")
    if 运行.returncode == 5 or any(标记 in 小写 for 标记 in 无权限标记):
        return (结论_无权限, f"无权终止 PID {进程ID}（{动作} 退出码 {运行.returncode}）")
    return (结论_终止失败, f"{动作} 退出码 {运行.returncode}：{输出 or '无输出'}")


def _Windows回退单进程(进程ID: int) -> tuple[str, str]:
    """``taskkill`` 不可用时的回退：``os.kill``。

    Windows 上没有 ``signal.SIGKILL``，且 ``os.kill`` 对非控制台信号走 ``TerminateProcess``
    ——语义上等同强制结束，但**不会**顺带回收子进程树。说明里如实写明，不伪装成整树终止。
    """
    信号号 = getattr(signal, "SIGTERM", 15)
    try:
        os.kill(进程ID, 信号号)
    except ProcessLookupError:
        return (
            结论_进程不存在,
            f"PID {进程ID} 不存在（taskkill 不可用时的回退路径，幂等）",
        )
    except PermissionError:
        return (结论_无权限, f"无权终止 PID {进程ID}（taskkill 与 os.kill 均无权限）")
    except AttributeError as 错误:
        return (结论_不支持, f"当前环境缺少 os.kill: {错误}")
    except OSError as 错误:
        return (结论_终止失败, f"os.kill 终止 PID {进程ID} 失败: {错误.strerror or 错误}")
    return (
        结论_已终止_回退,
        f"taskkill 不可用，已回退 os.kill(SIGTERM) 终止 PID {进程ID}"
        f"（Windows 语义为强制结束，但不保证回收子进程树）",
    )


# --------------------------------------------------------------------------- #
# 后续批次主入口：结束子进程（优雅 → 宽限 → 强杀 → 复查死透）
# --------------------------------------------------------------------------- #

def 强制结束子进程(
    进程: subprocess.Popen | int,
    *,
    宽限秒: float = 终止宽限秒,
    等待秒: float = 默认等待秒,
) -> 结果[dict[str, Any]]:
    """结束子进程并确认死透：``终止`` → 宽限等待 → ``强杀`` → 等待 → 复查。

    这是给后续批次的**统一接入形状**：现有 41 处调用点几乎都是
    「SIGTERM → wait(宽限) → SIGKILL → wait」这套手工流程，直接换成一次本调用即可，
    调用点不再出现 ``os.killpg`` / ``os.getpgid`` / ``signal.SIGKILL`` / ``start_new_session``。

    入参
        ``进程``：``subprocess.Popen`` 句柄 **或** ``int`` 进程号。两种入参都会**回收僵尸**：
                  传 ``Popen`` 走 ``poll()``/``wait()``；传 ``int`` 时若是本进程的自有子进程，
                  走 ``os.waitpid(WNOHANG)``（见 ``_回收自有子进程``）。**非**自有子进程无法回收，
                  此时若目标落在僵尸态，结论会是 ``仍存活``（``进程存活`` 的如实语义，不谎报已清理）。
        ``宽限秒``：发「终止」后等进程自行退出的时间。
        ``等待秒``：发「强杀」后等进程消失的总时长。

    接入建议（后续批次）：**手上有 `Popen` 句柄就传句柄**——句柄路径能拿到真实退出码
    （信号杀死为负数，如 SIGKILL → -9）；只传裸进程号时本函数会 `waitpid` 回收僵尸，若
    调用方同时另存了该 `Popen` 句柄，其 `returncode` 会因进程已被外部回收而退化为 **0**
    （CPython 在 `ChildProcessError` 时以 0 兜底），此时应以本函数的「结论」为准，不要读句柄的退出码。

    返回
        ``结果.值``：``{结论, 进程ID, 退出码, 已使用强杀, 宽限秒, 等待秒, 平台, 说明表}``。
        结论 ``已终止`` → 成功；``进程不存在`` → 成功（幂等）；``仍存活`` → 失败（错误码
        ``仍存活``，绝不谎报已清理）；平台/权限/参数问题 → 对应失败错误码。
    """
    if isinstance(宽限秒, bool) or not isinstance(宽限秒, (int, float)) or 宽限秒 < 0:
        return _失败结果(结论_参数错误, f"宽限秒 必须是非负数，收到 {宽限秒!r}")
    if isinstance(等待秒, bool) or not isinstance(等待秒, (int, float)) or 等待秒 < 0:
        return _失败结果(结论_参数错误, f"等待秒 必须是非负数，收到 {等待秒!r}")

    # 句柄判定用鸭子类型，不用 isinstance(进程, subprocess.Popen)：
    # 后者在 subprocess.Popen 被替换/打桩（如 mock.patch("subprocess.Popen", autospec=True)）时，
    # isinstance 的第二个参数不再是类型对象 → 抛 TypeError，且会波及所有调用方（收口层必须稳）。
    if isinstance(进程, bool):
        return _失败结果(结论_参数错误, f"进程 不接受布尔值，收到 {进程!r}")
    if isinstance(进程, int):
        进程ID = 进程
    elif hasattr(进程, "pid") and hasattr(进程, "poll"):
        进程ID = 进程.pid
    else:
        return _失败结果(
            结论_参数错误,
            f"进程 必须是有 pid/poll 的句柄或正整数进程号，收到 {type(进程).__name__}",
        )
    if not isinstance(进程ID, int) or 进程ID <= 0:
        return _失败结果(结论_参数错误, f"无法从入参取得合法进程号: {进程ID!r}")

    参数 = (进程ID, 进程, 宽限秒, 等待秒)
    说明表: list[str] = []
    已使用强杀 = False

    if _已结束(进程):
        说明表.append("目标进程此前已结束，无需终止（幂等）")
        return _组装结束(结论_进程不存在, 已使用强杀, 说明表, *参数)

    # 阶段一：优雅终止
    第一步 = 终止进程组(进程ID, 信号="终止")
    if not 第一步.成功:
        if 第一步.错误码 == 结论_进程不存在:
            说明表.append(f"终止阶段返回「进程不存在」：{第一步.错误说明}")
            return _组装结束(结论_进程不存在, 已使用强杀, 说明表, *参数)
        return _失败结果(
            第一步.错误码,
            f"优雅终止失败：{第一步.错误说明}",
            详情={"阶段": "终止", "进程ID": 进程ID},
        )
    说明表.append(f"终止阶段：{第一步.值.get('说明') if 第一步.值 else '已发送终止信号'}")

    if _等待结束(进程, 进程ID, 宽限秒):
        说明表.append(f"{宽限秒} 秒宽限内自行退出")
        return _组装结束(结论_已终止, 已使用强杀, 说明表, *参数)
    说明表.append(f"{宽限秒} 秒宽限内未退出，升级为强杀")

    # 阶段二：强杀
    已使用强杀 = True
    第二步 = 终止进程组(进程ID, 信号="强杀")
    if not 第二步.成功 and 第二步.错误码 != 结论_进程不存在:
        return _失败结果(
            第二步.错误码,
            f"强杀失败：{第二步.错误说明}",
            详情={"阶段": "强杀", "进程ID": 进程ID},
        )
    说明表.append(f"强杀阶段：{第二步.值.get('说明') if 第二步.值 else '已发送强杀信号'}")

    if _等待结束(进程, 进程ID, 等待秒):
        说明表.append(f"强杀后 {等待秒} 秒内已消失")
        return _组装结束(结论_已终止, 已使用强杀, 说明表, *参数)

    说明表.append(f"强杀后 {等待秒} 秒仍未消失（僵尸计为存活）")
    return _组装结束(结论_仍存活, 已使用强杀, 说明表, *参数)


def _是进程句柄(值) -> bool:
    """句柄判定：**一律用鸭子类型**，不用 ``isinstance(值, subprocess.Popen)``。

    为什么不能用 isinstance：`subprocess.Popen` 可能被替换或打桩
    （如 ``mock.patch("subprocess.Popen", autospec=True)``），此时它是 MagicMock 而非类型对象，
    ``isinstance`` 的第二参会抛 ``TypeError`` —— 而本模块是所有调用方的收口层，
    一处抛错会波及全部调用方（实测已打中 `测试中心/支持库/测试_Git提供者.py`）。
    """
    return (not isinstance(值, (bool, int))) and hasattr(值, "pid") and hasattr(值, "poll")


def _已结束(进程: subprocess.Popen | int) -> bool:
    """目标是否已结束：``Popen`` 走 ``poll()``（含回收），``int`` 走存活探测。"""
    if _是进程句柄(进程):
        try:
            return 进程.poll() is not None
        except OSError:
            return False
    return not 进程存活(进程)


def _等待结束(进程: subprocess.Popen | int, 进程ID: int, 秒: float) -> bool:
    """等待进程结束：``Popen`` 走 ``wait``（顺带回收），``int`` 走「先回收僵尸 → 再探存活」。"""
    截止 = time.monotonic() + float(秒)
    while True:
        if _是进程句柄(进程):
            try:
                进程.wait(timeout=轮询间隔秒)
                return True
            except subprocess.TimeoutExpired:
                pass
            except OSError:
                pass
            try:
                if 进程.poll() is not None:
                    return True
            except OSError:
                pass
        else:
            # 裸进程号路径：先尝试回收自有子进程（僵尸），再按存活探测收口
            if _回收自有子进程(进程ID):
                return True
            if not 进程存活(进程ID):
                return True
        if time.monotonic() >= 截止:
            return False
        time.sleep(轮询间隔秒)


def _组装结束(
    结论: str,
    已使用强杀: bool,
    说明表: list[str],
    进程ID: int,
    进程: subprocess.Popen | int,
    宽限秒: float,
    等待秒: float,
) -> 结果[dict[str, Any]]:
    退出码: int | None = None
    if _是进程句柄(进程):
        try:
            退出码 = 进程.poll()
        except OSError:
            退出码 = None
    值 = {
        "结论": 结论,
        "进程ID": 进程ID,
        "退出码": 退出码,
        "已使用强杀": 已使用强杀,
        "宽限秒": 宽限秒,
        "等待秒": 等待秒,
        "平台": _当前平台名(),
        "说明表": 说明表,
    }
    if 结论 in (结论_已终止, 结论_进程不存在):
        return 结果.成功结果(值)
    return _失败结果(结论, "；".join(说明表) or 结论, 详情=值)


__all__ = [
    "来源",
    "终止宽限秒",
    "默认等待秒",
    "轮询间隔秒",
    "信号表",
    "结论_已终止",
    "结论_已终止_回退",
    "结论_进程不存在",
    "结论_无权限",
    "结论_不支持",
    "结论_参数错误",
    "结论_终止失败",
    "结论_仍存活",
    "进程存活",
    "等待进程消失",
    "终止进程组",
    "强制结束子进程",
    # 2026-09-16 补齐：`组长被 wait 回收后仍要判组存活 / 按组号补发信号` 三原语
    # 已实现但漏登记，Pyright 对 `进程终止.按组号探活(...)` 报 reportAttributeAccessIssue。
    "按组号探活",
    "按组号终止",
    "进程组号",
]


def 按组号探活(组号: int) -> bool:
    """按**进程组号**探活；Windows 恒 ``False``（如实标注，不伪造）。

    为什么必须独立于 ``进程存活``：``os.getpgid(pid)`` 在组长被 ``wait()`` 回收后
    抛 ``ProcessLookupError``，而 ``os.killpg(组号, 0)`` 仍能探测到该组存在
    —— 「组长退出、同组子孙仍在」这类语义只有按组号的原语能表达。
    """
    if isinstance(组号, bool) or not isinstance(组号, int) or 组号 <= 0:
        return False
    if _是Windows() or not hasattr(os, "killpg"):
        return False
    try:
        os.killpg(组号, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 组在，只是无权限发信号
    except OSError:
        return False
    return True


def 按组号终止(组号: int, *, 信号: str = "终止") -> 结果[dict[str, Any]]:
    """按**进程组号**终止整组，返回 ``结果``，**永不抛异常**。

    与 ``终止进程组`` 的唯一区别：**不再用 ``os.getpgid`` 反查组号**，因此
    **组长已被回收（僵尸已 wait）时依然可用** —— 正是「组长正常退出但同组子孙仍在」
    场景唯一能用的终止原语。``结果.值`` 字段与 ``终止进程组`` 完全一致（同一信封），
    其中 ``进程ID`` 位放的是**组号**。
    """
    if 信号 not in 信号表:
        return _失败结果(结论_参数错误, f"信号必须是 {信号表} 之一，收到: {信号!r}")
    if isinstance(组号, bool) or not isinstance(组号, int) or 组号 <= 0:
        return _失败结果(
            结论_参数错误,
            f"组号必须是正整数，收到 {type(组号).__name__}: {组号!r}",
        )
    强杀 = 信号 == "强杀"
    try:
        if _是Windows():
            结论, 说明 = (
                结论_不支持,
                "Windows 无进程组号概念，无法按组号终止（请按进程树终止）",
            )
        elif not hasattr(os, "killpg"):
            结论, 说明 = (
                结论_不支持,
                f"平台 {sys.platform} 无 os.killpg，无法按组号终止",
            )
        else:
            信号号 = signal.SIGKILL if 强杀 else signal.SIGTERM
            信号名 = "SIGKILL" if 强杀 else "SIGTERM"
            try:
                os.killpg(组号, 信号号)
                结论 = 结论_已终止
                说明 = f"已按组号向进程组 {组号} 发出 {信号名}"
            except ProcessLookupError:
                结论 = 结论_进程不存在
                说明 = f"进程组 {组号} 不存在（幂等）"
            except PermissionError:
                结论 = 结论_无权限
                说明 = f"无权限向进程组 {组号} 发信号"
    except Exception as 错误:  # noqa: BLE001
        结论 = 结论_终止失败
        说明 = f"按组号终止时出现未预期异常 {type(错误).__name__}: {错误}"
    return _组装(结论, 组号, 信号, 说明, 已发出信号=结论 in (结论_已终止, 结论_已终止_回退))

def 进程组号(进程) -> int | None:
    """返回进程所属进程组号；Windows 无此概念时返回 ``None``（如实标注，不伪造）。

    供需要"真实组号"的调用方使用（例如 FFmpeg 提供者对账进程组）。
    平台差异只在本模块内判断，调用方不需要知道自己在什么平台上。
    """
    if isinstance(进程, bool):
        return None
    if isinstance(进程, int):
        进程ID = 进程
    elif hasattr(进程, "pid"):
        进程ID = 进程.pid
    else:
        return None
    try:
        if not _是POSIX():
            return None
        return os.getpgid(进程ID)
    except (OSError, AttributeError):
        return None
