"""进程管理原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：启动/终止/查询/等待进程（参考易语言系统核心支持库）。
句柄模式：启动进程返回句柄，状态机统一生命周期（超时/释放自动杀进程组）。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源
from 公共契约.运行时.有界IO import 受限通信, 默认子进程输出上限字节

句柄系统 = 句柄体系()
进程表: dict[int, dict] = {}
锁 = threading.Lock()



降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程）

def _取进程(句柄: int | None) -> tuple[subprocess.Popen | None, str]:
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return None, "句柄必须是1到999999的整数"
    有效, 原因 = 句柄系统.校验(句柄id=句柄)
    if not 有效:
        return None, 原因
    进程 = 进程表.get(句柄)
    if 进程 is None:
        return None, f"进程句柄 {句柄} 不存在"
    return 进程.get("进程对象"), ""


def 启动进程(命令: str = None, 参数: list = None, 工作目录: str = None,
             环境变量: dict = None, 超时秒: int = None,
             就绪地址: str = None, 就绪超时秒: float = None) -> 结果:
    """启动外部进程。返回 {句柄, PID}。"""
    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    try:
        cmd = [命令] + (参数 or [])
        # 独立进程组：POSIX 下 killpg 必须作用在独立组，否则会误杀
        # 网关/测试进程自身；Windows 走 job 等价策略（terminate/kill）。
        进程 = subprocess.Popen(cmd, cwd=工作目录, env=环境变量,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=(os.name == "posix"))
    except Exception as 错误:
        return 结果.失败("启动失败", str(错误), 来源="进程管理")
    if 就绪地址:
        try:
            主机, 端口文本 = 就绪地址.rsplit(":", 1)
            端口 = int(端口文本)
            截止 = time.monotonic() + (float(就绪超时秒) if 就绪超时秒 else 5.0)
            while time.monotonic() < 截止:
                if 进程.poll() is not None:
                    错误输出 = (进程.stderr.read() if 进程.stderr else b"")[:2000]
                    return 结果.失败("启动失败", f"进程在就绪前退出: {错误输出.decode('utf-8', 'replace')}", 来源="进程管理")
                try:
                    with socket.create_connection((主机, 端口), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.02)
            else:
                _终止进程组(进程)
                return 结果.失败("启动超时", f"就绪地址未监听: {就绪地址}", 来源="进程管理")
        except (TypeError, ValueError) as 错误:
            _终止进程组(进程)
            return 结果.失败("参数不合法", f"就绪地址必须是 主机:端口: {错误}", 来源="进程管理")
    with 锁:
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id="进程", 所有者="")
        进程表[对象.句柄id] = {"进程对象": 进程, "PID": 进程.pid, "命令": 命令}
    return 结果.成功结果({"句柄": 对象.句柄id, "PID": 进程.pid, "命令": 命令})


def _终止进程组(进程: subprocess.Popen, 强制: bool = True, 宽限秒: float = 2.0) -> None:
    """进程组终止：TERM→有界等待→KILL→再次等待（POSIX）；Windows 用进程级 terminate/kill。

    先确认进程组归属（进程可能已退出或从未建立独立组），避免误杀无关进程组。
    """
    if os.name != "posix":
        try:
            if 强制:
                进程.kill()
            else:
                进程.terminate()
            进程.wait(timeout=宽限秒)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return
    try:
        os.killpg(os.getpgid(进程.pid), signal.SIGTERM if not 强制 else signal.SIGKILL)
    except (OSError, ProcessLookupError):
        return  # 进程组已不存在
    try:
        进程.wait(timeout=宽限秒)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(进程.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        进程.wait(timeout=宽限秒)
    except subprocess.TimeoutExpired:
        pass


def 终止进程(句柄: int | None = None, 强制: bool = None) -> 结果:
    """终止进程（killpg 进程组）。返回 {已终止, 退出码}。"""
    进程, 原因 = _取进程(句柄)
    if 进程 is None:
        return 结果.失败("句柄失效", 原因, 来源="进程管理")
    try:
        _终止进程组(进程, 强制=bool(强制))
        return 结果.成功结果({"已终止": True, "退出码": 进程.returncode, "PID": 进程.pid})
    except Exception as 错误:
        return 结果.失败("终止失败", str(错误), 来源="进程管理")


def 查询进程状态(句柄: int | None = None) -> 结果:
    """查询进程状态。返回 {运行中, 退出码, PID}。"""
    进程, 原因 = _取进程(句柄)
    if 进程 is None:
        return 结果.失败("句柄失效", 原因, 来源="进程管理")
    进程.poll()
    return 结果.成功结果({"运行中": 进程.returncode is None,
                            "退出码": 进程.returncode, "PID": 进程.pid})


def 等待进程结束(句柄: int | None = None, 超时秒: float = None) -> 结果:
    """等待进程结束。返回 {退出码, 标准输出, 错误输出}。"""
    进程, 原因 = _取进程(句柄)
    if 进程 is None:
        return 结果.失败("句柄失效", 原因, 来源="进程管理")
    try:
        stdout, stderr, 已超时, 已超限 = 受限通信(
            进程, 超时秒=float(超时秒) if 超时秒 is not None else 60.0,
            输出上限字节=默认子进程输出上限字节,
            终止回调=lambda: _终止进程组(进程),
        )
        if 已超时:
            return 结果.失败("超时", "进程等待超时", 来源="进程管理")
        if 已超限:
            return 结果.失败("超出限制", "进程输出超过上限", 来源="进程管理")
        return 结果.成功结果({"退出码": 进程.returncode,
                                "标准输出": (stdout or b"").decode("utf-8", errors="replace"),
                                "错误输出": (stderr or b"").decode("utf-8", errors="replace")})
    except Exception as 错误:
        return 结果.失败("等待失败", str(错误), 来源="进程管理")


def 执行命令(命令: str = None, 超时秒: float = None, 工作目录: str = None) -> 结果:
    """执行命令并等待完成。返回 {退出码, 标准输出, 错误输出}。"""
    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    # shell=True 时无法 killpg 进程组；改用参数列表方式，超时由独立
    # 进程组统一回收，避免 shell 子孙进程泄漏。
    import shlex
    try:
        命令表 = shlex.split(命令)
    except ValueError as 错误:
        return 结果.失败("参数不合法", f"命令解析失败: {错误}", 来源="进程管理")
    if not 命令表:
        return 结果.失败("参数不合法", "命令为空", 来源="进程管理")
    进程 = None
    try:
        进程 = subprocess.Popen(
            命令表, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=工作目录, start_new_session=(os.name == "posix"))
        stdout, stderr, 已超时, 已超限 = 受限通信(
            进程, 超时秒=float(超时秒 or 60),
            输出上限字节=默认子进程输出上限字节,
            终止回调=lambda: _终止进程组(进程),
        )
        if 已超时:
            return 结果.失败("超时", "命令执行超时", 来源="进程管理")
        if 已超限:
            return 结果.失败("超出限制", "命令输出超过上限", 来源="进程管理")
        return 结果.成功结果({"退出码": 进程.returncode,
                                "标准输出": (stdout or b"").decode("utf-8", errors="replace"),
                                "错误输出": (stderr or b"").decode("utf-8", errors="replace")})
    except Exception as 错误:
        # 超时/异常后强制回收独立进程组，避免子孙进程残留
        if 进程 is not None:
            try:
                _终止进程组(进程, 强制=True)
            except Exception:
                pass
        return 结果.失败("执行失败", str(错误), 来源="进程管理")


def 检查命令可用(命令: str = None) -> 结果:
    """检查命令是否可用（which）。返回 {可用, 路径}。"""
    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    try:
        运行结果 = subprocess.run(["which", 命令], capture_output=True, text=True, timeout=5)
        可用 = 运行结果.returncode == 0
        return 结果.成功结果({"可用": 可用, "路径": 运行结果.stdout.strip() if 可用 else None})
    except Exception as 错误:
        return 结果.失败("检查失败", str(错误), 来源="进程管理")


def 释放句柄(句柄: int | None = None) -> 结果:
    """释放进程句柄（幂等，强制终止残留进程）。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return 结果.失败("参数不合法", "句柄必须是1到999999的整数", 来源="进程管理")
    with 锁:
        进程 = 进程表.pop(句柄, None)
        if 进程:
            # 先确认进程组归属（start_new_session 保证独立组），再锁外终止，
            # 避免在锁内执行阻塞式 kill/wait 拖住所有句柄操作。
            进程对象 = 进程.get("进程对象")
        else:
            进程对象 = None
        句柄系统.失效(句柄, "释放")
    if 进程对象 is not None:
        try:
            _终止进程组(进程对象, 强制=True)
        except Exception as 错误:
            降级记录表.append(str(错误))
        finally:
            for 管道 in (进程对象.stdout, 进程对象.stderr, 进程对象.stdin):
                if 管道 is not None:
                    管道.close()
    return 结果.成功结果({"句柄": 句柄, "已释放": True})