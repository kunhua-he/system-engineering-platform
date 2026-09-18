"""进程级优雅停机编排（外部二次审计 B4）：四段停机状态机，收尾链复用 P0-1 世代账本回收。

**为什么需要本文件（现场取证，不是推测）**：
- `本地网关.有界线程HTTP服务器.daemon_threads = True`：进程退出时工作线程被直接带走，
  **在途请求/任务被腰斩**，客户端只见连接断开，分不清「限流 / 故障 / 停机」；
- 全仓 `signal.signal` 处理器 **0 处**：`launchd kickstart -k`、`kill` 走默认动作（立即终止），
  装配在飞、任务在跑、常驻提供者整组还活着时进程就没了，下一代只能靠世代账本兜；
- `容量基线.py` 的「停止接收→排空→优雅释放」是**熔断路径**（单次请求过载保护），
  与进程级停机不是同一件事，不能共用一条腿（同一现象两种语义）。

**四段（与审计要求逐段对应，顺序即语义）**：
1. **停止收新请求**：关 listen socket，内核直接拒绝新连接（不再产生新工作线程）；
2. **有界排空在途**：等在途请求自然收尾，到上限仍未收尾的**逐条如实记录**（不静默丢）；
   流式通道先取消、再给一个复查窗口，避免 SSE 长连接把排空拖成无界；
3. **整组回收常驻进程**：**复用 P0-1 收尾链** —— 注入的收尾项（如
   `提供者生命周期管理器.清理全部` → `独立进程.关闭`：优雅请求 → 组 TERM → 组 KILL →
   资源核对 → 销账）与任务系统整组回收依次执行；再调 A 簇公开兜底
   `独立进程.清扫上一代常驻进程()` 回收**上一代**孤儿整组。本世代仍留在账本上的行
   **不动、如实上报** —— A 簇判据是「归属网关进程已消失才算孤儿」，本进程还在运行就动它
   等于破坏该判据；它们由**下一世代同一个 reaper** 收盘，所以这是同一条收尾链，
   不是第二条腿。
4. **持久化任务 + 退出**：任务账本落库（非终态任务在新一代 `任务系统.加载` 里收敛为
   「崩溃」，与既有跨重启语义**同一口径**，不另造收敛逻辑），清网关凭证，输出停机报告。

**明确不做的事**：
- 不新写资源回收：回收能力全在各所有者与 A 簇手里，本文件只按序调用、如实记录；
- 不用 `os._exit`：那会跳过 atexit 里已登记的收尾（如权威状态维护线程停止）。
  退出码默认 **0** —— launchd `KeepAlive{SuccessfulExit:false}` 见非零码会立刻重启，
  「优雅停机」不该表现成「崩了要重启」；未收敛明细一律进停机报告与日志，不靠退出码表达。
"""

from __future__ import annotations

import math
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假

# 停机状态机的唯一状态表（顺序即四段推进顺序；「运行中」「已停机」为两端）
停机阶段_运行中 = "运行中"
停机阶段_停止收新请求 = "停止收新请求"
停机阶段_排空在途 = "排空在途"
停机阶段_整组回收 = "整组回收"
停机阶段_持久化 = "持久化"
停机阶段_已停机 = "已停机"

#: 四段（审计要求的四段，顺序不可换：先拒新、再排空、再回收、最后持久化）
四段阶段表 = (停机阶段_停止收新请求, 停机阶段_排空在途,
            停机阶段_整组回收, 停机阶段_持久化)

#: 有界排空上限（秒）。上限存在的理由：Python 无法强杀线程，无界等 = 停机卡死；
#: 超时的代价必须**可见**（逐条记入报告），而不是假装排空成功。
默认排空上限秒 = 20.0
#: 排空超时后取消流式通道、再复查一轮的窗口（SSE 是长连接，只靠等永远等不到）
默认排空复查窗口秒 = 2.0
#: 停机日志环形上限（与网关日志同口径的有界）
默认日志上限 = 200
#: 收尾链每项预算（用于推导 launchd ExitTimeOut 建议值，不用于打断收尾）
默认收尾项预算秒 = 10.0


def launchd退出超时建议(排空上限秒: float | None = None,
                        收尾项数: int = 3) -> int:
    """推导 launchd `ExitTimeOut` 建议值（秒）：排空上限 + 收尾预算 + 余量。

    为什么要有这个值：launchd 发 SIGTERM 后到 SIGKILL 之间只等 `ExitTimeOut`
    （缺省 20 秒）。本机 40007 的 plist **没有** ExitTimeOut（全仓 grep 0 处，
    实测 2026-09-18），而本平台排空上限缺省就是 20 秒 —— 上一批的批量转码/转写
    在途时，SIGTERM 后 20 秒到点就被 SIGKILL，四段永远走不完，等于优雅停机对
    长请求失效。故本函数把「plist 该写多少」变成机器可算的一个数。
    """
    排空 = 默认排空上限秒 if 排空上限秒 is None else max(0.0, float(排空上限秒))
    收尾预算 = max(1, int(收尾项数)) * 默认收尾项预算秒
    return int(math.ceil(排空 + 收尾预算 + 默认排空复查窗口秒 + 8.0))


def 退出超时改造建议(排空上限秒: float | None = None,
                    收尾项数: int = 3,
                    plist路径: str = "~/Library/LaunchAgents/com.huashi.gateway-40007.plist") -> dict[str, Any]:
    """给出 ExitTimeOut 的**落地改法与命令**（本模块不改 plist：属主会话的部署面）。

    返回 `{建议秒, 理由, 存在ExitTimeOut, 命令}`；`命令` 为可直接粘贴的 plutil 两行。
    """
    建议秒 = launchd退出超时建议(排空上限秒, 收尾项数)
    命令 = [
        f"plutil -replace ExitTimeOut -integer {建议秒} {plist路径}",
        f"launchctl kickstart -k gui/$(id -u)/com.huashi.gateway-40007  # 重载生效",
    ]
    return {
        "建议秒": 建议秒,
        "存在ExitTimeOut": 假 if not 已配置退出超时(plist路径) else 真,
        "理由": ("排空上限 + 收尾预算 + 复查窗口 + 余量；缺省 ExitTimeOut 只有 20 秒，"
               "与排空上限同量级，长请求在途时必然被 SIGKILL 腰斩"),
        "命令": 命令,
    }


def 已配置退出超时(plist路径: str = "~/Library/LaunchAgents/com.huashi.gateway-40007.plist") -> bool:
    """plist 是否已声明 ExitTimeOut（只读探测；文件不可读按「未声明」处理）。"""
    try:
        路径 = os.path.expanduser(plist路径)
        with open(路径, "rb") as 文件:
            内容 = 文件.read().decode("utf-8", "replace")
    except OSError:
        return 假
    return "<key>ExitTimeOut</key>" in 内容


class 停机编排:
    """四段停机状态机：按序推进，幂等，重复信号即降级为「立即收尾」。

    依赖全部**注入**（停收函数/排空函数/收尾链/持久化链），本类不认识网关、任务系统或
    提供者管理器 —— 谁持有资源谁提供收尾项，本类只负责**顺序、超时、幂等与如实上报**。
    """

    def __init__(self, *, 名称: str = "网关",
                 排空上限秒: float = 默认排空上限秒,
                 排空复查窗口秒: float = 默认排空复查窗口秒,
                 停收函数: Callable[[], tuple[bool, str]] | None = None,
                 排空函数: Callable[[float], tuple[bool, str]] | None = None,
                 在途快照函数: Callable[[], list[dict[str, Any]]] | None = None,
                 取消在途流函数: Callable[[], Any] | None = None,
                 收尾链: list[tuple[str, Callable[[], Any]]] | None = None,
                 持久化链: list[tuple[str, Callable[[], Any]]] | None = None,
                 非终态任务函数: Callable[[], int] | None = None,
                 兜底回收函数: Callable[[], Any] | None = None,
                 本世代残留函数: Callable[[], list[dict[str, Any]]] | None = None,
                 日志上限: int = 默认日志上限,
                 失败退出码: int = 0) -> None:
        self.名称 = str(名称)
        self.排空上限秒 = max(0.0, float(排空上限秒))
        self.排空复查窗口秒 = max(0.0, float(排空复查窗口秒))
        self.失败退出码 = int(失败退出码)
        self._停收函数 = 停收函数
        self._排空函数 = 排空函数
        self._在途快照函数 = 在途快照函数
        self._取消在途流函数 = 取消在途流函数
        self._收尾链: list[tuple[str, Callable[[], Any]]] = list(收尾链 or [])
        self._持久化链: list[tuple[str, Callable[[], Any]]] = list(持久化链 or [])
        self._非终态任务函数 = 非终态任务函数
        self._兜底回收函数 = 兜底回收函数
        self._本世代残留函数 = 本世代残留函数
        self._日志上限 = max(1, int(日志上限))
        self._锁 = threading.RLock()
        self.状态 = 停机阶段_运行中
        self.已请求 = 假
        self.信号记录: list[str] = []
        self.日志列表: list[str] = []
        self.阶段记录: list[dict[str, Any]] = []
        self._强制退出 = threading.Event()
        self._报告: dict[str, Any] | None = None
        self._信号安装结果 = ""

    # ---------- 配置与观测 ----------

    def 注册收尾项(self, 名称: str, 函数: Callable[[], Any]) -> None:
        """登记一个「整组回收」收尾项（顺序即执行顺序）。重复登记同名项覆盖为最新函数。"""
        with self._锁:
            self._收尾链 = [(项名, 项函数) for 项名, 项函数 in self._收尾链 if 项名 != 名称]
            self._收尾链.append((str(名称), 函数))

    def 注册持久化项(self, 名称: str, 函数: Callable[[], Any]) -> None:
        """登记一个「持久化」项（顺序即执行顺序）。"""
        with self._锁:
            self._持久化链 = [(项名, 项函数) for 项名, 项函数 in self._持久化链 if 项名 != 名称]
            self._持久化链.append((str(名称), 函数))

    def 记日志(self, 消息: str) -> None:
        """环形有界日志（可见，不静默）；同时打到 stdout 供 launchd 标准输出留存。"""
        with self._锁:
            self.日志列表.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {消息}")
            if len(self.日志列表) > self._日志上限:
                del self.日志列表[:len(self.日志列表) - self._日志上限]
        print(f"[停机编排:{self.名称}] {消息}", flush=True)

    def 状态快照(self) -> dict[str, Any]:
        """当前状态快照（测试/运维观测用；不含任何资源对象）。"""
        with self._锁:
            return {
                "名称": self.名称, "状态": self.状态, "已请求停机": self.已请求,
                "已停机": self.状态 == 停机阶段_已停机,
                "强制退出": self._强制退出.is_set(),
                "排空上限秒": self.排空上限秒,
                "收尾项": [项名 for 项名, _ in self._收尾链],
                "持久化项": [项名 for 项名, _ in self._持久化链],
                "信号记录": list(self.信号记录),
                "日志": list(self.日志列表),
                "信号安装": self._信号安装结果,
                "launchd退出超时建议秒": launchd退出超时建议(self.排空上限秒, len(self._收尾链) or 1),
            }

    def 停机报告(self) -> dict[str, Any] | None:
        """最后一次停机报告（未停机过则为 None）。"""
        with self._锁:
            return None if self._报告 is None else dict(self._报告)

    # ---------- 请求与执行 ----------

    def 请求停机(self, 信号名: str = "") -> dict[str, Any]:
        """请求停机（幂等）；**第二次信号即降级**：跳过剩余排空，直接收尾。

        为什么第二次要降级而不是忽略：运维/launchd 连发两次信号表达的是「别等了」，
        忽略它等于把「卡住」换成「不响应」；降级后依然要把四段走完（只是排空上限归零），
        所以不丢收尾链，也不丢截断记录。
        """
        with self._锁:
            if 信号名:
                self.信号记录.append(str(信号名))
            if self.状态 == 停机阶段_已停机:
                self.记日志(f"收到停机请求（{信号名 or '内部'}）：已停机，幂等返回")
                return {"已请求": 假, "重复": 真, "状态": self.状态}
            if self.已请求:
                self._强制退出.set()
                self.记日志(f"第二次停机请求（{信号名 or '内部'}）：跳过剩余排空，立即收尾")
                return {"已请求": 真, "重复": 真, "降级": 真, "状态": self.状态}
            self.已请求 = 真
        self.记日志(f"收到停机请求（{信号名 or '内部'}）：进入四段停机，排空上限 {self.排空上限秒:.1f} 秒")
        return {"已请求": 真, "重复": 假, "状态": self.状态}

    def 执行(self) -> dict[str, Any]:
        """执行四段停机（幂等：已停机时直接返回既有报告）。返回停机报告。"""
        with self._锁:
            if self.状态 == 停机阶段_已停机:
                self.记日志("执行停机：已停机，幂等返回既有报告")
                return dict(self._报告 or {})
            if not self.已请求:
                self.已请求 = 真
                self.记日志(f"未经请求直接执行停机（{self.名称}）：按四段推进")
        self.记日志("进入四段停机编排")
        try:
            self._推进段(停机阶段_停止收新请求, self._段_停止收新请求)
            self._推进段(停机阶段_排空在途, self._段_排空在途)
            self._推进段(停机阶段_整组回收, self._段_整组回收)
            self._推进段(停机阶段_持久化, self._段_持久化)
        finally:
            with self._锁:
                self.状态 = 停机阶段_已停机
        报告 = self._组装报告()
        with self._锁:
            self._报告 = 报告
        self.记日志(f"四段停机完成：{'全部收敛' if 报告['成功'] else '存在未收敛项'}；"
                    f"截断在途 {报告['排空']['截断数']} 条；耗时 {报告['耗时毫秒']:.0f} 毫秒")
        return dict(报告)

    def 处理信号(self, 信号名: str, *, 退出: bool = 真) -> None:
        """信号处理器体：请求停机 → 执行四段 → 按退出码抛 `SystemExit`。

        之所以在主线程内联执行（而不是丢给后台线程）：四段里的
        `服务器.shutdown()` 依赖 serve_forever 另一线程、排空依赖主线程等待，
        后台线程执行完还得靠 `os._exit` 才能让进程真正退出，而 `os._exit` 会跳过
        atexit 已登记的收尾（权威状态维护线程停止）。在主线程内联 + `SystemExit`
        可以让解释器正常收尾，这是「四段走完才退出」的唯一可靠姿势。
        生产主线程在 `time.sleep(3600)` 的空转里，信号处理期间没有持锁业务代码。
        """
        结果 = self.请求停机(信号名)
        if 结果.get("重复") and 结果.get("降级"):
            pass  # 正在执行的编排会读到强制退出标记
        else:
            self.执行()
        if 退出:
            报告 = self.停机报告() or {}
            raise SystemExit(self._退出码(报告))

    def _退出码(self, 报告: dict[str, Any]) -> int:
        """退出码：默认 0（launchd `SuccessfulExit:false` 见非零会立刻重启）。"""
        return 0 if 报告.get("成功") else self.失败退出码

    # ---------- 四段实现 ----------

    def _推进段(self, 阶段: str, 段函数: Callable[[], dict[str, Any]]) -> None:
        with self._锁:
            self.状态 = 阶段
        起点 = time.monotonic()
        try:
            明细 = 段函数()
        except Exception as 错误:  # noqa: BLE001 —— 段异常必须进报告，不得静默吞
            明细 = {"成功": 假, "错误说明": f"{阶段}段异常 {type(错误).__name__}: {错误}"}
        明细 = dict(明细 or {})
        明细.setdefault("成功", 假)
        明细["阶段"] = 阶段
        明细["耗时毫秒"] = (time.monotonic() - 起点) * 1000.0
        with self._锁:
            self.阶段记录.append(明细)
        self.记日志(f"段[{阶段}] {'完成' if 明细['成功'] else '未收敛'}："
                    f"{明细.get('说明') or 明细.get('错误说明') or ''}"
                    f"（{明细['耗时毫秒']:.0f} 毫秒）")

    def _段_停止收新请求(self) -> dict[str, Any]:
        """段 1：关闭 listen socket（内核拒绝新连接）。"""
        if self._停收函数 is None:
            return {"成功": 假, "错误说明": "未注入停收函数（无法停止收新请求）"}
        成功, 说明 = self._停收函数()
        return {"成功": bool(成功), "说明": str(说明)}

    def _段_排空在途(self) -> dict[str, Any]:
        """段 2：有界排空在途；超时逐条记录，不静默。"""
        if self._排空函数 is None:
            return {"成功": 假, "错误说明": "未注入排空函数（无法有界排空在途）"}
        上限 = 0.0 if self._强制退出.is_set() else self.排空上限秒
        if self._强制退出.is_set():
            self.记日志("强制退出已置位：排空上限归零（不无限等）")
        成功, 说明 = self._排空函数(上限)
        在途 = self._取在途快照()
        if 在途 and self._取消在途流函数 is not None and self.排空复查窗口秒 > 0:
            取消 = self._取消在途流函数()
            self.记日志(f"排空超时且仍有在途 {len(在途)} 条：已取消在途流式通道（{取消}），"
                        f"给 {self.排空复查窗口秒:.1f} 秒复查窗口"
                        if 在途 else "")
            self._排空函数(self.排空复查窗口秒)
            在途 = self._取在途快照()
        截断说明 = "；".join(
            f"{项.get('路径') or '未知路径'}"
            f"{'/请求id=' + str(项.get('请求id')) if 项.get('请求id') else ''}"
            f"（已运行 {float(项.get('已运行秒') or 0.0):.2f} 秒）"
            for 项 in 在途
        )
        if 在途:
            self.记日志(f"排空到上限仍有在途 {len(在途)} 条，**被截断**（逐条记录）：{截断说明}")
            return {
                "成功": 假,
                "说明": f"{说明}；在途 {len(在途)} 条已被截断（见截断清单）",
                "错误说明": f"排空超时，截断 {len(在途)} 条在途请求",
                "截断数": len(在途), "截断清单": 在途,
            }
        return {"成功": bool(成功), "说明": str(说明), "截断数": 0, "截断清单": []}

    def _取在途快照(self) -> list[dict[str, Any]]:
        if self._在途快照函数 is None:
            return []
        try:
            快照 = self._在途快照函数() or []
        except Exception as 错误:  # noqa: BLE001 —— 取不到快照必须可见
            self.记日志(f"在途快照失败：{type(错误).__name__}: {错误}")
            return []
        return [dict(项) for 项 in 快照]

    def _段_整组回收(self) -> dict[str, Any]:
        """段 3：跑收尾链（各所有者 + A 簇收尾链）+ A 簇公开兜底 + 本世代账本核对。"""
        项表: list[dict[str, Any]] = []
        for 项名, 项函数 in list(self._收尾链):
            项表.append(self._跑收尾项("收尾", 项名, 项函数))
        兜底 = self._跑A簇兜底回收()
        残留 = self._本世代残留行()
        if 残留:
            self.记日志(f"本世代账本仍留 {len(残留)} 行（归属本进程，未收敛不销账；"
                        f"由下一世代同一 reaper 收盘）")
        成功 = all(项["成功"] for 项 in 项表) and bool(兜底["成功"])
        return {
            "成功": 成功, "收尾项": 项表,
            "兜底回收": 兜底, "本世代残留": 残留,
            "说明": (f"收尾项 {len(项表)} 项（成功 {sum(1 for 项 in 项表 if 项['成功'])}）；"
                    f"上一代孤儿回收：{兜底['说明']}；本世代残留账本行 {len(残留)}"),
        }

    def _跑收尾项(self, 类别: str, 项名: str, 项函数: Callable[[], Any]) -> dict[str, Any]:
        """执行一个收尾项：异常/元组/信封三种返回形态都收敛成统一结论（可见，不静默）。"""
        起点 = time.monotonic()
        成功 = 假
        说明 = ""
        try:
            返回值 = 项函数()
            成功, 说明 = _解释收尾结果(返回值)
        except Exception as 错误:  # noqa: BLE001 —— 收尾失败必须进报告
            成功, 说明 = 假, f"收尾项异常 {type(错误).__name__}: {错误}"
        项 = {"类别": 类别, "名称": 项名, "成功": 成功, "说明": 说明,
              "耗时毫秒": (time.monotonic() - 起点) * 1000.0}
        self.记日志(f"{类别}项[{项名}] {'成功' if 成功 else '未收敛'}：{说明}")
        return 项

    def _跑A簇兜底回收(self) -> dict[str, Any]:
        """复用 A 簇公开入口：回收**上一代**（归属网关已消失）常驻进程整组。

        为什么兜底必须在这里：优雅停机切断的是「本进程自己持有的资源」；上一代网关
        被 kill -9 / 崩溃时留下的整组孤儿没有内存句柄，只有世代账本能定位 —— 这正是
        A 簇 `清扫上一代常驻进程()` 的职责。本段只**调用**它，不重写回收逻辑。
        """
        if self._兜底回收函数 is None:
            return {"成功": 真, "说明": "未注入兜底回收（本次停机不涉及上一代孤儿）",
                    "已回收": [], "未回收": [], "跳过": []}
        try:
            结论 = self._兜底回收函数() or {}
        except Exception as 错误:  # noqa: BLE001 —— 兜底失败必须可见
            return {"成功": 假, "说明": f"兜底回收异常 {type(错误).__name__}: {错误}",
                    "已回收": [], "未回收": [], "跳过": []}
        已回收 = list(结论.get("已回收") or [])
        未回收 = list(结论.get("未回收") or [])
        跳过 = list(结论.get("跳过") or [])
        成功 = bool(结论.get("成功")) and not 未回收
        return {
            "成功": 成功,
            "说明": (f"账本 {结论.get('账本行数', 0)} 行：已回收 {len(已回收)}，"
                    f"未回收 {len(未回收)}，跳过（归属仍存活）{len(跳过)}"
                    + (f"；{结论.get('错误说明')}" if 结论.get("错误说明") else "")),
            "已回收": 已回收, "未回收": 未回收, "跳过": 跳过,
        }

    def _本世代残留行(self) -> list[dict[str, Any]]:
        if self._本世代残留函数 is None:
            return []
        try:
            return [dict(行) for 行 in (self._本世代残留函数() or [])]
        except Exception as 错误:  # noqa: BLE001 —— 核对失败必须可见
            self.记日志(f"本世代账本核对失败：{type(错误).__name__}: {错误}")
            return []

    def _段_持久化(self) -> dict[str, Any]:
        """段 4：账本落库 + 非终态任务统计（收敛口径交下一代 `任务系统.加载`）。"""
        项表: list[dict[str, Any]] = []
        for 项名, 项函数 in list(self._持久化链):
            项表.append(self._跑收尾项("持久化", 项名, 项函数))
        非终态 = 0
        if self._非终态任务函数 is not None:
            try:
                非终态 = int(self._非终态任务函数() or 0)
            except Exception as 错误:  # noqa: BLE001 —— 统计失败必须可见
                self.记日志(f"非终态任务统计失败：{type(错误).__name__}: {错误}")
        if 非终态:
            self.记日志(f"非终态任务 {非终态} 条：账本已落库，"
                        f"新一代启动时由 任务系统.加载 收敛为「崩溃」（既有跨重启语义）")
        成功 = all(项["成功"] for 项 in 项表)
        return {
            "成功": 成功, "持久化项": 项表, "非终态任务数": 非终态,
            "说明": (f"持久化项 {len(项表)} 项（成功 {sum(1 for 项 in 项表 if 项['成功'])}）；"
                    f"非终态任务 {非终态} 条（交下一代 加载() 收敛为崩溃）"),
        }

    def _组装报告(self) -> dict[str, Any]:
        with self._锁:
            阶段记录 = [dict(项) for 项 in self.阶段记录]
            强制 = self._强制退出.is_set()
        段表 = {项["阶段"]: 项 for 项 in 阶段记录}
        排空 = 段表.get(停机阶段_排空在途, {})
        回收 = 段表.get(停机阶段_整组回收, {})
        持久化 = 段表.get(停机阶段_持久化, {})
        成功 = (len(阶段记录) == len(四段阶段表)
                and all(bool(项.get("成功")) for 项 in 阶段记录))
        耗时毫秒 = sum(float(项.get("耗时毫秒") or 0.0) for 项 in 阶段记录)
        未收敛原因 = [f"{项['阶段']}: {项.get('错误说明') or 项.get('说明') or ''}"
                    for 项 in 阶段记录 if not 项.get("成功")]
        return {
            "名称": self.名称, "成功": 成功, "强制退出": 强制,
            "阶段序列": [项["阶段"] for 项 in 阶段记录],
            "四段完整": len(阶段记录) == len(四段阶段表),
            "阶段明细": 阶段记录,
            "排空": {
                "上限秒": self.排空上限秒,
                "截断数": int(排空.get("截断数") or 0),
                "截断清单": list(排空.get("截断清单") or []),
            },
            "整组回收": {
                "收尾项": list(回收.get("收尾项") or []),
                "兜底回收": 回收.get("兜底回收") or {},
                "本世代残留行数": len(回收.get("本世代残留") or []),
            },
            "持久化": {
                "非终态任务数": int(持久化.get("非终态任务数") or 0),
                "持久化项": list(持久化.get("持久化项") or []),
            },
            "未收敛原因": 未收敛原因,
            "耗时毫秒": 耗时毫秒,
            "信号记录": list(self.信号记录),
            "日志": list(self.日志列表),
        }


def _解释收尾结果(返回值: Any) -> tuple[bool, str]:
    """把收尾项的返回形态统一成 (成功, 说明)。

    支持的形态（既有代码里真实存在的三种，不另立第四种）：
    - `(bool, str)` 元组（如 `网关.优雅停止()`、`进程池.停止()`）；
    - 结果信封（有 `.成功` 属性，如 `后端核心.优雅关闭()`）；
    - `dict`（带 `成功` 键，如 `独立进程.关闭()` 的关闭结果信封）。
    `None` 视为**成功**（无返回值的收尾动作，如 `任务系统.保存()`）；其余按「已完成无结论」
    处理并如实说明，绝不因为「返回值不认识」就判失败或静默通过。
    """
    if 返回值 is None:
        return 真, "已完成（无返回值）"
    if isinstance(返回值, tuple) and len(返回值) == 2:
        return bool(返回值[0]), str(返回值[1])
    if isinstance(返回值, dict):
        成功 = bool(返回值.get("成功", 返回值.get("已成功", 假)))
        说明 = str(返回值.get("错误说明") or 返回值.get("说明") or 返回值.get("值") or "")
        if "未收敛" in 返回值 and 返回值.get("未收敛"):
            成功 = 假
            说明 = 说明 or f"未收敛: {返回值.get('未收敛')}"
        return 成功, 说明 or ("已收敛" if 成功 else "未给出说明的失败")
    成功属性 = getattr(返回值, "成功", None)
    if isinstance(成功属性, bool):
        说明 = str(getattr(返回值, "错误说明", "") or getattr(返回值, "值", "") or "")
        return bool(成功属性), 说明 or ("已完成" if 成功属性 else "未给出说明的失败")
    return 真, f"已完成（返回类型 {type(返回值).__name__}，按无结论处理）"


#: 进程级信号安装闸门：信号处理是**进程级**资源，同一进程内只允许一个停机编排持有它。
_信号归属: 停机编排 | None = None
_安装锁 = threading.Lock()


def 安装停机信号处理(编排: 停机编排, *, 信号表: tuple[int, ...] | None = None,
                    允许接管: bool = 假) -> tuple[bool, str]:
    """把 SIGTERM/SIGINT 接到停机编排（进程内一次性；返回 (是否安装, 说明)）。

    为什么进程内只装一次：信号表是全局的，两个网关实例在一个进程里同时装会互相顶替 ——
    后装者把前者的收尾链从信号路径上摘掉，而前者仍以为自己在被托管（假绿）。故首个安装者
    拥有信号，后续调用如实返回「已被 <现有> 持有」，除非显式 `允许接管=真`。
    非主线程调用一律拒绝（`signal.signal` 只能在主线程生效，静默失败等于没装）。
    """
    global _信号归属
    with _安装锁:
        if threading.current_thread() is not threading.main_thread():
            return 假, "信号安装必须在主线程（否则信号处理器不会生效）"
        现有 = _信号归属
        if 现有 is not None and 现有 is not 编排 and not 允许接管:
            return 假, f"进程内信号处理已归 {现有.名称}（如需接管请显式 允许接管=真）"
        信号列表 = 信号表 or (signal.SIGTERM, signal.SIGINT)
        已装: list[str] = []
        try:
            for 信号号 in 信号列表:
                signal.signal(信号号, _构造处理器(编排, 信号号))
                已装.append(signal.Signals(信号号).name)
        except (ValueError, OSError, AttributeError) as 错误:
            编排.记日志(f"信号安装失败（{type(错误).__name__}: {错误}）："
                         f"已装 {已装}，停机只能靠显式调用")
            编排._信号安装结果 = f"失败: {错误}"
            return 假, f"信号安装失败: {错误}"
        _信号归属 = 编排
        编排._信号安装结果 = "、".join(已装)
        编排.记日志(f"已接入进程信号：{'、'.join(已装)} → 四段停机编排"
                     f"（launchd ExitTimeOut 建议 "
                     f"{launchd退出超时建议(编排.排空上限秒, len(编排._收尾链) or 1)} 秒）")
        return 真, f"已安装 {('、'.join(已装))}"


def _构造处理器(编排: 停机编排, 信号号: int) -> Callable[[int, Any], None]:
    """构造信号处理器：只做「请求停机 → 内联执行四段 → SystemExit」三件事。"""
    名称 = signal.Signals(信号号).name

    def 处理器(收到的信号号: int, 帧: Any) -> None:
        编排.处理信号(名称 or f"信号{信号号}")

    return 处理器


def 信号安装状态() -> dict[str, Any]:
    """进程级信号归属快照（运维/测试观测用）。"""
    with _安装锁:
        return {
            "已安装": _信号归属 is not None,
            "归属": _信号归属.名称 if _信号归属 is not None else "",
            "安装结果": _信号归属._信号安装结果 if _信号归属 is not None else "",
        }


__all__ = [
    "停机阶段_运行中", "停机阶段_停止收新请求", "停机阶段_排空在途",
    "停机阶段_整组回收", "停机阶段_持久化", "停机阶段_已停机", "四段阶段表",
    "默认排空上限秒", "默认排空复查窗口秒", "默认日志上限",
    "launchd退出超时建议", "退出超时改造建议", "已配置退出超时",
    "停机编排", "安装停机信号处理", "信号安装状态",
]
