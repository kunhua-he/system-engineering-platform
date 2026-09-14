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
        # 超时/异常后强制回收独立进程组，避免子孙进程残留；
        # 回收失败必须随失败说明一起回报（哲学第 15 条：失败要明确，不允许静默吞掉）
        清理说明 = ""
        if 进程 is not None:
            try:
                _终止进程组(进程, 强制=True)
            except Exception as 清理错误:
                清理说明 = f"（强制回收失败：{清理错误}）"
        return 结果.失败("执行失败", f"{错误}{清理说明}", 来源="进程管理")


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

# ── macOS sandbox-exec 内核沙箱执行（迁移自 V3 终端工具 沙箱处理器） ────────

默认沙箱输出上限字节 = 1 * 1024 * 1024


def _构建沙箱配置(工作目录: str) -> str:
    """返回 sandbox-exec profile：系统只读 + 仅工作目录可读写。

    只读放开的位置限定为系统工具/动态库目录与 Python 解释器自身 prefix，
    不放开整个 /Users，避免越出工作区读用户其他文件。
    """
    import sys as _sys
    py_prefix = os.path.realpath(_sys.prefix)
    py_base = os.path.realpath(_sys.base_prefix)
    return f"""(version 1)
(import "system.sb")
(allow process-fork)
(allow process-exec)
(allow network*)
(allow mach-lookup)
(allow sysctl-read)
(allow file-read-metadata)
(allow file-read*
  (subpath "/usr") (subpath "/bin") (subpath "/sbin")
  (subpath "/System") (subpath "/Library") (subpath "/opt/homebrew")
  (subpath "/private/var/db/dyld") (subpath "/private/var/folders")
  (subpath "/private/var/select") (subpath "/dev")
  (subpath "/private/etc/ssl")
  (subpath "{py_prefix}") (subpath "{py_base}")
  (literal "/private/etc/hosts") (literal "/private/etc/resolv.conf"))
(allow file-read* file-write* (subpath "{工作目录}"))
"""


def _沙箱安全环境(工作目录: str) -> dict:
    """子进程环境白名单：不整体转发宿主环境，避免泄露密钥/令牌。"""
    from pathlib import Path as _Path
    临时目录 = _Path(工作目录) / ".tmp"
    临时目录.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": 工作目录,
        "WORKSPACE": 工作目录,
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "en_US.UTF-8"),
        "TMPDIR": str(临时目录),
    }


def 沙箱执行命令(
    命令: str = None,
    工作目录: str = None,
    超时秒: float = None,
    输出上限字节: int = None,
    环境变量: dict = None,
) -> 结果:
    """在 macOS sandbox-exec 内核沙箱内执行 shell 命令。

    - 内核级隔离：系统目录只读，只有「工作目录」可读写；
    - Linux 等无 sandbox-exec 的平台 **fail-closed**（拒绝执行，不降级为无沙箱）；
    - 输出上限内截断；超时用 killpg 回收整棵进程树；
    - 环境变量走白名单，可用 环境变量 追加白名单内的键。

    注意：危险命令检测不在此能力内（那是策略不是机制），由调用方先做。
    """
    from pathlib import Path as _Path

    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    if not isinstance(工作目录, str) or not 工作目录.strip():
        return 结果.失败("参数不合法", "工作目录必填（沙箱唯一可读写目录）", 来源="进程管理")
    工作区 = _Path(工作目录).resolve()
    if not 工作区.is_dir():
        return 结果.失败("目录不存在", f"工作目录不存在: {工作区}", 来源="进程管理")
    上限字节 = int(输出上限字节) if isinstance(输出上限字节, int) and 输出上限字节 > 0 \
        else 默认沙箱输出上限字节
    超时 = float(超时秒) if isinstance(超时秒, (int, float)) and 超时秒 > 0 else 60.0

    import shutil as _shutil
    import sys as _sys
    if not (_sys.platform == "darwin" and _shutil.which("sandbox-exec")):
        return 结果.失败(
            "沙箱不可用",
            "当前平台无 sandbox-exec 内核沙箱，沙箱执行已禁用（fail-closed，不降级）",
            来源="进程管理",
        )

    环境 = _沙箱安全环境(str(工作区))
    for 键, 值 in (环境变量 or {}).items():
        if 键 in 环境:
            环境[键] = str(值)
    配置 = _构建沙箱配置(str(工作区))
    argv = ["sandbox-exec", "-p", 配置, "/bin/sh", "-c", 命令]

    import tempfile as _tempfile
    import uuid as _uuid
    令牌 = _uuid.uuid4().hex
    输出文件 = _Path(_tempfile.gettempdir()) / f".沙箱输出_{令牌}.txt"
    错误文件 = _Path(_tempfile.gettempdir()) / f".沙箱错误_{令牌}.txt"
    进程 = None
    try:
        with 输出文件.open("wb") as 出, 错误文件.open("wb") as 错:
            进程 = subprocess.Popen(
                argv, cwd=str(工作区), stdout=出, stderr=错,
                env=环境, start_new_session=(os.name == "posix"))
            超时标志 = False
            try:
                进程.wait(timeout=超时)
            except subprocess.TimeoutExpired:
                超时标志 = True
                _终止进程组(进程, 强制=True)
        标准输出 = _读受限(输出文件, 上限字节)
        错误输出 = _读受限(错误文件, 上限字节)
        if 超时标志:
            return 结果.失败(
                "超时", f"沙箱命令执行超过 {超时} 秒",
                来源="进程管理",
                详情={"标准输出": 标准输出, "错误输出": 错误输出},
            )
        return 结果.成功结果({
            "退出码": 进程.returncode,
            "成功执行": 进程.returncode == 0,   # 命令执行完成且退出码为 0
            "标准输出": 标准输出,
            "错误输出": 错误输出,
            "沙箱": "macOS sandbox-exec",
        })
    except Exception as 错误:
        if 进程 is not None:
            try:
                _终止进程组(进程, 强制=True)
            except Exception:
                pass
        return 结果.失败("执行失败", str(错误), 来源="进程管理")
    finally:
        for 文件 in (输出文件, 错误文件):
            try:
                文件.unlink(missing_ok=True)
            except OSError:
                pass


def _读受限(路径, 上限字节: int) -> str:
    """按上限读取子进程输出文件，超限截断并标注。"""
    try:
        原始 = 路径.read_bytes()
    except OSError:
        return ""
    截断 = len(原始) > 上限字节
    if 截断:
        原始 = 原始[:上限字节]
    文本 = 原始.decode("utf-8", errors="replace")
    if 截断:
        文本 += f"\n... [truncated at {上限字节} bytes]"
    return 文本
