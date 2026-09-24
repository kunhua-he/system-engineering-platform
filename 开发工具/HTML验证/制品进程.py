"""制品进程启动、有界输出与进程组回收。

跨平台纪律：本文件**不再自带平台判断**（无 ``os.name`` / ``os.killpg`` /
``os.getpgid`` / ``start_new_session``），进程组启动、存活探测、整组终止一律走
``公共契约.运行时`` 的收口层（``平台适配.子进程组启动标志``、``进程终止``）。
"""
from __future__ import annotations
from 公共契约.基础类型.逻辑类型 import 真, 假
import os, queue, re, shutil, subprocess, sys, threading, time
from pathlib import Path
from typing import Any
from 开发工具.HTML验证.常量 import 默认启动超时秒, 输出上限字节
from 公共契约.运行时 import 平台适配, 进程终止
from 公共契约.运行时.运行缓存 import 解析运行缓存根

#: 进程状态工具（``ps``）的绝对路径；由 ``shutil.which`` 按能力探测，**不按平台名判**。
#: 存在 → 可用它排除僵尸得到「活动成员」语义；不存在（如 Windows）→ 退回收口层探活。
_进程状态工具 = shutil.which("ps")


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
    """进程组内是否仍有**活动（非僵尸）**成员。

    优先用 ``ps`` 扫描真实组归属：僵尸成员不算活跃——这与收口层 ``进程存活`` /
    ``按组号探活`` 的「僵尸计为存活」语义**刻意不同**，本函数判的是「组是否还占着
    资源」，僵尸已不占资源。

    ``ps`` 不可用（如 Windows 无此工具）时退回收口层 ``按组号探活``：**按能力探测，
    不按平台名硬判**（``shutil.which("ps")`` 判的是「这台机器有没有这个进程状态工具」），
    平台差异全在收口层承担。

    **为什么本函数留在本域**（2026-09-24 批R·R-6）：收口层 ``进程组存活`` 是「僵尸计为
    存活」的**回收口径**，本函数判的是「组是否还占着资源」的**验收口径** —— 两者刻意不同，
    故它不是第二份组回收实现，而是本域判据。
    """
    if _进程状态工具:
        try:
            结果 = subprocess.run(
                [_进程状态工具, "-axo", "pgid=,stat="], capture_output=True, text=True, timeout=2, check=False,
            )
            for 行 in 结果.stdout.splitlines():
                部分 = 行.strip().split(None, 1)
                if len(部分) == 2 and int(部分[0]) == 进程组id and not 部分[1].startswith("Z"):
                    return 真
            return 假
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return 进程终止.按组号探活(进程组id)


def _回收进程组(进程: subprocess.Popen[Any] | None) -> dict[str, Any]:
    """回收制品进程整组，返回回收读数；**整组收敛唯一实现在 公共契约/运行时/进程终止**。

    「终止 → 宽限 → 强杀 → 等整组收敛」全在收口层 `结束并留痕` 内完成（收口层自己按
    POSIX 进程组 / Windows 进程树判定，且以**整组**收敛为准：组长已退出、同组子孙仍在
    判未收敛并升级强杀；回收失败即登记回收失败留痕，不静默）。本函数只做两件本域的事：

    ① 记录**模式**（有组号 = 独立进程组，否则单进程）与退出码；
    ② 用本域 `_进程组活跃` 判**残留** —— 它判的是「组是否还占着资源」（僵尸不算），
       与收口层「僵尸计为存活」刻意不同（判据见该函数）。
    """
    if 进程 is None:
        return {"已回收": True, "模式": "直连", "进程组残留": False}
    进程组id: int | None = 进程终止.进程组号(进程)
    收敛 = 进程终止.结束并留痕(进程, 位置="制品进程._回收进程组", 宽限秒=2.0, 等待秒=2.0)
    残留 = bool(进程组id is not None and _进程组活跃(进程组id))
    for 管道 in (进程.stdin, 进程.stdout, 进程.stderr):
        if 管道 is not None and not 管道.closed:
            try:
                管道.close()
            except (OSError, ValueError):
                pass
    return {
        "已回收": 收敛 and not 残留,
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


def _解析监听端口(文本: str) -> int | None:
    """从制品启动输出里取**监听端口**（未完成事项 #176）。

    为什么不能取首个匹配（原实现 `re.search(r"127\\.0\\.0\\.1:(\\d+)", 文本)`）：
    制品启动期会先打印「连接网关 127.0.0.1:40007」，再打印「已启动 127.0.0.1:45080」；
    取首匹配会把**网关端口 40007** 当成监听端口 ⇒ 后续健康检查与场景验证
    全打到网关而非制品，**功能性假绿**（全绿假象或全红）。
    现口径：优先取「已启动」同一行里的回环地址，取不到再退回全部匹配的**最后一个**
    （最后打印的才是真正的监听地址）；两者都取不到回 None，由调用方继续等待。
    """
    候选 = re.findall(r"已启动[^\n]*?127\.0\.0\.1:(\d+)", 文本)
    if not 候选:
        候选 = re.findall(r"127\.0\.0\.1:(\d+)", 文本)
    return int(候选[-1]) if 候选 else None


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
        # 平台差异收口：POSIX 是 start_new_session（setsid 独立组），
        # Windows 是 creationflags=CREATE_NEW_PROCESS_GROUP
        **平台适配.子进程组启动标志(),
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
            if "已启动" in 文本 or "启动" in 文本:
                监听端口 = _解析监听端口(文本)
                if 监听端口 is not None:
                    return 进程, 监听端口, {"stdout": 文本, "stderr": 标准错误.文本()}
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
    except BaseException as 错误:
        # #168（2026-09-20）：原实现调了 `_回收进程组(进程)` 但**丢弃返回值** ——
        # 调用方（单实例验证）拿不到真实回收结论，只能把 `报告.资源回收` 硬编码成
        # 「已回收: True」，`进程组残留=True` 时照样谎报已回收（掩盖资源泄漏）。
        # 现把真实回收结果挂在异常对象上回传（不改函数签名/不引入第二返回值通道）。
        回收结果 = _回收进程组(进程)
        try:
            错误.启动回收结果 = 回收结果      # type: ignore[attr-defined]
        except (AttributeError, TypeError):   # 极少数异常对象禁止挂属性时静默跳过
            pass
        raise
