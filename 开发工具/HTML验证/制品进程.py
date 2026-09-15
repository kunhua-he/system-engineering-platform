"""制品进程启动、有界输出与进程组回收。"""
from __future__ import annotations
import os, queue, re, signal, subprocess, sys, threading, time
from pathlib import Path
from typing import Any
from 开发工具.HTML验证.常量 import 默认启动超时秒, 输出上限字节
from 公共契约.运行时.运行缓存 import 解析运行缓存根
class _有界输出:
    def __init__(self, 上限字节: int) -> None:
        self.上限 = max(128, int(上限字节))
        self.内容 = bytearray()
        self.锁 = threading.Lock()

    def 追加(self, 数据: bytes) -> None:
        with self.锁:
            self.内容.extend(数据)
            if len(self.内容) > self.上限:
                del self.内容[:len(self.内容) - self.上限]

    def 文本(self) -> str:
        with self.锁:
            return bytes(self.内容).decode("utf-8", errors="replace")

def _读取管道(管道: Any, 缓冲: _有界输出, 事件: queue.Queue[None]) -> None:
    try:
        while True:
            数据 = os.read(管道.fileno(), 4096)
            if not 数据:
                break
            缓冲.追加(数据)
            try:
                事件.put_nowait(None)
            except queue.Full:
                pass
    except (OSError, ValueError):
        pass

def _进程组活跃(进程组id: int) -> bool:
    if os.name != "posix":
        return False
    try:
        结果 = subprocess.run(
            ["ps", "-axo", "pgid=,stat="], capture_output=True, text=True, timeout=2, check=False,
        )
        for 行 in 结果.stdout.splitlines():
            部分 = 行.strip().split(None, 1)
            if len(部分) == 2 and int(部分[0]) == 进程组id and not 部分[1].startswith("Z"):
                return True
        return False
    except (OSError, ValueError, subprocess.TimeoutExpired):
        try:
            os.killpg(进程组id, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

def _回收进程组(进程: subprocess.Popen[Any] | None) -> dict[str, Any]:
    if 进程 is None:
        return {"已回收": True, "模式": "直连", "进程组残留": False}
    进程组id: int | None = None
    if os.name == "posix":
        try:
            进程组id = os.getpgid(进程.pid)
        except ProcessLookupError:
            pass
    if 进程.poll() is None or (进程组id is not None and _进程组活跃(进程组id)):
        try:
            if 进程组id is not None:
                os.killpg(进程组id, signal.SIGTERM)
            else:
                进程.terminate()
        except ProcessLookupError:
            pass
        截止 = time.monotonic() + 2
        while time.monotonic() < 截止:
            if 进程.poll() is not None and (进程组id is None or not _进程组活跃(进程组id)):
                break
            time.sleep(0.03)
        if 进程.poll() is None or (进程组id is not None and _进程组活跃(进程组id)):
            try:
                if 进程组id is not None:
                    os.killpg(进程组id, signal.SIGKILL)
                else:
                    进程.kill()
            except ProcessLookupError:
                pass
    try:
        进程.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            进程.kill()
        except ProcessLookupError:
            pass
        try:
            进程.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    残留 = bool(进程组id is not None and _进程组活跃(进程组id))
    for 管道 in (进程.stdin, 进程.stdout, 进程.stderr):
        if 管道 is not None and not 管道.closed:
            try:
                管道.close()
            except (OSError, ValueError):
                pass
    return {
        "已回收": 进程.poll() is not None and not 残留,
        "模式": "独立进程组" if 进程组id is not None else "单进程",
        "pid": 进程.pid,
        "进程组id": 进程组id,
        "退出码": 进程.poll(),
        "进程组残留": 残留,
    }

受管临时根目录名 = "HTML验证临时"


def _受管临时根目录() -> Path | None:
    """验证链的受管临时根父目录（`<缓存根>/HTML验证临时`）。

    与 `场景执行器._建场景临时根` 同源：场景临时目录就建在这里，本函数把它
    显式授权给制品子进程的 Git 仓库根白名单（见下方 `工作区允许提交根` 说明）。
    """
    try:
        系统根 = Path(__file__).resolve().parents[2]
        目录 = 解析运行缓存根(系统根) / 受管临时根目录名
    except Exception:
        return None
    return 目录 if 目录.is_dir() else None


def _启动制品(
    启动器: Path,
    制品目录: Path,
    端口: int,
    启动超时秒: float = 默认启动超时秒,
    上限字节: int = 输出上限字节,
) -> tuple[subprocess.Popen[Any], int, dict[str, str]]:
    环境 = os.environ.copy()
    # HTML 黑盒是本地受管验证链；制品默认要求凭证时，为验证子进程
    # 注入非生产测试凭证，真实请求仍由网关按自身策略校验。
    环境.setdefault("系统库网关凭证", "html-blackbox-verifier")
    # Git 能力（提交/切换分支/合并分支）的仓库根白名单只认「制品自己的仓库根 +
    # 环境变量显式授权 + 系统临时目录」。而黑盒的场景受管临时根现在落在
    # `<源码仓库>/工程缓存/HTML验证临时/`（见 场景执行器._建场景临时根），
    # 制品看不到它 → 场景里的临时 Git 仓被判 `路径越界`（HTTP 400），
    # `Git操作.临时仓库完整正向链` 19 步全红（2026-09-15 实测）。
    # 这里把验证链自己的受管目录显式授权给制品子进程——只授权本验证链的
    # 临时目录与源码仓库根，不放开任意路径。
    受管临时根 = _受管临时根目录()
    if 受管临时根 is not None:
        已有 = 环境.get("工作区允许提交根", "")
        环境["工作区允许提交根"] = os.pathsep.join(
            [x for x in (已有, str(受管临时根)) if x])
    进程 = subprocess.Popen(
        [sys.executable, "-u", str(启动器), "--端口", str(端口), "--不自动打开"],
        cwd=str(制品目录),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
        env=环境,
    )
    标准输出 = _有界输出(上限字节)
    标准错误 = _有界输出(上限字节)
    事件: queue.Queue[None] = queue.Queue(maxsize=1)
    线程表 = [
        threading.Thread(target=_读取管道, args=(进程.stdout, 标准输出, 事件), daemon=True),
        threading.Thread(target=_读取管道, args=(进程.stderr, 标准错误, 事件), daemon=True),
    ]
    for 线程 in 线程表:
        线程.start()
    截止 = time.monotonic() + max(0.05, 启动超时秒)
    try:
        while time.monotonic() < 截止:
            文本 = 标准输出.文本()
            匹配 = re.search(r"127\.0\.0\.1:(\d+)", 文本)
            if 匹配 and ("已启动" in 文本 or "启动" in 文本):
                return 进程, int(匹配.group(1)), {"stdout": 文本, "stderr": 标准错误.文本()}
            if 进程.poll() is not None:
                raise RuntimeError(
                    f"制品启动失败(退出码={进程.returncode}): stdout={文本!r} stderr={标准错误.文本()!r}"
                )
            try:
                事件.get(timeout=min(0.05, max(0.001, 截止 - time.monotonic())))
            except queue.Empty:
                pass
        raise RuntimeError(
            f"制品启动超时({启动超时秒}s): stdout={标准输出.文本()!r} stderr={标准错误.文本()!r}"
        )
    except BaseException:
        _回收进程组(进程)
        raise
