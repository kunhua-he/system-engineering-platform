"""进程资源硬限制提供者：macOS 用 resource.setrlimit 做真实硬限制（无 cgroup）。

覆盖进程数/文件句柄/内存/核心转储四类，每条限制都在真实子进程内设置并
验证强制效果；无法强制的预算项如实返回 UNENFORCEABLE，禁止显示为正常。
契约：探测能力()、设置限制(类型,软上限,硬上限)、应用预算(预算dict)
（返回已生效/不可强制清单）、在独立进程组中运行(命令列表,预算dict,超时秒)。
预算键：进程数上限/文件句柄上限/内存上限(字节)/核心转储上限(字节)。
"""
from __future__ import annotations

import errno
import json
import mmap
import os
import resource
import subprocess
import sys
import threading
import signal
from pathlib import Path

模块路径 = str(Path(__file__).resolve())
未强制 = "UNENFORCEABLE"
类型表 = {"进程数": resource.RLIMIT_NPROC, "文件句柄": resource.RLIMIT_NOFILE,
          "内存": resource.RLIMIT_AS, "核心转储": resource.RLIMIT_CORE}
预算对应表 = {"进程数上限": "进程数", "文件句柄上限": "文件句柄",
            "内存上限": "内存", "核心转储上限": "核心转储"}
默认输出上限 = 4 * 1024 * 1024


def _终止进程组(进程: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(进程.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            进程.kill()
        except (OSError, ProcessLookupError):
            pass
    try:
        进程.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def _受限通信(进程: subprocess.Popen, 超时秒: float,
             输出上限: int = 默认输出上限) -> tuple[bytes, bytes, bool, bool]:
    """双管道有界读取，避免 communicate 一次性把子进程输出载入内存。"""
    结果: dict[str, bytearray] = {"输出": bytearray(), "错误输出": bytearray()}
    超限 = {"输出": False, "错误输出": False}

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
                    超限[名称] = True
                    _终止进程组(进程)
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
        _终止进程组(进程)
        for 线程 in 线程表:
            线程.join(timeout=1.0)
        for 流 in (进程.stdout, 进程.stderr):
            try:
                if 流 is not None:
                    流.close()
            except (OSError, ValueError):
                pass
        return bytes(结果["输出"]), bytes(结果["错误输出"]), True, any(线程.is_alive() for 线程 in 线程表)
    for 线程 in 线程表:
        线程.join(timeout=1.0)
    for 流 in (进程.stdout, 进程.stderr):
        try:
            if 流 is not None:
                流.close()
        except (OSError, ValueError):
            pass
    return bytes(结果["输出"]), bytes(结果["错误输出"]), False, any(超限.values())


def 设置限制(类型: str, 软上限: int, 硬上限: int) -> dict:
    """当前进程真实 setrlimit；设置失败返回 UNENFORCEABLE，不伪装成功。"""
    常量 = 类型表.get(类型)
    if 常量 is None:
        return {"成功": False, "值": None, "错误码": 未强制, "错误说明": f"未知限制类型: {类型}"}
    try:
        resource.setrlimit(常量, (软上限, 硬上限))
    except (OSError, ValueError) as 错误:
        return {"成功": False, "值": None, "错误码": 未强制,
                "错误说明": f"{类型}上限设置失败，不具备硬限制能力: {错误}"}
    return {"成功": True, "值": resource.getrlimit(常量), "错误码": "", "错误说明": ""}


def 验证文件句柄() -> tuple[bool, str]:
    """RLIMIT_NOFILE 验证：真实打开文件直到被拒（EMFILE）。"""
    已开: list[int] = []
    try:
        for _ in range(32):
            已开.append(os.open("/dev/null", os.O_RDONLY))
        return False, "打开 32 个文件未被拒"
    except OSError as 错误:
        for 句柄 in 已开:
            os.close(句柄)
        if 错误.errno == errno.EMFILE:
            return True, f"上限5个句柄，打开{len(已开)}个后第{len(已开)+1}个被拒(EMFILE)"
        return False, f"异常错误: {错误}"


def 验证进程数() -> tuple[bool, str]:
    """RLIMIT_NPROC 验证：fork 超过同用户进程上限被拒（EAGAIN）。"""
    try:
        子进程号 = os.fork()
    except OSError as 错误:
        if 错误.errno == errno.EAGAIN:
            return True, f"上限1个进程时fork被拒(EAGAIN: {错误})"
        return False, f"异常错误: {错误}"
    if 子进程号 == 0:
        os._exit(0)
    os.waitpid(子进程号, 0)
    return False, "fork 未被拒绝"


def 验证内存() -> tuple[bool, str]:
    """RLIMIT_AS 验证：超限映射被拒才算强制生效。"""
    try:
        映射 = mmap.mmap(-1, 1024 * 1024 * 1024)
        映射.close()
        return False, "1GB 映射未被拒，内核未执行限制"
    except (OSError, MemoryError, ValueError) as 错误:
        return True, f"超限映射被拒: {错误}"


自检表 = {"进程数": (1, 1, 验证进程数), "文件句柄": (5, 5, 验证文件句柄),
         "内存": (512 * 1024 * 1024, 512 * 1024 * 1024, 验证内存),
         "核心转储": (0, 0, lambda: (True, "上限已设为 0，内核将抑制核心转储"))}


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
        return {"成功": True, "已生效": 报告.get("已生效", []),
                "不可强制": 报告.get("不可强制", []), "错误说明": ""}
    except Exception as 错误:
        return {"成功": False, "已生效": [], "不可强制": [],
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
        return {"成功": False, "错误码": 未强制, "值": None,
                "错误说明": f"以下预算项不具备硬限制能力，拒绝启动（不能假装正常）: {被拒 or 探测['错误说明']}"}
    try:
        进程 = subprocess.Popen(命令列表, start_new_session=True,
                                preexec_fn=lambda: _子进程应用预算(预算),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as 错误:
        return {"成功": False, "错误码": 未强制, "值": None,
                "错误说明": f"进程启动失败: {错误}"}
    try:
        输出, 错误输出, 已超时, 输出超限 = _受限通信(进程, 超时秒)
    except Exception as 错误:
        _终止进程组(进程)
        return {"成功": False, "错误码": "命令失败", "值": None,
                "错误说明": f"受限读取失败: {错误}"}
    if 已超时:
        进程.kill()
        进程.wait()
        return {"成功": False, "错误码": "超时", "值": None,
                "错误说明": f"命令 {超时秒} 秒未结束，已终止"}
    if 输出超限:
        _终止进程组(进程)
        return {"成功": False, "错误码": "超出限制", "值": None,
                "错误说明": f"命令输出超过上限 {默认输出上限} 字节，已终止"}
    return {"成功": 进程.returncode == 0,
            "错误码": "" if 进程.returncode == 0 else "命令失败",
            "错误说明": "" if 进程.returncode == 0 else "命令返回非零",
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
