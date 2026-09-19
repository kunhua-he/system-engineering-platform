"""管道读取面：stdout 后台读线程、带超时行读取与滞留行排空（混入类）。

**为什么独立成文件**：这一簇是「stdout 只有一个读者（唯一所有权）」的实现所在 ——
裸文件描述符包装（`_描述符读取器`）、管道启动与消费（`_启动stderr消费` /
`_启动stdout消费` / `_收块` / `_消费stderr` / `_消费stdout`）、带超时行读取
（`_读取一行`）、滞留行排空（`弃置滞留行`）、管道关闭（`_关闭管道`）。

**唯一所有权语义**：管道 fd 归本面的后台读线程独有，上层（如
`运行核心/运行环境管理器/提供者生命周期.py`）**永不直接碰管道 fd** ——
要丢掉滞留响应行一律走 `弃置滞留行()`（只在同一把交接锁下从后台线程维护的
`_读取缓冲` 里非阻塞取/弃完整行）。旧实现让上层 `select + readline` 直读同一管道，
两个读者分食同一字节流。

**跨平台收口**：stdout 由后台线程阻塞式 `os.read` 直读内核，经
`公共契约.运行时.有界IO.受限读取` 排空+限界，调用方在条件变量上等一个完整行
—— **不用 `select` 轮询管道 fd**（Windows 的 `select` 只接受 socket，轮询管道必然报错，
旧实现把该异常吞成「启动超时」，导致提供者隔离进程在 Windows 永远起不来）。
本文件调用点不含任何平台判断（无 `os.name` / `sys.platform`）。

**对外零变化（2026-09-19 拆分）**：正文逐字取自冻结基线
`/tmp/拆分基线/独立进程.py`（1044 行，sha256 前16 = 963513edb4dd3228）；
`排空窗口秒` / `排空预算秒` / `排空预算字节` 与 `_描述符读取器` 的唯一定义处搬到这里
（**只在本模块定义一份**，主文件与 `独立进程_账本.py` 都经「导入即再导出」拿到同一对象，
不各写一遍字面量 —— 同一件事不留两套度量口径）。

**导入方向**：本文件只被 `独立进程.py` 模块级导入，**不得反向导入**它；
宿主属性（`_读取缓冲` / `_读取条件` / `_读取结束` / `_读取超限` / `_读取序号` /
`_通信锁` / `名称` / `日志列表` / `_stderr线程` / `_stdout线程`）写成类注解 = 契约，
宿主缺哪个属性当场 `AttributeError`，不静默退回各自拼路径。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any

from 公共契约.运行时 import 有界IO
from 公共契约.基础类型.逻辑类型 import 真, 假
from 运行核心.加载器.提供者隔离.独立进程_对象 import 响应行上限字节, 读取块大小


class _描述符读取器:
    """把裸文件描述符包成 ``有界IO.受限读取`` 需要的 ``read(大小)`` 接口。

    用 ``os.read`` 直读内核：每次只返回当前可用字节，不做 readline/预读的无界阻塞。
    **不使用 ``select``**：Windows 的 ``select`` 只接受 socket，轮询管道 fd 会直接
    报错（旧实现把该异常吞成「启动超时」，导致提供者隔离进程在 Windows 永远起不来）。
    """

    __slots__ = ("描述符",)

    def __init__(self, 描述符: int) -> None:
        self.描述符 = 描述符

    def read(self, 大小: int = 读取块大小) -> bytes:
        return os.read(self.描述符, int(大小))


#: 排空滞留行的窗口与预算（上层「调用前排空」共用一份口径）
排空窗口秒 = 0.05
排空预算秒 = 2.0
排空预算字节 = 64 * 1024


class 管道读取面:
    """stdout/stderr 消费、带超时行读取与滞留排空簇。

    宿主契约（类注解，真源＝`独立进程.独立进程.__init__`）：名称 / 日志列表 /
    `_读取缓冲` / `_读取条件` / `_读取结束` / `_读取超限` / `_读取序号` /
    `_stderr线程` / `_stdout线程` / `_通信锁` / `进程`。
    `_读取一行` / `弃置滞留行` / `_关闭管道` 由本面提供，被兄弟面
    （启动调用面 / 进程组收口面）运行时经 `self` 解析。
    """

    # ---- 宿主契约（由 独立进程.__init__ 提供，只声明不赋值） ----
    名称: str
    进程: subprocess.Popen | None
    日志列表: list[str]
    _读取缓冲: bytes
    _读取条件: Any
    _读取结束: bool
    _读取超限: bool
    _读取序号: int
    _通信锁: Any
    _stderr线程: Any
    _stdout线程: Any

    # ---- 协作方契约（由兄弟混入面提供，**只声明类型不赋值**：写同名占位方法会按 MRO 遮蔽真实实现） ----
    _记录日志: Any
    _确定解释器: Any


    def _消费stderr(self, 进程: subprocess.Popen) -> None:
        """持续消费 stderr；只保留最近固定数量的块，防管道回压和日志无界。"""
        if 进程.stderr is None:
            return
        try:
            描述符 = 进程.stderr.fileno()
            while True:
                块 = os.read(描述符, 4096)
                if not 块:
                    break
                self.stderr日志.append(块.decode("utf-8", "replace"))
        except (OSError, ValueError):
            pass

    def _启动stderr消费(self, 进程: subprocess.Popen) -> None:
        self._stderr线程 = threading.Thread(
            target=self._消费stderr, args=(进程,),
            name=f"Provider-stderr-{self.名称}-{进程.pid}", daemon=True)
        self._stderr线程.start()

    def _启动stdout消费(self, 进程: subprocess.Popen) -> None:
        """启动 stdout 后台读线程（阻塞式 os.read + 有界IO.受限读取）。

        跨平台收口：**不依赖 select**（Windows 的 select 只支持 socket，轮询管道 fd
        必然报错，旧实现把该异常吞成「启动超时」）。新进程启动前重置交接状态，避免
        迟到半行/超限标记串到新进程。
        """
        with self._读取条件:
            self._读取缓冲 = b""
            self._读取结束 = 假
            self._读取超限 = 假
            self._读取序号 = 0
        self._stdout线程 = threading.Thread(
            target=self._消费stdout, args=(进程,),
            name=f"Provider-stdout-{self.名称}-{进程.pid}", daemon=True)
        self._stdout线程.start()

    def _收块(self, 块: bytes) -> None:
        """后台读线程的数据回调：上限内累积，超限后不再累积但继续排空（防管道回压）。"""
        with self._读取条件:
            if not self._读取超限:
                self._读取缓冲 += 块
                if len(self._读取缓冲) > 响应行上限字节:
                    self._读取超限 = 真
                    self._读取缓冲 = self._读取缓冲[:响应行上限字节]
            self._读取序号 += 1
            self._读取条件.notify_all()

    def _消费stdout(self, 进程: subprocess.Popen) -> None:
        """持续落盘到 EOF：有界IO.受限读取 负责排空与上限，异常收敛为「读取结束」。

        对端正常退出/管道被关闭都会走这里（OSError/ValueError），由等待侧按协议
        判据给出「超时/进程已退出」的结构化结论，故与 stderr 消费同样静默收敛。
        """
        try:
            if 进程.stdout is not None:
                有界IO.受限读取(
                    _描述符读取器(进程.stdout.fileno()), 响应行上限字节,
                    块大小=读取块大小, 数据回调=self._收块)
        except (OSError, ValueError):
            pass
        finally:
            with self._读取条件:
                self._读取结束 = 真
                self._读取条件.notify_all()

    def _读取一行(self, 超时秒: float) -> str:
        """带超时的行读取：**后台读线程 + 有界IO.受限读取**，不轮询管道 fd。

        后台线程用 os.read 直读内核（不经过 readline/TextIOWrapper 预读），
        有界IO.受限读取 负责排空与上限；调用方在条件变量上等一个完整行：
        超过 超时秒 未读到完整行抛 TimeoutError；管道 EOF 抛 ConnectionError；
        单行超过 响应行上限字节 抛 ConnectionError。

        旧实现是 select.select([管道fd]) 轮询 —— Windows 的 select 只支持 socket，
        对管道 fd 直接报错，而 启动() 把该异常吞成「启动超时」，导致提供者隔离
        进程在 Windows 永远起不来。改后台线程后调用点不含任何平台判断。
        """
        截止 = time.monotonic() + max(0.01, 超时秒)
        with self._读取条件:
            while True:
                if b"\n" in self._读取缓冲:
                    行, 剩余 = self._读取缓冲.split(b"\n", 1)
                    self._读取缓冲 = 剩余
                    return 行.decode("utf-8", "replace")
                if self._读取超限:
                    raise ConnectionError(f"响应行超过上限（{响应行上限字节} 字节）")
                if self._读取结束:
                    raise ConnectionError("进程已退出（无响应）")
                剩余时间 = 截止 - time.monotonic()
                if 剩余时间 <= 0:
                    raise TimeoutError(f"读取响应超时（> {超时秒} 秒）")
                self._读取条件.wait(剩余时间)

    def 弃置滞留行(self, *, 窗口秒: float = 排空窗口秒,
                   预算秒: float = 排空预算秒, 预算字节: int = 排空预算字节) -> bool:
        """从后台读线程维护的 `_读取缓冲` 里**非阻塞取/弃完整行**；上层唯一排空入口。

        为什么必须是这一条路（旧实现的病根）：上层原先自己 `select([管道]) +
        readline()` 直读同一个 stdout 管道，与后台读线程**分食同一字节流** ——
        两个读者抢同一批字节，要么上层偷走后台上游字节（后续响应错位、请求id 不匹配），
        要么 `select` 报可读而管道里只有半行时 `readline` 无超时包裹地永久阻塞
        （实测阻塞 > 1 秒，远超 0.05 秒窗口）。管道 fd 现在只有一个读者：
        本类的后台读线程；上层要丢滞留响应只能来这里取**已经交接过来的**完整行。

        语义与旧「调用前排空」逐项对齐：
        - 返回 ``True``：窗口内已收敛（缓冲里的完整行已丢完且窗口内无新数据，
          或后台读线程已 EOF）；
        - 返回 ``False``：超预算 —— 累计丢弃字节 ≥ `预算字节`，或累计时间 ≥ `预算秒`，
          或单行超过 `响应行上限字节`（读缓冲已被判超限，协议流不可信）。
          调用方按「进程不可复用」处理（终止并重启）。
        半行（无换行）**不丢**：它不是完整响应行，擅自按行边界切会伪造协议。

        为什么还要拿 `_通信锁`：排空必须与「在途请求/响应」互斥 —— 否则并发调用时
        会把别人正在等的响应行当滞留行丢掉（JSON 行协议是一问一答，同一进程不能让
        排空插进问答之间）。锁序与 `_发送请求` 一致（通信锁 → 读取条件），不会反向。
        """
        开始 = time.monotonic()
        累计字节 = 0
        with self._通信锁, self._读取条件:
            while True:
                位置 = self._读取缓冲.rfind(b"\n")
                if 位置 >= 0:
                    累计字节 += 位置 + 1
                    self._读取缓冲 = self._读取缓冲[位置 + 1:]
                    if 累计字节 >= 预算字节:
                        return 假
                    continue
                if self._读取超限:
                    return 假
                if self._读取结束:
                    return 真
                剩余时间 = 预算秒 - (time.monotonic() - 开始)
                if 剩余时间 <= 0:
                    return 假
                序号 = self._读取序号
                self._读取条件.wait(min(max(窗口秒, 0.0), 剩余时间))
                if self._读取序号 == 序号 and b"\n" not in self._读取缓冲:
                    # 窗口内无新数据即视为已收敛（与旧实现「一次 select 窗口无可读即停」同语义）
                    return 真

    def _关闭管道(self) -> None:
        """关闭已结束进程的标准管道并回收后台消费线程，避免 fd/线程泄漏。"""
        if self.进程 is None:
            return
        for 管道 in (self.进程.stdin, self.进程.stdout, self.进程.stderr):
            if 管道 is not None and not 管道.closed:
                try:
                    管道.close()
                except OSError:
                    pass
        for 线程 in (self._stderr线程, self._stdout线程):
            if 线程 is not None and 线程 is not threading.current_thread():
                线程.join(timeout=1.0)
