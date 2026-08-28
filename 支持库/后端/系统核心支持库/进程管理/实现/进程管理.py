"""进程管理原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：启动/终止/查询/等待进程（参考易语言系统核心支持库）。
句柄模式：启动进程返回句柄，状态机统一生命周期（超时/释放自动杀进程组）。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源

句柄系统 = 句柄体系()
进程表: dict[str, dict] = {}
锁 = threading.Lock()



降级记录表: list[str] = []  # 尽力清理/降级场景的异常记录（不阻断主流程）

def _取进程(句柄: str) -> tuple[subprocess.Popen | None, str]:
    有效, 原因 = 句柄系统.校验(句柄id=句柄)
    if not 有效:
        return None, 原因
    进程 = 进程表.get(句柄)
    if 进程 is None:
        return None, f"进程句柄 {句柄} 不存在"
    return 进程.get("进程对象"), ""


def 启动进程(命令: str = None, 参数: list = None, 工作目录: str = None,
             环境变量: dict = None, 超时秒: int = None) -> 结果:
    """启动外部进程。返回 {句柄, PID}。"""
    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    try:
        cmd = [命令] + (参数 or [])
        进程 = subprocess.Popen(cmd, cwd=工作目录, env=环境变量,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as 错误:
        return 结果.失败("启动失败", str(错误), 来源="进程管理")
    with 锁:
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id="进程", 所有者="")
        进程表[对象.句柄id] = {"进程对象": 进程, "PID": 进程.pid, "命令": 命令}
    return 结果.成功结果({"句柄": 对象.句柄id, "PID": 进程.pid, "命令": 命令})


def 终止进程(句柄: str = None, 强制: bool = None) -> 结果:
    """终止进程（killpg 进程组）。返回 {已终止, 退出码}。"""
    进程, 原因 = _取进程(句柄)
    if 进程 is None:
        return 结果.失败("句柄失效", 原因, 来源="进程管理")
    try:
        if 强制:
            os.killpg(os.getpgid(进程.pid), 9)
        else:
            进程.terminate()
            进程.wait(timeout=5)
        return 结果.成功结果({"已终止": True, "退出码": 进程.returncode, "PID": 进程.pid})
    except Exception as 错误:
        return 结果.失败("终止失败", str(错误), 来源="进程管理")


def 查询进程状态(句柄: str = None) -> 结果:
    """查询进程状态。返回 {运行中, 退出码, PID}。"""
    进程, 原因 = _取进程(句柄)
    if 进程 is None:
        return 结果.失败("句柄失效", 原因, 来源="进程管理")
    进程.poll()
    return 结果.成功结果({"运行中": 进程.returncode is None,
                            "退出码": 进程.returncode, "PID": 进程.pid})


def 等待进程结束(句柄: str = None, 超时秒: float = None) -> 结果:
    """等待进程结束。返回 {退出码, 标准输出, 错误输出}。"""
    进程, 原因 = _取进程(句柄)
    if 进程 is None:
        return 结果.失败("句柄失效", 原因, 来源="进程管理")
    try:
        stdout, stderr = 进程.communicate(timeout=超时秒)
        return 结果.成功结果({"退出码": 进程.returncode,
                                "标准输出": (stdout or b"").decode("utf-8", errors="replace"),
                                "错误输出": (stderr or b"").decode("utf-8", errors="replace")})
    except subprocess.TimeoutExpired:
        return 结果.失败("超时", "进程等待超时", 来源="进程管理")


def 执行命令(命令: str = None, 超时秒: float = None, 工作目录: str = None) -> 结果:
    """执行命令并等待完成。返回 {退出码, 标准输出, 错误输出}。"""
    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    try:
        运行结果 = subprocess.run(命令, shell=True, capture_output=True, text=True,
                               timeout=超时秒 or 60, cwd=工作目录)
        return 结果.成功结果({"退出码": 运行结果.returncode, "标准输出": 运行结果.stdout,
                                "错误输出": 运行结果.stderr})
    except subprocess.TimeoutExpired:
        return 结果.失败("超时", "命令执行超时", 来源="进程管理")
    except Exception as 错误:
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


def 释放句柄(句柄: str = None) -> 结果:
    """释放进程句柄（幂等，强制终止残留进程）。"""
    if not isinstance(句柄, str) or not 句柄.strip():
        return 结果.失败("参数不合法", "句柄必须是非空字符串", 来源="进程管理")
    with 锁:
        进程 = 进程表.pop(句柄, None)
        if 进程:
            try:
                os.killpg(os.getpgid(进程["进程对象"].pid), 9)
            except Exception as 错误:
                降级记录表.append(str(错误))
        句柄系统.失效(句柄, "释放")
    return 结果.成功结果({"句柄": 句柄, "已释放": True})