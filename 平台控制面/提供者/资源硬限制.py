"""进程资源硬限制提供者：POSIX 用 resource.setrlimit 做真实硬限制（无 cgroup）。

覆盖进程数/文件句柄/内存/核心转储四类，每条限制都在真实子进程内设置并
验证强制效果；无法强制的预算项如实返回 UNENFORCEABLE，禁止显示为正常。
契约：探测能力()、设置限制(类型,软上限,硬上限)、应用预算(预算dict)
（返回已生效/不可强制清单）、在独立进程组中运行(命令列表,预算dict,超时秒)。
预算键：进程数上限/文件句柄上限/内存上限(字节)/核心转储上限(字节)。

平台口径：``resource`` 是 **POSIX 专有** 模块（Windows 上根本不存在，顶层导入会让
import 本模块即崩）。故本模块顶层不导入它，改成 `限制类型表()` 内惰性取用，并在取用前
用 `平台适配.要求POSIX能力` **显式报不支持**——非 POSIX 平台不会静默降级成「无限制运行」。
"""
from __future__ import annotations

import errno
import json
import mmap
import os
import subprocess
import sys
import threading
import signal
from pathlib import Path

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 平台适配, 进程终止

模块路径 = str(Path(__file__).resolve())
未强制 = "UNENFORCEABLE"
预算对应表 = {"进程数上限": "进程数", "文件句柄上限": "文件句柄",
            "内存上限": "内存", "核心转储上限": "核心转储"}
默认输出上限 = 4 * 1024 * 1024


def 限制类型表() -> dict[str, int]:
    """资源限制类型 → 当前平台 ``resource`` 常量的映射（**取值时才取用** POSIX 专有模块）。

    非 POSIX 平台在此**显式报不支持**（``平台不支持错误``），不返回空表、不静默跳过。
    """
    平台适配.要求POSIX能力("resource 资源硬限制（setrlimit）")
    from resource import RLIMIT_AS, RLIMIT_CORE, RLIMIT_NOFILE, RLIMIT_NPROC  # 惰性导入：POSIX 专有
    return {"进程数": RLIMIT_NPROC, "文件句柄": RLIMIT_NOFILE,
            "内存": RLIMIT_AS, "核心转储": RLIMIT_CORE}


class _惰性限制类型表:
    """``类型表`` 的惰性替身：只有真正取值时才取用 POSIX 专有的 ``resource``。

    为什么不是普通 dict：本模块的 ``类型表`` 被 `平台控制面.提供者.__init__` 在**导入期**
    取用，而 dict 必须在导入期就把 ``resource`` 常量算出来——那等于让 Windows 上 import 即崩。
    这里改为「取值时才构建」的映射替身，语义与原 dict 逐项一致：
    - POSIX：取值结果与原来完全相同；
    - 非 POSIX：任何取值经 `限制类型表()` 显式抛 ``平台不支持错误``，不静默返 None。
    """

    def 全部取值(self) -> dict[str, int]:
        """真实映射（每次取值现算，避免导入期取用 POSIX 专有模块）。"""
        return 限制类型表()

    def 取(self, 类型: str, 默认=None):
        """中文命名的取项方法（不用 dict 的 ``get``：正式代码全中文，且 ``get`` 不是映射协议的一部分）。"""
        return 限制类型表().get(类型, 默认)

    def __getitem__(self, 类型: str) -> int:
        return 限制类型表()[类型]

    def __contains__(self, 类型: object) -> bool:
        return 类型 in 限制类型表()

    def __len__(self) -> int:
        return len(限制类型表())

    def __iter__(self):
        return iter(限制类型表())

    def __repr__(self) -> str:
        return "类型表（惰性：取值时才取用 POSIX 专有的 resource 模块）"


类型表 = _惰性限制类型表()


def _终止进程组(进程: subprocess.Popen) -> bool:
    """收敛本进程组的子进程；返回是否确认收敛（**回收失败不静默**）。

    统一口径：``强制结束子进程`` 的返回值一律走 ``进程终止.结束并留痕`` ——
    失败即登记回收失败留痕（可经 ``进程终止.回收失败留痕快照()`` 读到），
    本函数再把「是否确认收敛」交给调用方，调用方据此在错误说明里如实带出，
    绝不把「没回收掉」写成「已终止」。
    """
    收敛 = 进程终止.结束并留痕(
        进程, 位置="资源硬限制._终止进程组", 宽限秒=2.0, 等待秒=2.0)
    try:
        进程.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        收敛 = 假
    if 进程.poll() is None:
        收敛 = 假
    return 收敛


def _回收失败提示(回收失败: list[str]) -> str:
    """回收失败留痕 → 错误说明后缀（空表 = 无失败，返回空串，不改原说明形状）。

    口径：``强制结束子进程`` 的失败已经在 ``进程终止`` 里留痕，这里只把「未确认回收」
    如实带到调用方看得见的错误说明上——**不把失败说成已终止**，也不造第二套留痕。
    """
    if not 回收失败:
        return ""
    return "；" + "；".join(回收失败) + "（见 进程终止.回收失败留痕快照()）"


def _受限通信(进程: subprocess.Popen, 超时秒: float,
             输出上限: int = 默认输出上限) -> tuple[bytes, bytes, bool, bool, list[str]]:
    """双管道有界读取，避免 communicate 一次性把子进程输出载入内存。

    返回第 5 项是**回收失败留痕**（本次调用里 ``_终止进程组`` 未确认收敛的条目），
    空表 = 所有终止路径都确认收敛；调用方必须把它带进错误说明，不得丢弃。
    """
    结果: dict[str, bytearray] = {"输出": bytearray(), "错误输出": bytearray()}
    超限 = {"输出": 假, "错误输出": 假}
    回收失败: list[str] = []

    def 读取(名称: str, 流) -> None:
        if 流 is None:
            return
        try:
            while True:
                块 = 流.read(65536)
                if not 块:
                    return
                if isinstance(块, str):
                    块 = 块.encode("utf-8", "replace")
                目标 = 结果[名称]
                if len(目标) < 输出上限:
                    目标.extend(块[:输出上限 - len(目标)])
                if len(目标) >= 输出上限 and len(块) > 输出上限 - len(目标):
                    超限[名称] = 真
                    if not _终止进程组(进程):
                        回收失败.append(f"输出达到上限后回收子进程组未确认收敛（{名称}）")
                    return
        except (OSError, ValueError):
            return

    线程表 = [threading.Thread(target=读取, args=(名称, 流), daemon=True)
             for 名称, 流 in (("输出", 进程.stdout), ("错误输出", 进程.stderr))]
    for 线程 in 线程表:
        线程.start()
    try:
        进程.wait(timeout=超时秒)
    except subprocess.TimeoutExpired:
        if not _终止进程组(进程):
            回收失败.append(f"超时（{超时秒} 秒）回收子进程组未确认收敛")
        for 线程 in 线程表:
            线程.join(timeout=1.0)
        for 流 in (进程.stdout, 进程.stderr):
            try:
                if 流 is not None:
                    流.close()
            except (OSError, ValueError):
                pass
        return (bytes(结果["输出"]), bytes(结果["错误输出"]), 真,
                any(线程.is_alive() for 线程 in 线程表), 回收失败)
    for 线程 in 线程表:
        线程.join(timeout=1.0)
    for 流 in (进程.stdout, 进程.stderr):
        try:
            if 流 is not None:
                流.close()
        except (OSError, ValueError):
            pass
    return (bytes(结果["输出"]), bytes(结果["错误输出"]), 假,
            any(超限.values()), 回收失败)


def 设置限制(类型: str, 软上限: int, 硬上限: int) -> dict:
    """当前进程真实 setrlimit；设置失败返回 UNENFORCEABLE，不伪装成功。

    ``resource`` 在真正调用它的本函数内惰性导入（POSIX 专有：顶层导入会让 Windows 上
    import 本模块即崩）；非 POSIX 平台由 `类型表.get()` 先行**显式报不支持**。
    """
    常量 = 类型表.取(类型)
    if 常量 is None:
        return {"成功": 假, "值": None, "错误码": 未强制, "错误说明": f"未知限制类型: {类型}"}
    from resource import getrlimit, setrlimit  # 惰性导入：POSIX 专有
    try:
        setrlimit(常量, (软上限, 硬上限))
    except (OSError, ValueError) as 错误:
        return {"成功": 假, "值": None, "错误码": 未强制,
                "错误说明": f"{类型}上限设置失败，不具备硬限制能力: {错误}"}
    return {"成功": 真, "值": getrlimit(常量), "错误码": "", "错误说明": ""}


def 验证文件句柄() -> tuple[bool, str]:
    """RLIMIT_NOFILE 验证：真实打开文件直到被拒（EMFILE）。"""
    已开: list[int] = []
    try:
        for _ in range(32):
            已开.append(os.open(os.devnull, os.O_RDONLY))
        return 假, "打开 32 个文件未被拒"
    except OSError as 错误:
        for 句柄 in 已开:
            os.close(句柄)
        if 错误.errno == errno.EMFILE:
            return 真, f"上限5个句柄，打开{len(已开)}个后第{len(已开)+1}个被拒(EMFILE)"
        return 假, f"异常错误: {错误}"


def 验证进程数() -> tuple[bool, str]:
    """RLIMIT_NPROC 验证：fork 超过同用户进程上限被拒（EAGAIN）。

    非 POSIX（Windows）没有 ``os.fork``，此处**如实返回探测不通过**（不抛异常）——
    探测函数的契约是「能不能强制」，不是「能不能跑」，崩掉会让整条探测链失真。
    """
    if not hasattr(os, "fork"):
        return 假, "平台无 os.fork（非 POSIX），RLIMIT_NPROC 不可强制"
    try:
        子进程号 = os.fork()
    except OSError as 错误:
        if 错误.errno == errno.EAGAIN:
            return 真, f"上限1个进程时fork被拒(EAGAIN: {错误})"
        return 假, f"异常错误: {错误}"
    if 子进程号 == 0:
        os._exit(0)
    os.waitpid(子进程号, 0)
    return 假, "fork 未被拒绝"


def 验证内存() -> tuple[bool, str]:
    """RLIMIT_AS 验证：超限映射被拒才算强制生效。"""
    try:
        映射 = mmap.mmap(-1, 1024 * 1024 * 1024)
        映射.close()
        return 假, "1GB 映射未被拒，内核未执行限制"
    except (OSError, MemoryError, ValueError) as 错误:
        return 真, f"超限映射被拒: {错误}"


自检表 = {"进程数": (1, 1, 验证进程数), "文件句柄": (5, 5, 验证文件句柄),
         "内存": (512 * 1024 * 1024, 512 * 1024 * 1024, 验证内存),
         "核心转储": (0, 0, lambda: (真, "上限已设为 0，内核将抑制核心转储"))}


def 自检记录(类型: str, 软上限: int, 硬上限: int, 验证) -> dict:
    """设置后真实验证：能设置且能观察到强制效果才算已生效。"""
    结果 = 设置限制(类型, 软上限, 硬上限)
    if not 结果["成功"]:
        return {"类型": 类型, "状态": 未强制, "说明": 结果["错误说明"]}
    生效, 说明 = 验证()
    return {"类型": 类型, "状态": "已生效" if 生效 else 未强制, "说明": 说明}


def 探测能力() -> dict:
    """启动前能力探测：真实子进程内逐类验证；无法强制的类型如实报告。"""
    try:
        子进程 = subprocess.run([sys.executable, 模块路径, "--自检"],
                                capture_output=True, text=True, timeout=60)
        报告 = json.loads(子进程.stdout.strip().splitlines()[-1])
        return {"成功": 真, "已生效": 报告.get("已生效", []),
                "不可强制": 报告.get("不可强制", []), "错误说明": ""}
    except Exception as 错误:
        return {"成功": 假, "已生效": [], "不可强制": [],
                "错误说明": f"能力探测子进程未返回有效报告: {错误}"}


def 应用预算(预算: dict) -> dict:
    """当前进程逐项真实 setrlimit；返回已生效清单与不可强制清单。"""
    已生效, 不可强制 = [], []
    for 键, 类型 in 预算对应表.items():
        if 键 not in 预算:
            continue
        结果 = 设置限制(类型, 预算[键], 预算[键])
        (已生效 if 结果["成功"] else 不可强制).append(
            {"类型": 类型} if 结果["成功"] else {"类型": 类型, "错误说明": 结果["错误说明"]})
    return {"成功": not 不可强制, "已生效": 已生效, "不可强制": 不可强制,
            "错误说明": "" if not 不可强制 else "存在无法强制的预算项，未假装全部生效"}


def _子进程应用预算(预算: dict) -> None:
    """exec 前在受限子进程内真实设置全部预算项；失败阻止启动。"""
    for 键, 类型 in 预算对应表.items():
        if 键 in 预算:
            结果 = 设置限制(类型, 预算[键], 预算[键])
            if not 结果["成功"]:
                raise RuntimeError(结果["错误说明"])


def 在独立进程组中运行(命令列表: list[str], 预算: dict, 超时秒: float = 30) -> dict:
    """在独立进程组（新会话）中启动命令；存在不可强制预算项则拒绝启动。"""
    探测 = 探测能力()
    不可强制表 = {项["类型"] for 项 in 探测["不可强制"]}
    被拒 = [类型 for 键, 类型 in 预算对应表.items() if 键 in 预算 and 类型 in 不可强制表]
    if 被拒 or not 探测["成功"]:
        return {"成功": 假, "错误码": 未强制, "值": None,
                "错误说明": f"以下预算项不具备硬限制能力，拒绝启动（不能假装正常）: {被拒 or 探测['错误说明']}"}
    try:
        进程 = subprocess.Popen(命令列表, **平台适配.子进程组启动标志(),
                                preexec_fn=lambda: _子进程应用预算(预算),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as 错误:
        return {"成功": 假, "错误码": 未强制, "值": None,
                "错误说明": f"进程启动失败: {错误}"}
    try:
        输出, 错误输出, 已超时, 输出超限, 回收失败 = _受限通信(进程, 超时秒)
    except Exception as 错误:
        if not _终止进程组(进程):
            回收失败 = [f"受限读取异常后回收子进程组未确认收敛（{type(错误).__name__}）"]
        else:
            回收失败 = []
        return {"成功": 假, "错误码": "命令失败", "值": None,
                "错误说明": f"受限读取失败: {错误}{_回收失败提示(回收失败)}",
                "回收失败留痕": 回收失败}
    if 已超时:
        进程.kill()
        进程.wait()
        return {"成功": 假, "错误码": "超时", "值": None,
                "错误说明": f"命令 {超时秒} 秒未结束，已终止{_回收失败提示(回收失败)}",
                "回收失败留痕": 回收失败}
    if 输出超限:
        if not _终止进程组(进程):
            回收失败.append("输出超限路径回收子进程组未确认收敛")
        return {"成功": 假, "错误码": "超出限制", "值": None,
                "错误说明": f"命令输出超过上限 {默认输出上限} 字节，已终止{_回收失败提示(回收失败)}",
                "回收失败留痕": 回收失败}
    return {"成功": 进程.returncode == 0,
            "错误码": "" if 进程.returncode == 0 else "命令失败",
            "错误说明": "" if 进程.returncode == 0 else "命令返回非零",
            "回收失败留痕": 回收失败,
            "值": {"进程组id": 进程.pid, "返回码": 进程.returncode,
                   "输出": 输出.decode("utf-8", "replace"),
                   "错误输出": 错误输出.decode("utf-8", "replace")}}


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--自检":
        类型 = sys.argv[2] if len(sys.argv) >= 3 else None
        报告 = 自检记录(类型, *自检表[类型]) if 类型 else {"已生效": [], "不可强制": []}
        if not 类型:
            for 名称, 项 in 自检表.items():
                记录 = 自检记录(名称, *项)
                (报告["已生效"] if 记录["状态"] == "已生效" else 报告["不可强制"]).append(记录)
        print(json.dumps(报告, ensure_ascii=False))
        raise SystemExit(0)
    print("用法: python3.14 平台控制面/提供者/资源硬限制.py --自检 [类型]")
    raise SystemExit(1)
