"""进程组收口面：组信号、收敛核对与关闭/停止四路（混入类）。

**为什么独立成文件**：这一簇是宿主类的「整组回收」接入面 —— 进程组存活判定
（`_进程组存活`）、按组等待（`_等待进程组退出`）、两发组信号（`_发进程组信号`：
终止 → 强杀，带「不向自己进程组发信号」的安全闸）、资源收敛核对（`_核对资源收敛`：
进程组 + 三管道 + 两条消费线程）、关闭结果信封（`_关闭结果`）与四条对外收口路径
（`关闭` / `重试关闭` / `优雅停止` / `强制终止` / `停止` / `关闭并清理`）。

**逻辑唯一实现在 `公共契约/运行时/进程终止.py`**（2026-09-24 批R·R-6）：`进程组存活` /
`等待进程组退出` / `发进程组信号` 三个原语收口后，本文件只保留宿主契约与调用形状
（`self.进程`），不再持有任何组判定或信号实现 —— 同一套流程此前在本文件与
`平台控制面/提供者/进程提供者.py` 各写一份（两份的收尾稳健度并不相同）。

**跨平台收口**：平台差异（有无 `os.killpg`、Windows 无组概念）全部收口在
`公共契约/运行时/进程终止.py` 与 `平台适配.py`，**本文件调用点不做任何平台判断**。
两条必保语义：① 不误伤本进程自己所在的组（靠收口层 `进程组号()`，非 POSIX
平台如实回 `None`）；② 「组长已被 `Popen` 回收但同组子孙仍在」仍按组回收 ——
`Popen.wait()/poll()` 一旦观察到组长退出就把它回收，回收后 `os.getpgid(组长pid)`
必然失败，只有收口层专为此场景补齐的按组号原语（`按组号探活` / `按组号终止`）能表达
（`测试中心/第一批维修/测试_Provider进程.py::test_P0_14`）。

**对外零变化（2026-09-19 拆分）**：正文逐字取自冻结基线
`/tmp/拆分基线/独立进程.py`（1044 行，sha256 前16 = 963513edb4dd3228）；
`信号_终止` / `信号_强杀` / `_已发出信号` 的唯一定义处搬到这里，
主文件经「导入即再导出」拿到同一对象。

**导入方向**：本文件只被 `独立进程.py` 模块级导入，**不得反向导入**它；
`进程状态_已停止` / `进程状态_故障` 来自叶子模块 `独立进程_对象.py`。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 进程终止
from 运行核心.加载器.提供者隔离.独立进程_对象 import 进程状态_已停止, 进程状态_故障
from 运行核心.加载器.提供者隔离.独立进程_账本 import (
    _登记常驻进程, _注销常驻进程, 当前网关世代id)


#: 收口层 进程终止 的信号语义名（POSIX → SIGTERM/SIGKILL；Windows → taskkill 不带/带 /F）
信号_终止 = "终止"
信号_强杀 = "强杀"


#: 判定收口层信封是否**真的发出了信号**：逻辑唯一实现在 `进程终止.信号已发出`。
#: 本名由 `独立进程.py` 以「导入即再导出」对外暴露（该文件不在本批写集内），故以
#: **同一函数对象的导入名**保留 —— 不是第二份实现，也不是兼容壳。
_已发出信号 = 进程终止.信号已发出


class 进程组收口面:
    """进程组收口簇：组信号、收敛核对、关闭/停止四路。

    宿主契约（类注解，真源＝`独立进程.独立进程.__init__`）：名称 / 调用超时秒 /
    进程 / 退出码 / 日志列表 / 关闭账本 / `_stderr线程` / `_stdout线程`。
    协作方（运行时经 `self` 解析，由兄弟混入面提供）：`_关闭管道`（管道读取面）、
    `_发送请求` 与 `_注销世代账本`（启动调用面）。
    """

    # ---- 宿主契约（由 独立进程.__init__ 提供，只声明不赋值） ----
    名称: str
    调用超时秒: float
    进程: subprocess.Popen | None
    退出码: int | None
    日志列表: list[str]
    关闭账本: list[dict[str, Any]]
    _stderr线程: Any
    _stdout线程: Any

    # ---- 协作方契约（由兄弟混入面提供，**只声明类型不赋值**：写同名占位方法会按 MRO 遮蔽真实实现） ----
    _关闭管道: Any
    _发送请求: Any
    _注销世代账本: Any


    def _进程组存活(self) -> bool:
        """成员进程组是否仍存活（组长已回收但同组子孙仍在也算存活）。

        判据与实现唯一在 `公共契约/运行时/进程终止.进程组存活`：句柄未回收 → 真；句柄已回收
        → `按组号探活(组长pid)`（组号 == 组长 pid 由 `子进程组启动标志()` 保证）。本方法只把
        宿主的 `self.进程` 递过去，不持有任何组判定 —— 平台差异全在收口层，调用点不做平台判断。
        """
        return 进程终止.进程组存活(self.进程)

    def _等待进程组退出(self, 超时秒: float) -> bool:
        """按整组口径等退出（组长已回收但同组子孙仍在 ⇒ 未收敛）。

        逻辑唯一在 `公共契约/运行时/进程终止.等待进程组退出`。
        """
        return 进程终止.等待进程组退出(self.进程, 超时秒)

    def _发进程组信号(self, 信号名: str) -> None:
        """向成员进程组发信号：两发都走跨平台收口，**调用点不做任何平台判断**。

        逻辑唯一在 `公共契约/运行时/进程终止.发进程组信号`：按组长身份整组发信号 →
        组长已被 `Popen` 回收时按组号补发（`按组号终止`，组长已回收仍可用）→ 两发都没发出
        且手上有句柄时退化为句柄信号。「不向自己所在的组发信号」的安全闸也在收口层内
        （本进程组号由 `进程组号()` 取，非 POSIX 平台如实回 `None`）—— 保住
        「组长已回收 ≠ 组已收敛」（测试中心/第一批维修/测试_Provider进程.py::test_P0_14）。
        """
        进程终止.发进程组信号(self.进程, 信号名)

    def _核对资源收敛(self) -> list[str]:
        """进程组、三管道、stderr 消费线程全部收敛才算关闭成功。"""
        未收敛: list[str] = []
        进程 = self.进程
        if 进程 is not None and self._进程组存活():
            未收敛.append(f"进程组仍存活:{进程.pid}")
        if 进程 is not None:
            for 名称, 管道 in (("stdin", 进程.stdin), ("stdout", 进程.stdout), ("stderr", 进程.stderr)):
                if 管道 is not None and not 管道.closed:
                    未收敛.append(f"管道未关闭:{名称}")
        if self._stderr线程 is not None and self._stderr线程.is_alive():
            未收敛.append(f"stderr线程仍存活:{self._stderr线程.name}")
        if self._stdout线程 is not None and self._stdout线程.is_alive():
            未收敛.append(f"stdout线程仍存活:{self._stdout线程.name}")
        return 未收敛


    def _关闭结果(self, *, 已使用SIGKILL: bool = 假) -> dict[str, Any]:
        self._关闭管道()
        if self._stderr线程 is not None:
            self._stderr线程.join(timeout=1.0)
        未收敛 = self._核对资源收敛()
        成功 = not 未收敛
        self.状态 = 进程状态_已停止 if 成功 else 进程状态_故障
        if 成功:
            # 只有整组 + 三管道 + 消费线程全部收敛才销账：留着「其实已死」的行无害，
            # 但把「还活着」的行销掉就等于让孤儿失去观测对象（假阴性）。
            self._注销世代账本()
        结果 = {
            "成功": 成功, "错误码": "" if 成功 else "资源未收敛",
            "错误说明": "资源已收敛" if 成功 else f"Provider资源未收敛: {'；'.join(未收敛)}",
            "可重试": not 成功, "未收敛": 未收敛,
            "已使用SIGKILL": 已使用SIGKILL, "退出码": self.退出码,
        }
        self.关闭账本.append(dict(结果, 时间=time.time()))
        return 结果

    def 关闭(self) -> dict[str, Any]:
        """优雅请求后按 TERM→KILL 收口；只有全部资源核对通过才成功。"""
        进程 = self.进程
        已使用SIGKILL = 假
        if self._进程组存活():
            if 进程 is not None and 进程.poll() is None:
                try:
                    self._发送请求({"请求id": uuid.uuid4().hex[:12], "类型": "停止"})
                except (TimeoutError, ConnectionError, json.JSONDecodeError, OSError, ValueError):
                    pass
                try:
                    进程.wait(timeout=self.调用超时秒)
                except subprocess.TimeoutExpired:
                    pass
            if self._进程组存活():
                self._发进程组信号(信号_终止)
                self._等待进程组退出(min(max(self.调用超时秒, 0.05), 1.0))
            if self._进程组存活():
                已使用SIGKILL = 真
                self._发进程组信号(信号_强杀)
                self._等待进程组退出(2.0)
            if 进程 is not None:
                self.退出码 = 进程.poll()
        return self._关闭结果(已使用SIGKILL=已使用SIGKILL)

    def 重试关闭(self) -> dict[str, Any]:
        return self.关闭()

    def 优雅停止(self) -> tuple[bool, str]:
        结果 = self.关闭()
        return bool(结果["成功"]), str(结果["错误说明"])

    def 强制终止(self) -> tuple[bool, str]:
        进程 = self.进程
        已使用SIGKILL = 假
        if self._进程组存活():
            self._发进程组信号(信号_终止)
            self._等待进程组退出(min(max(self.调用超时秒, 0.05), 1.0))
            if self._进程组存活():
                已使用SIGKILL = 真
                self._发进程组信号(信号_强杀)
                self._等待进程组退出(2.0)
            if 进程 is not None:
                self.退出码 = 进程.poll()
        结果 = self._关闭结果(已使用SIGKILL=已使用SIGKILL)
        return bool(结果["成功"]), str(结果["错误说明"])

    def 停止(self) -> tuple[bool, str]:
        return self.优雅停止()

    def 关闭并清理(self) -> dict[str, Any]:
        return self.关闭()
