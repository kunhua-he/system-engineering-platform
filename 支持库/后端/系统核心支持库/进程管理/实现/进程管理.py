"""进程管理原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：启动/终止/查询/等待进程（参考易语言系统核心支持库）。
句柄模式：启动进程返回句柄，状态机统一生命周期（超时/释放自动杀进程组）。
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from 公共契约.基础类型.逻辑类型 import 假
from 公共契约.基础类型.结果类型 import 结果
from 公共契约.句柄体系 import 句柄体系, 句柄类型_资源
from 公共契约.运行时 import 平台适配, 进程终止, 执行耗时账本
from 公共契约.运行时.有界IO import 受限读取, 受限通信, 默认子进程输出上限字节
from 公共契约.运行时.取消登记 import 当前 as 当前取消令牌
from 公共契约.运行时.运行缓存 import 解析运行缓存根
from 公共契约.运行时.导入前缀 import 取系统根

句柄系统 = 句柄体系()
进程表: dict[int, dict] = {}
# 容错路径留痕（哲学第 3 条 2 项：不许 except: pass 吞掉）
临时文件问题: list[str] = []

锁 = threading.Lock()



# 尽力清理/降级场景的异常记录（不阻断主流程）。上限照对照件 `模型连接器.py:64`（1000 条）。
降级记录表上限 = 1000
降级记录表: deque[str] = deque(maxlen=降级记录表上限)


def 降级记录摘要() -> dict:
    """降级记录表的有界只读视图（供诊断/测试；不注册为能力，故不进 `__all__`）。

    收口前本表是无界 list 且全仓 0 读取方（只写不读的死登记）：本函数是唯一读取入口。
    """
    return {
        "在册条数": len(降级记录表),
        "上限": 降级记录表上限,
        "最近记录": list(降级记录表),
    }


def _解析超时秒(超时秒, 默认秒: float | None, 留空语义: str) -> tuple[float | None, str]:
    """把 `超时秒` 收口成「秒数或 None」，非法输入返回原因文本（空串=合法）。

    - 留空（None）→ `默认秒`（None 表示**无限等待**：不设隐式截止）；
    - 非数字 / 布尔 / 非正数 → 拒绝（原因文本）。

    为什么不沿用 `float(超时秒 or 60)`：`0` 是假值，会被静默改写成 60 秒，
    调用方显式传 0（意图「不等待」）却得到 60 秒的等待与强杀；显式参数被偷偷
    改写属于「参数只收不用」。这里一律显式裁定：留空取默认，非正数拒收。
    """
    if 超时秒 is None:
        return 默认秒, ""
    if isinstance(超时秒, bool) or not isinstance(超时秒, (int, float)):
        return None, f"超时秒必须是正数；留空表示{留空语义}"
    if not float(超时秒) > 0:
        return None, f"超时秒必须大于 0（收到 {超时秒!r}）；留空表示{留空语义}"
    return float(超时秒), ""


def _解析经shell(经shell) -> tuple[bool, str]:
    """把 `经shell` 收口成「真/假」，非法输入返回原因文本（空串=合法）。

    - 留空（None）→ **假**：argv 直启，历史行为逐字不变（默认档不动）；
    - 真/假（bool）→ 原样；
    - 其它（数字 / 文本 / 列表…）→ 拒绝并点名。

    为什么不写 `bool(经shell)`：逻辑型契约是**真 bool**（`公共契约/基础类型/逻辑类型`），
    把 `1`/`"true"`/非空列表静默当真，等于替调用方猜意图（「参数只收不用」的反面）；
    显式参数只许显式裁定 —— 与 `_解析超时秒` 同一口径。
    """
    if 经shell is None:
        return 假, ""
    if isinstance(经shell, bool):
        return 经shell, ""
    return 假, f"经shell 必须是 真/假（逻辑型）；收到 {经shell!r}"


# 命令文本拆分（B-28）与它的 `posix=False` 口径**已整体下沉收口层**
# `公共契约.运行时.平台适配.拆分命令文本()`：本文件不再自带 `_拆分命令` / `_剥成对引号`
# 及其平台分支（第一轮审计 §二 B1-2 / §四 D-1 —— 原文与本文件第 88 行的平台分叉冲突）。

系统根 = 取系统根(__file__)

# 沙箱输出临时文件目录：落本仓固定运行缓存目录（铁律「测试产物和快照只放工程缓存」），
# 不落系统 /tmp —— 子进程被 SIGKILL 时 finally 不执行，散在系统 /tmp 的残片无人回收、
# 多次运行无界累积（报告 BUG-12）。保留策略按年龄 + 条数双限，既不无界增长，
# 也不可能删掉正在进行中的调用（新文件 mtime 最新，排在保留窗口最前）。
沙箱输出目录名 = ("进程管理", "沙箱输出")
沙箱输出保留秒 = 24 * 3600
沙箱输出保留条数 = 200
沙箱输出文件模式 = (".沙箱输出_*.txt", ".沙箱错误_*.txt")


class _启动输出通道:
    """`启动进程` 带就绪轮询时建立的输出排空通道（进程存活期内的唯一管道读者）。

    为什么必须有：子进程 stdout/stderr 都是管道，子进程在就绪前写满管道缓冲
    （macOS 常见 64KB）就阻塞在 write 上 → 端口永不监听 → 就绪轮询空转到超时；
    历史实现只在 `poll() is not None`（进程已退出）之后才读一次 stderr，轮询
    期间从不读 stdout，等于把子进程的输出写死在管道里（报告 BUG-04）。

    为什么由通道长期持有：通道建立后它就是这两个管道的唯一读者。若就绪成功后把它
    撤掉、再由 `等待进程结束` 另起读者，两个读者会争抢同一管道（谁先读到算谁的），
    输出会静默丢字节。因此 `等待进程结束` 复用它而不另开读者。

    有界性复用 公共契约.运行时.有界IO.受限读取（读满上限后继续排空），本类只负责
    「谁在什么时候读、读完归谁」，不复制读取/截断判定。
    """

    def __init__(self, 进程: subprocess.Popen,
                 输出上限字节: int = 默认子进程输出上限字节) -> None:
        self.进程 = 进程
        self.输出上限字节 = 输出上限字节
        self.缓冲: dict[str, bytearray] = {"标准输出": bytearray(), "错误输出": bytearray()}
        self.超限事件 = threading.Event()
        self.线程: list[threading.Thread] = []
        for 名称, 流 in (("标准输出", 进程.stdout), ("错误输出", 进程.stderr)):
            线程 = threading.Thread(target=self._排空, args=(名称, 流),
                                  daemon=True, name=f"进程输出排空-{名称}")
            线程.start()
            self.线程.append(线程)

    def _排空(self, 名称: str, 流) -> None:
        if 流 is None:
            return
        try:
            内容, _超限 = 受限读取(流, self.输出上限字节, 超限回调=self.超限事件.set)
        except (OSError, ValueError) as 错误:
            # 释放句柄/外部关闭管道导致的收尾中断：留痕不吞（哲学第 3 条 2 项）
            临时文件问题.append(f"{名称} 排空中断（管道已关闭）: {错误}")
            return
        self.缓冲[名称].extend(内容)

    def 收口(self, 等待秒: float) -> tuple[bytes, bytes, bool]:
        """限时等排空收口（进程退出或管道关闭即收口），返回（输出、错误、是否超限）。"""
        for 线程 in self.线程:
            线程.join(timeout=max(0.0, float(等待秒)))
        return (bytes(self.缓冲["标准输出"]), bytes(self.缓冲["错误输出"]),
                self.超限事件.is_set())

    def 已收口(self) -> bool:
        return not any(线程.is_alive() for 线程 in self.线程)


def _取条目(句柄: int | None) -> tuple[dict | None, str]:
    """按句柄取进程表条目（含输出通道）；无效句柄返回（None，原因）。"""
    if isinstance(句柄, bool) or not isinstance(句柄, int) or not 1 <= 句柄 <= 999999:
        return None, "句柄必须是1到999999的整数"
    有效, 原因 = 句柄系统.校验(句柄id=句柄)
    if not 有效:
        return None, 原因
    条目 = 进程表.get(句柄)
    if 条目 is None:
        return None, f"进程句柄 {句柄} 不存在"
    return 条目, ""


def _取进程(句柄: int | None) -> tuple[subprocess.Popen | None, str]:
    条目, 原因 = _取条目(句柄)
    if 条目 is None:
        return None, 原因
    return 条目.get("进程对象"), ""


def 启动进程(命令: str = None, 参数: list = None, 工作目录: str = None,
             环境变量: dict = None, 超时秒: int = None,
             就绪地址: str = None, 就绪超时秒: float = None,
             经shell: bool = None) -> 结果:
    """启动外部进程。返回 {句柄, PID, 命令}。

    ``命令`` 收**一条完整命令行**（「可执行文件 + 参数」，按空白切分），与
    `执行命令` / `沙箱执行命令` 同一个形状 —— 调用方只写「要跑什么」，
    不必把可执行文件与参数拆成两个字段（2026-09-23 华哥：「传参实际上面要传参到
    内容，而不是一大堆杂项」）。可执行文件按 PATH 解析（`execvp` 语义）。

    ``参数`` 是**逐项精确控制 argv 的补充口**：与 ``命令`` 的切分结果拼接，
    供参数本身含空白/特殊字符时用（``命令`` 按空白切分，写不出含空格的单个参数）。
    不需要精确控制就别传它。

    ``经shell``（2026-09-23 新增，默认 **假**）—— ``假`` 时 argv 直启（历史行为逐字
    不变）；``真`` 时把 ``命令`` 整串交给本平台 shell 解释器（POSIX ``/bin/sh -c`` /
    Windows ``cmd /c``，由 `平台适配.经shell命令表()` 统一裁定平台差异），于是
    管道 / 重定向 / ``&&`` / 变量展开 / shell 内建全部可用。**长任务异步腿要 shell 语义
    就传它**，不必再自己写 `bash -c "…"` 或用 `参数=['-c', …]` 手拼。

    直启（不经 shell，即 ``经shell`` 留空/假）时**不内建**危险命令检测：策略拦截落在
    执行命令 / 沙箱执行命令 两条 shell 文本入口（S-06 接线），
    需要策略前置的调用方请走那两条能力，或在调用本能力前自行做策略判定。

    ``环境变量`` —— ★ **语义与 `执行命令` 的同名参数相反**（2026-09-23 实测）：本能力把它
    原样交给 ``Popen(env=…)`` ⇒ **整体替换、不合并**；留空则继承当前进程环境。
    而 `执行命令` 的同名参数是**在安全白名单环境上追加**。故这里传 ``{"X": "1"}``
    会让子进程**丢掉 PATH**（实测症状：``/bin/sh: python3.14: command not found``、
    退出码 127 —— **静默失败**，看着像解释器没装）。要保留 PATH 就自己带上：
    ``{"PATH": os.environ["PATH"], "X": "1"}``。
    两者要不要统一口径（合并 vs 替换）**待裁**，见债务清单。
    """
    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    经shell开关, 经shell原因 = _解析经shell(经shell)
    if 经shell原因:
        return 结果.失败("参数不合法", 经shell原因, 来源="进程管理")
    try:
        # 经shell=真 的解释器 argv（含 POSIX/Windows 差异）由收口层唯一实现，
        # 本处不含任何平台判断。
        cmd = (平台适配.经shell命令表(命令, 参数) if 经shell开关
               else 命令.split() + list(参数 or []))
        # 独立进程组：平台差异（POSIX setsid / Windows 新建进程组标志）只在
        # 平台适配.子进程组启动标志() 内判定，调用点不写平台判断。
        进程 = subprocess.Popen(cmd, cwd=工作目录, env=环境变量,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **平台适配.子进程组启动标志())
    except Exception as 错误:
        return 结果.失败("启动失败", str(错误), 来源="进程管理")
    # 就绪轮询必须有独立排空者：子进程在就绪前写满管道缓冲（约 64KB）就会卡在
    # write 上，端口永不监听，轮询只会空转到超时（报告 BUG-04 管道死锁）。
    # 通道在轮询开始之前建立，成为这两个管道在进程存活期内的唯一读者。
    输出通道 = _启动输出通道(进程) if 就绪地址 else None
    if 就绪地址:
        try:
            主机, 端口文本 = 就绪地址.rsplit(":", 1)
            端口 = int(端口文本)
            截止 = time.monotonic() + (float(就绪超时秒) if 就绪超时秒 else 5.0)
            while time.monotonic() < 截止:
                if 进程.poll() is not None:
                    已排空错误输出 = 输出通道.收口(1.0)[1] if 输出通道 else b""
                    错误输出 = 已排空错误输出[:2000]
                    return 结果.失败("启动失败", f"进程在就绪前退出: {错误输出.decode('utf-8', 'replace')}", 来源="进程管理")
                try:
                    with socket.create_connection((主机, 端口), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.02)
            else:
                _终止进程组(进程)
                if 输出通道 is not None:
                    输出通道.收口(2.0)
                return 结果.失败("启动超时", f"就绪地址未监听: {就绪地址}", 来源="进程管理")
        except (TypeError, ValueError) as 错误:
            _终止进程组(进程)
            if 输出通道 is not None:
                输出通道.收口(2.0)
            return 结果.失败("参数不合法", f"就绪地址必须是 主机:端口: {错误}", 来源="进程管理")
    with 锁:
        对象 = 句柄系统.创建句柄(句柄类型=句柄类型_资源, 资源id="进程", 所有者="")
        进程表[对象.句柄id] = {"进程对象": 进程, "PID": 进程.pid, "命令": 命令,
                              "输出通道": 输出通道}
    return 结果.成功结果({"句柄": 对象.句柄id, "PID": 进程.pid, "命令": 命令})


def _终止进程组(进程: subprocess.Popen, 强制: bool = True, 宽限秒: float = 2.0) -> None:
    """进程组终止：唯一实现在 公共契约.运行时.进程终止.强制结束子进程。

    终止 → 宽限 → 强杀 → 复查死透全在收口层内完成（POSIX 按进程组 / Windows
    按进程树由收口层自己判定）；本处不再持有平台判断、信号号或 killpg 调用。
    强制 为真时不设宽限（直接升级强杀），为假时给 宽限秒 让进程自行退出。
    """
    进程终止.强制结束子进程(进程, 宽限秒=0.0 if 强制 else 宽限秒, 等待秒=宽限秒)


def 终止进程(句柄: int | None = None, 强制: bool = None) -> 结果:
    """终止进程（回收整个进程组）。返回 {已终止, 退出码}。"""
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
    """等待进程结束。返回 {退出码, 标准输出, 错误输出}。

    超时语义（B-27）：
    - `超时秒` 留空 = **无限等待**（不设隐式截止）。历史实现把留空当 60 秒，
      于是默认参数就能强杀一个正在健康运行的长驻进程；空值的正确含义是
      「等到进程自己结束」。
    - 显式给出 `超时秒` = 只结束本次等待：到点返回失败 `超时`，**不终止进程**，
      管道与已读输出保持原样，调用方可以再等，或显式 `终止进程` / `释放句柄`。
      （历史实现在超时点直接回收进程组，等待 API 变成了隐式杀进程 API。）
    - 非正数 / 非数字一律 `参数不合法`，不静默改写成默认值。

    输出读取（与 `启动进程` 的就绪排空通道配合，不另开读者）：
    就绪启动的进程，输出由启动期建立的通道排空；**非就绪启动的进程在这里补建同一个
    排空通道**并记进条目，之后一律复用 —— 通道是这两条管道的唯一读者。历史实现让非
    就绪进程走「一次性有界通信」，它在返回前就关闭 stdout/stderr：超时后进程再写输出
    即 EPIPE 乱死、读取线程还会撞上已关闭的流，所以等待一律由通道承载。
    """
    条目, 原因 = _取条目(句柄)
    if 条目 is None:
        return 结果.失败("句柄失效", 原因, 来源="进程管理")
    进程 = 条目.get("进程对象")
    if 进程 is None:
        return 结果.失败("句柄失效", f"进程句柄 {句柄} 无进程对象", 来源="进程管理")
    上限等待, 超时原因 = _解析超时秒(超时秒, None, "无限等待（等到进程结束）")
    if 超时原因:
        return 结果.失败("参数不合法", 超时原因, 来源="进程管理")
    通道: _启动输出通道 | None = 条目.get("输出通道")
    if 通道 is None:
        try:
            通道 = _启动输出通道(进程)
        except (OSError, ValueError) as 错误:
            return 结果.失败("等待失败", f"建立输出排空通道失败: {错误}", 来源="进程管理")
        条目["输出通道"] = 通道      # 通道即唯一读者，后续等待复用同一通道
    try:
        try:
            if 上限等待 is None:
                进程.wait()
            else:
                进程.wait(timeout=上限等待)
        except subprocess.TimeoutExpired:
            # 只结束本次等待，不销毁进程对象（B-27 去掉「超时即杀」）
            return 结果.失败(
                "超时",
                f"等待超时（{上限等待} 秒）：进程仍在运行，未被终止；"
                "如需终止请调用 终止进程 或 释放句柄，也可再次等待",
                来源="进程管理",
                详情={"PID": 进程.pid, "超时秒": 上限等待, "进程已被终止": False},
            )
        stdout, stderr, 已超限 = 通道.收口(5.0)
        if 已超限:
            return 结果.失败("超出限制", "进程输出超过上限", 来源="进程管理")
        return 结果.成功结果({"退出码": 进程.returncode,
                                "标准输出": (stdout or b"").decode("utf-8", errors="replace"),
                                "错误输出": (stderr or b"").decode("utf-8", errors="replace")})
    except Exception as 错误:
        return 结果.失败("等待失败", str(错误), 来源="进程管理")


def 执行命令(命令: str = None, 超时秒: float = None, 工作目录: str = None,
             经shell: bool = None) -> 结果:
    """执行命令并等待完成。返回 {退出码, 标准输出, 错误输出}。

    ``经shell``（2026-09-23 新增，默认 **假**）—— ``假`` 时按「可执行文件 + 参数」
    直启（历史行为逐字不变）；``真`` 时把 ``命令`` 整串交给本平台 shell 解释器
    （POSIX ``/bin/sh -c`` / Windows ``cmd /c``，平台差异由 `平台适配.经shell命令表()`
    统一裁定），于是管道 / 重定向 / ``&&`` / 变量展开 / shell 内建全部可用。
    要 shell 语义就传它，不必自己写 `sh -c "…"` 或落脚本文件。

    执行前经能力调用服务取 `命令安全.检测危险命令`（S-06 接线）：命中危险命令
    返回失败（错误码 `危险命令`），不发起进程；检测器不可用时留痕降级放行。
    **``经shell`` 两种取值下都在直启/解释器启动之前拦截**（shell 形态尤其需要前置策略）。
    """
    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    经shell开关, 经shell原因 = _解析经shell(经shell)
    if 经shell原因:
        return 结果.失败("参数不合法", 经shell原因, 来源="进程管理")
    执行上限秒, 超时原因 = _解析超时秒(超时秒, 60.0, "按参数契约默认 60 秒")
    if 超时原因 or 执行上限秒 is None:
        return 结果.失败("参数不合法", 超时原因 or "超时秒不合法", 来源="进程管理")
    危险命中 = _前置危险命令检测(命令)
    if 危险命中 is not None:
        return 危险命中
    # 不用 shell=True（参数列表直启）：进程自成独立组后，超时/异常由收口层
    # 整组回收，避免 shell 子孙进程泄漏。
    # 命令文本拆分的平台差异（B-28）已收口到 平台适配.拆分命令文本()：
    # Windows 用 posix=False 保住反斜杠路径，**本处不含任何平台分叉**。
    # 经shell=真 时命令整串交给解释器（`sh -c` 形态），不做 argv 拆分 —— 引号/管道
    # 的解析权归 shell，这正是「要 shell 语义」的用意；解释器 argv 由收口层给出。
    if 经shell开关:
        命令表 = 平台适配.经shell命令表(命令)
    else:
        try:
            命令表 = 平台适配.拆分命令文本(命令)
        except ValueError as 错误:
            return 结果.失败("参数不合法", f"命令解析失败: {错误}", 来源="进程管理")
    if not 命令表 or not 命令表[0].strip():
        return 结果.失败("参数不合法", "命令为空", 来源="进程管理")
    进程 = None
    取消令牌 = 当前取消令牌()
    开始时刻 = time.monotonic()
    try:
        进程 = subprocess.Popen(
            命令表, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=工作目录, **平台适配.子进程组启动标志())
        取消记录: dict = {}
        stdout, stderr, 已超时, 已超限 = 受限通信(
            进程, 超时秒=执行上限秒,
            输出上限字节=默认子进程输出上限字节,
            终止回调=lambda: _终止进程组(进程),
            # 取消判定：网关连接断开时置位的取消令牌（`公共契约.运行时.取消登记`）。
            # 未登记（跨进程执行、直接单测调用）时传 None —— 行为与新增前逐字相同。
            取消判定=(lambda: 取消令牌.已取消) if 取消令牌 is not None else None,
            取消记录=取消记录,
        )
        # 执行耗时账本（华哥 2026-09-23）：**开关关着时 `记一笔` 第一行就返回、不碰盘**
        # （见 公共契约/运行时/执行耗时账本.py）。放在这里而不是各 return 分支里：
        # 一处记录覆盖下面「已取消 / 超时 / 超限 / 正常」四条出口，不会漏掉某一条。
        执行耗时账本.记一笔(
            来源="系统核心支持库.进程管理.执行命令", 命令=命令,
            耗时秒=time.monotonic() - 开始时刻,
            退出码=getattr(进程, "returncode", None),
            工作目录=str(工作目录 or ""),
            输出字节=len(stdout or b"") + len(stderr or b""))
        if 取消记录.get("已取消"):
            # 「调用方已离开」与「执行超时」是两件事，必须分开报（哲学第 3 条 2 项）：
            # 前者说明本次执行是被断连回收的，后者说明命令本身跑不完。错误码用已登记的
            # `调用已取消`（网关 公开错误说明表 已收录，映射 409）。
            return 结果.失败(
                "调用已取消",
                "调用方已离开（连接断开），已整组回收子进程",
                来源="进程管理",
                详情={"PID": 进程.pid, "取消原因": (取消令牌.原因 if 取消令牌 else "")},
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
        # 回收失败必须随失败说明一起回报（哲学第 3 条 2 项：失败要明确，不允许静默吞掉）
        清理说明 = ""
        if 进程 is not None:
            try:
                _终止进程组(进程, 强制=True)
            except Exception as 清理错误:
                清理说明 = f"（强制回收失败：{清理错误}）"
        return 结果.失败("执行失败", f"{错误}{清理说明}", 来源="进程管理")


# 批量执行的规模与并发上界（有界是铁律：不许一次调用拉起无界进程）。
执行命令集上限条数 = 64
执行命令集并发上限 = 8
执行命令集模式表 = ("串联", "并行")


def 执行命令集(命令表: list = None, 模式: str = None, 超时秒: float = None,
               工作目录: str = None, 失败即停: bool = None) -> 结果:
    """一次执行多条命令（串联=按序，并行=同时跑），逐条回带退出码与输出。

    为什么有这个能力（华哥 2026-09-21 裁决「mcp 调用……你加上这个底层不就行了？
    一次性多个命令」）：开发期一组检查本是几条独立命令，逐条各走一次 MCP 往返，
    每趟都重付协议与排队成本；而 `执行命令` 按「可执行文件 + 参数」直启（**不经 shell**），
    调用方想把它们串起来只能自己拼 shell，容易踩坑。本能力把「一组命令」收敛成
    **一次调用**，调用方一趟拿全所有退出码与输出。

    逐条复用 `执行命令`（哲学 1.1 结果唯一）：危险命令前置拦截、argv 拆分、输出有界、
    进程组整组回收全部沿用同一实现，本能力**一条都不复制**。

    `失败即停`（默认 真）**只在串联模式生效** —— 并行已同时起跑、停不下来，故忽略；
    被跳过的条目仍出现在 `结果表` 里并带 `已跳过=真`，便于与入参 `命令表` 按下标对齐。
    """
    模式值 = "串联" if 模式 is None else str(模式)
    if 模式值 not in 执行命令集模式表:
        return 结果.失败("参数不合法", f"模式必须是 {' 或 '.join(执行命令集模式表)}", 来源="进程管理")
    if not isinstance(命令表, list) or not 命令表:
        return 结果.失败("参数不合法", "命令表必须是非空列表", 来源="进程管理")
    if len(命令表) > 执行命令集上限条数:
        return 结果.失败("参数不合法",
                       f"命令表最多 {执行命令集上限条数} 条（当前 {len(命令表)} 条）；要跑更多请分批",
                       来源="进程管理")
    逐条命令: list[str] = []
    for 序号, 命令 in enumerate(命令表, start=1):
        if not isinstance(命令, str) or not 命令.strip():
            return 结果.失败("参数不合法", f"命令表第 {序号} 项必须是非空文本", 来源="进程管理")
        逐条命令.append(命令)
    停止即失败 = True if 失败即停 is None else bool(失败即停)
    起点 = time.monotonic()
    结果表: list[dict] = []

    def _跑一条(下标: int) -> dict:
        单条开始 = time.monotonic()
        单结果 = 执行命令(命令=逐条命令[下标], 超时秒=超时秒, 工作目录=工作目录)
        条目 = {
            "序号": 下标 + 1,
            "命令": 逐条命令[下标],
            "耗时毫秒": round((time.monotonic() - 单条开始) * 1000, 1),
        }
        if 单结果.成功 and isinstance(单结果.值, dict):
            条目.update(单结果.值)
            # **本能力的 `成功` = 退出码为 0**（命令真的成功），不是 `执行命令` 的
            # 「跑起来了就算成功」。实测踩过：`false` 退出码 1 却被 `执行命令` 判成功，
            # 若照抄那个语义，`失败即停` 永不触发、`成功数` 全是假的（2026-09-21 现场）。
            条目["成功"] = 条目.get("退出码") == 0
        else:
            # 压根没跑起来（超时/危险命令/执行失败/超出限制）：无退出码可谈。
            条目["成功"] = False
            条目["错误码"] = 单结果.错误码
            条目["错误说明"] = 单结果.错误说明
        return 条目

    if 模式值 == "串联":
        for 下标 in range(len(逐条命令)):
            条目 = _跑一条(下标)
            结果表.append(条目)
            if not 条目["成功"] and 停止即失败:
                结果表.extend(
                    {"序号": 剩余 + 1, "命令": 逐条命令[剩余], "已跳过": True}
                    for 剩余 in range(下标 + 1, len(逐条命令))
                )
                break
    else:
        from concurrent.futures import ThreadPoolExecutor

        并发度 = max(1, min(len(逐条命令), 执行命令集并发上限))
        with ThreadPoolExecutor(max_workers=并发度) as 池:
            结果表 = list(池.map(_跑一条, range(len(逐条命令))))

    已完成 = [条目 for 条目 in 结果表 if not 条目.get("已跳过")]
    成功数 = sum(1 for 条目 in 已完成 if 条目.get("成功"))
    return 结果.成功结果({
        "模式": 模式值,
        "结果表": 结果表,
        "总数": len(逐条命令),
        "已执行数": len(已完成),
        "成功数": 成功数,
        "失败数": len(已完成) - 成功数,
        "已跳过数": len(结果表) - len(已完成),
        "全部成功": 成功数 == len(逐条命令),
        "总耗时毫秒": round((time.monotonic() - 起点) * 1000, 1),
    })


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
            # 进程组归属由 平台适配.子进程组启动标志() 保证，再锁外终止，
            # 避免在锁内执行阻塞式等待拖住所有句柄操作。
            进程对象 = 进程.get("进程对象")
            输出通道 = 进程.get("输出通道")
        else:
            进程对象 = None
            输出通道 = None
        句柄系统.失效(句柄, "释放")
    if 进程对象 is not None:
        try:
            _终止进程组(进程对象, 强制=True)
        except Exception as 错误:
            降级记录表.append(str(错误))
        finally:
            # 先让启动期建立的排空通道收口，再关管道：反过来会让排空线程读到
            # 已关闭的管道（ValueError），已读到的字节还可能丢在通道缓冲里。
            if 输出通道 is not None:
                输出通道.收口(2.0)
            for 管道 in (进程对象.stdout, 进程对象.stderr, 进程对象.stdin):
                if 管道 is not None:
                    管道.close()
    return 结果.成功结果({"句柄": 句柄, "状态": "已释放", "已释放": True})

# ── macOS sandbox-exec 内核沙箱执行（迁移自 V3 终端工具 沙箱处理器） ────────

默认沙箱输出上限字节 = 1 * 1024 * 1024

# SBPL profile 结构安全（S-01 / S-12）：
# 1) 结构化拼装：插进 profile 的路径一律先经 _sbpl字面量 变成「已转义的字面量」，
#    再与固定子句用 join 拼行 —— 任何原始路径字符串都不进 profile 文本；
# 2) 入口拒绝：工作目录含引号/反斜杠/换行/右括号即 fail-closed 失败，
#    不让 sandbox-exec 退出 65 之后再由调用方猜（历史实现该场景仍报「成功」）。
沙箱路径非法字符 = ('"', "\\", "\n", "\r", ")")

# SBPL profile 编译预检用的固定探针命令（沙箱内必然放行：/usr 只读 + process-exec）。
沙箱配置预检命令 = "/usr/bin/true"

# 危险命令前置检测（S-06）：经唯一能力调用服务取 命令安全.检测危险命令。
命令安全检测能力id = "系统核心支持库.命令安全.检测危险命令"
危险命令检测问题: list[str] = []  # 检测不可用/异常留痕（哲学第 3 条 2 项：不许静默吞掉）


def _命中非法沙箱字符(路径文本: str) -> str | None:
    """返回路径中第一个 SBPL 非法字符；全部合法返回 None。"""
    for 字符 in 沙箱路径非法字符:
        if 字符 in 路径文本:
            return 字符
    return None


def _sbpl字面量(路径) -> str:
    """把路径拼成 SBPL 字符串字面量（profile 内唯一转义点）。"""
    文本 = os.fspath(路径)
    return '"' + (文本.replace("\\", "\\\\").replace('"', '\\"')
                  .replace("\n", "\\n").replace("\r", "\\r")) + '"'


def _构建沙箱配置(工作目录) -> str:
    """返回 sandbox-exec profile：系统只读 + 仅工作目录可读写。

    结构化拼装：路径只经 `_sbpl字面量` 变成字面量，再与固定子句逐行 join；
    函数体内不再出现「把原始路径插值进 profile 文本」的写法（历史实现用
    f-string 直拼整个 SBPL，构成注入面）。
    参数只接受 `pathlib.Path`（唯一调用点传的是已 resolve 的工作区）；为避免
    异常穿透能力边界，这里对非 Path 输入同样按路径文本处理并一律转义。

    只读放开的位置限定为系统工具/动态库目录与 Python 解释器自身 prefix，
    不放开整个 /Users，避免越出工作区读用户其他文件。
    """
    import sys as _sys
    只读子路径 = (
        "/usr", "/bin", "/sbin", "/System", "/Library", "/opt/homebrew",
        "/private/var/db/dyld", "/private/var/folders", "/private/var/select",
        "/dev", "/private/etc/ssl",
        os.path.realpath(_sys.prefix), os.path.realpath(_sys.base_prefix),
    )
    只读文件 = ("/private/etc/hosts", "/private/etc/resolv.conf")
    行列表 = [
        "(version 1)",
        '(import "system.sb")',
        "(allow process-fork)",
        "(allow process-exec)",
        "(allow network*)",
        "(allow mach-lookup)",
        "(allow sysctl-read)",
        "(allow file-read-metadata)",
        "(allow file-read*",
        "  " + " ".join("(subpath " + _sbpl字面量(路径) + ")" for 路径 in 只读子路径),
        "  " + " ".join("(literal " + _sbpl字面量(路径) + ")" for 路径 in 只读文件),
        ")",
        "(allow file-read* file-write* (subpath " + _sbpl字面量(工作目录) + "))",
        "",
    ]
    return "\n".join(行列表)


def _预检沙箱配置(配置: str, 超时秒: float = 10.0) -> 结果:
    """profile 编译预检（fail-closed）：编译不过就绝不带着坏 profile 去跑用户命令。

    sandbox-exec 在 profile 编译失败时**一条命令都不执行**并以 65 退出；历史实现
    把这种「根本没跑」的结果当成 `结果.成功=True` 回报给调用方（S-12 伪绿）。
    这里在发起真实命令之前先用固定探针命令编译一次 profile：编译失败 → 直接
    返回失败（错误码 `执行失败`，沙箱执行命令契约已声明）；编译通过 → 才允许
    跑真实命令。命令自身的非零退出码仍由 `值.成功执行` 如实表达，不被误判。
    """
    try:
        预检 = subprocess.run(
            ["sandbox-exec", "-p", 配置, 沙箱配置预检命令],
            capture_output=True, timeout=超时秒)
    except (OSError, subprocess.SubprocessError) as 错误:
        return 结果.失败("沙箱不可用", f"沙箱 profile 预检无法执行: {错误}", 来源="进程管理")
    if 预检.returncode != 0:
        详情 = (预检.stderr or b"").decode("utf-8", "replace").strip()
        return 结果.失败(
            "执行失败",
            f"沙箱 profile 编译失败（退出码 {预检.returncode}），已拒绝执行: {详情[:500]}",
            来源="进程管理",
        )
    return 结果.成功结果({"配置字节数": len(配置.encode("utf-8"))})


def _前置危险命令检测(命令: str) -> 结果 | None:
    """经唯一能力调用服务取 `命令安全.检测危险命令`，做执行前策略判定（S-06）。

    - 命中危险命令 → 返回失败结果（错误码 `危险命令`），调用方必须直接拒绝执行；
    - 未命中 → 返回 None；
    - 检测器不可用（调用器未装配 / 能力缺失 / 调用异常）→ 返回 None 并留痕。

    降级口径：危险命令检测是纵向加固层，内核沙箱与进程组回收才是边界；未经
    加载器装配的直连场景（单测、脚本、工具链）取不到调用器，此时若 fail-closed
    会把既有的正常调用全面打断。因此「检测器不可用」按留痕降级处理，
    「检测器明确报危险」一律 fail-closed。
    """
    try:
        from 公共契约.能力契约.调用器 import 获取能力调用器
        检测结果 = 获取能力调用器().调用能力(命令安全检测能力id, {"命令": 命令}, 调用方="进程管理")
    except Exception as 错误:  # noqa: BLE001 —— 装配状态异常/装配失败均需留痕降级
        危险命令检测问题.append(f"{命令安全检测能力id} 不可用: {type(错误).__name__}: {错误}")
        return None
    if not getattr(检测结果, "成功", False):
        危险命令检测问题.append(
            f"{命令安全检测能力id} 返回失败: "
            f"{getattr(检测结果, '错误码', '')} {getattr(检测结果, '错误说明', '')}")
        return None
    值 = getattr(检测结果, "值", None)
    if isinstance(值, dict) and 值.get("危险"):
        return 结果.失败(
            "危险命令",
            str(值.get("原因") or "命中危险命令规则"),
            来源="进程管理",
            详情={"检测能力id": 命令安全检测能力id},
        )
    return None


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


def _沙箱输出目录() -> Path:
    """沙箱输出临时文件目录：本仓固定运行缓存目录（铁律「测试产物和快照只放工程缓存」）。

    不落系统 /tmp：进程被 SIGKILL 时 finally 不执行，落在系统 /tmp 的残片无人回收、
    多次运行无界累积（报告 BUG-12）。
    """
    目录 = 解析运行缓存根(系统根).joinpath(*沙箱输出目录名)
    目录.mkdir(parents=True, exist_ok=True)
    return 目录


def _修改时刻(路径: Path) -> float:
    """文件 mtime；取不到（已被删/无权限）按 0 处理，让清理逻辑照常推进。"""
    try:
        return 路径.stat().st_mtime
    except OSError:
        return 0.0


def _清理残留沙箱输出(目录: Path, 现在: float | None = None) -> int:
    """清理沙箱输出的历史残留文件，返回清理条数。

    双限：只删「年龄超过 沙箱输出保留秒」的文件；条数超 沙箱输出保留条数 时只删
    最旧的。**正在进行中的调用不可能被删** —— 它的文件刚创建，mtime 最新，永远排在
    保留窗口最前。
    """
    时刻 = time.time() if 现在 is None else float(现在)
    文件列表: list[Path] = []
    for 模式 in 沙箱输出文件模式:
        文件列表.extend(路径 for 路径 in 目录.glob(模式) if 路径.is_file())
    文件列表.sort(key=_修改时刻, reverse=True)
    清理数 = 0
    for 序号, 路径 in enumerate(文件列表):
        try:
            if 序号 >= 沙箱输出保留条数 or (时刻 - _修改时刻(路径)) > 沙箱输出保留秒:
                路径.unlink(missing_ok=True)
                清理数 += 1
        except OSError as 删除错误:
            临时文件问题.append(f"{路径} 残留清理失败: {删除错误}")
    return 清理数


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
    - 工作目录含 `"`/`\\`/换行/`)` 直接 `参数不合法`（这些字符会改写 SBPL 结构）；
    - profile 先做编译预检，编译不过 → `执行失败`（绝不把「没跑」报成成功）；
    - 执行前经能力调用服务取 `命令安全.检测危险命令`，命中 → `危险命令`；
    - 输出上限内截断；超时由收口层回收整棵进程树；
    - 环境变量走白名单，可用 环境变量 追加白名单内的键。
    """
    from pathlib import Path as _Path

    if not isinstance(命令, str) or not 命令.strip():
        return 结果.失败("参数不合法", "命令必须是非空字符串", 来源="进程管理")
    if not isinstance(工作目录, str) or not 工作目录.strip():
        return 结果.失败("参数不合法", "工作目录必填（沙箱唯一可读写目录）", 来源="进程管理")
    工作区 = _Path(工作目录).resolve()
    非法字符 = _命中非法沙箱字符(str(工作区))
    if 非法字符 is not None:
        return 结果.失败(
            "参数不合法",
            f"工作目录含非法字符 {非法字符!r}：沙箱 profile 只接受不含双引号、反斜杠、"
            "换行、右括号的路径",
            来源="进程管理",
            详情={"非法字符": 非法字符},
        )
    if not 工作区.is_dir():
        return 结果.失败("目录不存在", f"工作目录不存在: {工作区}", 来源="进程管理")
    上限字节 = int(输出上限字节) if isinstance(输出上限字节, int) and 输出上限字节 > 0 \
        else 默认沙箱输出上限字节
    超时, 超时原因 = _解析超时秒(超时秒, 60.0, "按本能力的默认 60 秒")
    if 超时原因 or 超时 is None:
        return 结果.失败("参数不合法", 超时原因 or "超时秒不合法", 来源="进程管理")

    import shutil as _shutil
    if not (平台适配.是macOS() and _shutil.which("sandbox-exec")):
        return 结果.失败(
            "沙箱不可用",
            "当前平台无 sandbox-exec 内核沙箱，沙箱执行已禁用（fail-closed，不降级）",
            来源="进程管理",
        )

    危险命中 = _前置危险命令检测(命令)
    if 危险命中 is not None:
        return 危险命中

    环境 = _沙箱安全环境(str(工作区))
    for 键, 值 in (环境变量 or {}).items():
        if 键 in 环境:
            环境[键] = str(值)
    配置 = _构建沙箱配置(工作区)
    预检结果 = _预检沙箱配置(配置)
    if not 预检结果.成功:
        return 预检结果
    argv = ["sandbox-exec", "-p", 配置, "/bin/sh", "-c", 命令]

    import uuid as _uuid
    输出目录 = _沙箱输出目录()
    _清理残留沙箱输出(输出目录)
    令牌 = _uuid.uuid4().hex
    输出文件 = 输出目录 / f".沙箱输出_{令牌}.txt"
    错误文件 = 输出目录 / f".沙箱错误_{令牌}.txt"
    进程 = None
    开始时刻 = time.monotonic()
    try:
        with 输出文件.open("wb") as 出, 错误文件.open("wb") as 错:
            进程 = subprocess.Popen(
                argv, cwd=str(工作区), stdout=出, stderr=错,
                env=环境, **平台适配.子进程组启动标志())
            超时标志 = False
            try:
                进程.wait(timeout=超时)
            except subprocess.TimeoutExpired:
                超时标志 = True
                _终止进程组(进程, 强制=True)
        标准输出 = _读受限(输出文件, 上限字节)
        错误输出 = _读受限(错误文件, 上限字节)
        # 执行耗时账本（同 执行命令 那一处）：本能力**自己起进程**（不经 执行命令），
        # 故必须单独记一笔，否则沙箱这条腿的执行在账本里是空白。
        执行耗时账本.记一笔(
            来源="系统核心支持库.进程管理.沙箱执行命令", 命令=命令,
            耗时秒=time.monotonic() - 开始时刻,
            退出码=getattr(进程, "returncode", None),
            工作目录=str(工作目录 or ""),
            输出字节=len(标准输出 or "") + len(错误输出 or ""))
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
        # 强制回收失败必须随失败说明回报（哲学第 3 条 2 项：失败要明确，不许静默吞掉）
        清理说明 = ""
        if 进程 is not None:
            try:
                _终止进程组(进程, 强制=True)
            except Exception as 清理错误:
                清理说明 = f"（强制回收失败：{清理错误}）"
        return 结果.失败("执行失败", f"{错误}{清理说明}", 来源="进程管理")
    finally:
        for 文件 in (输出文件, 错误文件):
            try:
                文件.unlink(missing_ok=True)
            except OSError as 删除错误:
                临时文件问题.append(f"{文件} 删除失败: {删除错误}")


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
