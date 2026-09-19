"""进程组与子进程树回收：启动、强杀、检查残留。

中文契约：
- 启动进程树(工作目录=None, 模式=None) -> 进程组信息：启动真实 3 层
  python 进程树（父→子→孙，每层打印并落盘 PID），孙节点占用空闲端口，
  整棵树独立进程组（启动标志走 `公共契约.运行时.平台适配.子进程组启动标志()`，
  组号==组长 PID）。模式="组长自杀"时组长启动子进程后立即退出，
  验证整组回收不依赖组长存活。
- 强杀进程组(进程组信息) -> 回收报告：按跨平台收口 `进程终止.终止进程组`
  强杀整个进程组，等待全部 PID 从系统中消失，清理临时工作目录，验证端口
  可重绑；重复调用安全（幂等）。
- 检查残留(进程组信息) -> 残留报告：核验 ps 存活 PID / 临时目录 /
  端口占用，三者全清才无残留。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 平台适配, 进程终止

树节点代码 = """import os, socket, subprocess, sys, time
深度 = int(os.environ["树深度"])
工作目录 = os.environ["树工作目录"]
名字 = "节点_%d" % 深度
行 = "%s PID=%d PPID=%d" % (名字, os.getpid(), os.getppid())
print(行, flush=True)
open(os.path.join(工作目录, 名字 + ".log"), "w").write(行 + "\\n")
open(os.path.join(工作目录, 名字 + ".pid"), "w").write(str(os.getpid()))
if 深度 < 2:
    subprocess.Popen([sys.executable, "-c", os.environ["树代码"]],
                     env=dict(os.environ, 树深度=str(深度 + 1)))
else:
    监听 = socket.socket()
    监听.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    监听.bind(("127.0.0.1", int(os.environ["树端口"])))
    监听.listen(1)
if os.environ.get("树模式") == "组长自杀" and 深度 == 0:
    os._exit(0)
while True:
    time.sleep(60)
"""


def _空闲端口() -> int:
    """借用系统分配获取一个当前空闲端口。"""
    with socket.socket() as 套接字:
        套接字.bind(("127.0.0.1", 0))
        return 套接字.getsockname()[1]


def _进程存活表(pid表: list[int]) -> list[int]:
    """ps 查询：返回仍在系统中的 PID 列表（含未回收僵尸）。"""
    if not pid表:
        return []
    查询 = subprocess.run(["ps", "-p", ",".join(str(进程) for 进程 in pid表), "-o", "pid="],
                          capture_output=True, text=True)
    return [int(行.strip()) for 行 in 查询.stdout.splitlines() if 行.strip()]


def _等待退出(pid表: list[int], 超时秒: float = 8.0) -> list[int]:
    """轮询等待全部 PID 从系统中消失；超时返回仍未退出的 PID。"""
    剩余 = list(pid表)
    截止 = time.time() + 超时秒
    while time.time() < 截止:
        剩余 = _进程存活表(剩余)
        if not 剩余:
            return []
        time.sleep(0.1)
    return 剩余


def _端口可重绑(端口: int) -> bool:
    """尝试重新绑定端口；成功即端口已释放。"""
    with socket.socket() as 套接字:
        try:
            套接字.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            套接字.bind(("127.0.0.1", 端口))
            return 真
        except OSError:
            return 假


def _等待节点就绪(工作目录: Path, 端口: int, 超时秒: float = 10.0) -> list[int]:
    """等待 3 个节点写齐 PID 文件且孙节点端口开始监听；返回节点 PID 表。"""
    截止 = time.time() + 超时秒
    while time.time() < 截止:
        if len(sorted(工作目录.glob("节点_*.pid"))) >= 3:
            try:
                socket.create_connection(("127.0.0.1", 端口), timeout=1).close()
                break
            except OSError:
                pass
        time.sleep(0.1)
    return [int(文件.read_text(encoding="utf-8").strip()) for 文件 in sorted(工作目录.glob("节点_*.pid"))]


def _强杀整组(组长pid: int, 已知成员pid表: list[int] | None = None) -> None:
    """按跨平台收口强杀进程组（幂等，永不抛异常）。

    两步都走 `进程终止.终止进程组`，调用点不做任何平台判断：

    1. 以组长 PID 调一次——组长仍是活着的进程（含僵尸）时，收口按组号整组强杀，
       一次覆盖全组（含未登记的成员）；
    2. 组长已被 `Popen.wait()` 回收时（"组长自杀"模式）收口按 PID 判定取不到组号，
       会如实回「进程不存在」，此时按已知成员 PID 逐个补发——本模块的进程树每一层
       都落盘 PID，已知成员即全组成员，回收结论与整组强杀一致。
    """
    进程终止.终止进程组(组长pid, 信号="强杀")
    for pid in 已知成员pid表 or ():
        if pid != 组长pid:
            进程终止.终止进程组(pid, 信号="强杀")


def 启动进程树(工作目录: str | Path | None = None, 模式: str | None = None) -> dict:
    """启动真实 3 层 python 进程树，独立进程组，孙节点占用端口。"""
    目录 = Path(工作目录) if 工作目录 else Path(tempfile.mkdtemp(prefix="进程组树_"))
    目录.mkdir(parents=True, exist_ok=True)
    端口 = _空闲端口()
    环境 = dict(os.environ, 树代码=树节点代码, 树深度="0", 树工作目录=str(目录),
                树端口=str(端口), 树模式=模式 or "")
    组长 = subprocess.Popen([sys.executable, "-c", 树节点代码],
                            env=环境, **平台适配.子进程组启动标志())
    节点pid表 = _等待节点就绪(目录, 端口)
    if len(节点pid表) != 3:
        _强杀整组(组长.pid, 节点pid表)
        try:
            组长.wait(timeout=5)
        except (ChildProcessError, subprocess.TimeoutExpired):
            pass
        raise RuntimeError(f"进程树未就绪：仅收集到 {len(节点pid表)} 个节点 PID "
                           f"{节点pid表}，工作目录 {目录}")
    if 模式 == "组长自杀":
        组长.wait(timeout=10)  # 组长已 os._exit：wait 回收并同步 returncode
    return {"进程组id": 组长.pid, "组长pid": 组长.pid, "节点pid表": 节点pid表,
            "工作目录": str(目录), "端口": 端口, "模式": 模式, "组长对象": 组长}


def 强杀进程组(进程组信息: dict) -> dict:
    """强杀整个进程组，等待回收，清理临时目录，验证端口释放。"""
    组id = 进程组信息["进程组id"]
    端口 = 进程组信息["端口"]
    目录 = Path(进程组信息["工作目录"])
    _强杀整组(组id, 进程组信息.get("节点pid表"))
    组长对象 = 进程组信息.get("组长对象")
    if 组长对象 is not None:
        try:
            组长对象.wait(timeout=10)  # reap 组长僵尸并同步 returncode
        except (ChildProcessError, subprocess.TimeoutExpired):
            pass
    未退出 = _等待退出(进程组信息["节点pid表"])
    # 临时工作目录可能含只读文件/中间目录无写位，删除走唯一实现。
    平台适配.清只读后删除树(目录, 忽略失败=真)
    目录已清理 = not 目录.exists()
    端口可重绑 = _端口可重绑(端口)
    成功 = (not 未退出) and 目录已清理 and 端口可重绑
    return {"进程组id": 组id, "未退出pid": 未退出, "目录已清理": 目录已清理,
            "端口可重绑": 端口可重绑, "成功": 成功}


def 检查残留(进程组信息: dict) -> dict:
    """独立核验：ps 存活 PID、临时目录、端口占用；全清才无残留。"""
    存活pid表 = _进程存活表(进程组信息["节点pid表"])
    目录仍存在 = Path(进程组信息["工作目录"]).exists()
    端口被占 = not _端口可重绑(进程组信息["端口"])
    残留数 = len(存活pid表) + (1 if 目录仍存在 else 0) + (1 if 端口被占 else 0)
    return {"存活pid表": 存活pid表, "目录仍存在": 目录仍存在, "端口仍被占": 端口被占,
            "残留数": 残留数, "无残留": 残留数 == 0}
