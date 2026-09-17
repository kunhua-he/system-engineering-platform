"""真实独立进程：subprocess 运行的工作进程管理。

支持：启动（含启动超时）、标准输入输出通信、请求id、调用超时、取消、
健康检查、崩溃检测、自动重启（次数限制）、资源状态记录、优雅停止、
强制终止、进程退出码记录、日志隔离。

核心只能通过统一中文协议调用提供者，不得泄漏原生进程对象。

**跨平台收口（华哥 2026-09-16 裁决：底座做完整跨平台）**：子进程组启动标志、进程组存活
判定、组信号发送全部走 `公共契约/运行时/平台适配.py` 与 `公共契约/运行时/进程终止.py`
—— **本文件调用点不含任何平台判断**（无 `os.name` / `sys.platform` / `os.killpg` /
`os.getpgrp`）。**「进程组归属」与「隔离回收」语义不变**：组长被 `poll()` 回收后，
「同组子孙仍在」只有收口层的按组号原语（`按组号探活` / `按组号终止`）能表达。

**管道读取同样不做平台判断**：stdout 由后台线程阻塞式 `os.read` 直读内核并用
`公共契约/运行时/有界IO.受限读取` 排空+限界，调用方在条件变量上等一个完整行
—— 不再用 `select` 轮询管道 fd（Windows 的 `select` 只接受 socket，轮询管道必然报错）。
"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import time
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.版本规则.契约版本 import 取契约版本
from 公共契约.运行时 import 平台适配, 进程终止, 有界IO
from 公共契约.基础类型.逻辑类型 import 真, 假

进程状态_已创建 = "已创建"
进程状态_启动中 = "启动中"
进程状态_运行中 = "运行中"
进程状态_已停止 = "已停止"
进程状态_故障 = "故障"

日志上限 = 200  # 日志列表环形裁剪上限（对齐 提供者生命周期._日志上限）
stderr日志上限 = 200
最大允许池大小 = 16
响应行上限字节 = 1024 * 1024  # 单行响应上限（防恶意/异常进程写无界行）
读取块大小 = 4096  # 直读内核的块大小（不做 TextIOWrapper 预读）


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


#: 收口层 进程终止 的信号语义名（POSIX → SIGTERM/SIGKILL；Windows → taskkill 不带/带 /F）
信号_终止 = "终止"
信号_强杀 = "强杀"


def _已发出信号(收口结果) -> bool:
    """判定收口层 ``进程终止`` 的结果信封是否**真的发出了信号**。

    只读信封里的 ``已发出信号`` 字段（它由收口层按平台事实填写），调用点不猜平台：
    成功类结论（``已终止`` / ``已终止（回退）``）在 ``.值``，失败类结论在 ``.详细信息``。
    """
    载荷 = 收口结果.值 or 收口结果.详细信息 or {}
    return bool(载荷.get("已发出信号"))


@dataclass
class 进程调用结果:
    """一次进程调用的统一结果（不泄漏原生对象）。"""

    成功: bool
    值: Any = None
    错误码: str = ""
    错误说明: str = ""
    来源: str = "独立进程"
    可重试: bool = 假
    详细信息: dict[str, Any] = field(default_factory=dict)

    def 转字典(self) -> dict[str, Any]:
        return {
            "成功": self.成功, "值": self.值, "错误码": self.错误码,
            "错误说明": self.错误说明, "来源": self.来源,
            "可重试": self.可重试, "详细信息": self.详细信息,
        }


class 独立进程:
    """真实独立工作进程（subprocess + JSON 行协议）。"""

    def __init__(self, 名称: str, *, 工作器路径: Path | None = None,
                 启动超时秒: float = 5.0, 调用超时秒: float = 3.0,
                 最大重启次数: int = 3, 解释器路径: str | None = None,
                 提供者目录: Path | None = None) -> None:
        self.名称 = 名称
        self.工作器路径 = 工作器路径 or Path(__file__).resolve().parent / "进程工作器.py"
        self.启动超时秒 = 启动超时秒
        self.调用超时秒 = 调用超时秒
        self.最大重启次数 = 最大重启次数
        self.解释器路径 = 解释器路径
        self.提供者目录 = 提供者目录
        self.状态 = 进程状态_已创建
        self.进程: subprocess.Popen | None = None
        self.重启次数 = 0
        self.退出码: int | None = None
        self.日志列表: list[str] = []
        self.stderr日志 = deque(maxlen=stderr日志上限)
        self._stderr线程: threading.Thread | None = None
        self.关闭账本: list[dict[str, Any]] = []
        self._读取缓冲 = b""  # 后台读线程交接的行缓冲（os.read 直读内核，无预读）
        # 后台 stdout 读线程 ↔ 调用方的交接（条件变量：不用 sleep 轮询，也不用 select）
        self._读取条件 = threading.Condition()
        self._读取结束 = 假  # 后台读线程已 EOF/出错
        self._读取超限 = 假  # 单行超过 响应行上限字节
        self._stdout线程: threading.Thread | None = None
        # JSON 行协议是一问一答；同一 Provider 进程不能让多个线程交叉
        # 写 stdin/读 stdout，否则迟到响应会被下一请求消费。
        self._通信锁 = threading.RLock()

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

    def _确定解释器(self) -> str:
        """确定子进程解释器；声明提供者环境时失败必须阻断，禁止回退。"""
        if self.解释器路径:
            return self.解释器路径
        if self.提供者目录 is not None:
            try:
                from 运行核心.运行环境管理器 import 确保环境
                结果 = 确保环境(self.提供者目录)
                if 结果.成功 and 结果.解释器路径:
                    return 结果.解释器路径
            except Exception as 错误:
                raise RuntimeError(f"提供者隔离环境校验失败: {错误}") from 错误
            raise RuntimeError("提供者隔离环境不可用：未返回受管解释器")
        return sys.executable

    def _记录日志(self, 消息: str) -> None:
        self.日志列表.append(f"[{time.strftime('%H:%M:%S')}] {消息}")
        if len(self.日志列表) > 日志上限:
            del self.日志列表[:len(self.日志列表) - 日志上限]

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

    def 启动(self) -> tuple[bool, str]:
        """启动子进程并等待 READY（启动超时失败）。"""
        if self.状态 == 进程状态_运行中:
            return 真, "已在运行"
        self.状态 = 进程状态_启动中
        try:
            # -S 跳过 site 初始化加速子进程启动（工作器自行注入系统根路径）
            系统根 = Path(__file__).resolve()
            for _祖先 in 系统根.parents:
                if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
                    系统根 = _祖先
                    break
            self.进程 = subprocess.Popen(
                [self._确定解释器(), "-S", str(self.工作器路径), str(系统根)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1,
                env={**os.environ, "PYTHONNOUSERSITE": "1"},
                **平台适配.子进程组启动标志(),
            )
            self._启动stderr消费(self.进程)
            # stdout 后台读线程必须先起：READY/响应行由它落到交接缓冲，
            # 启动循环只做「等一行 + 判 READY」，不再轮询管道 fd。
            self._启动stdout消费(self.进程)
        except OSError as 错误:
            self.状态 = 进程状态_故障
            return 假, f"启动失败: {错误}"
        except RuntimeError as 错误:
            # 解释器解析/环境构建异常（如提供者隔离环境不可用）：状态置故障，
            # 清空句柄并统一返回失败结果，避免卡在“启动中”且进程表未登记。
            self.状态 = 进程状态_故障
            try:
                self._关闭管道()
            except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条）
                记录忽略('独立进程.启动', 错误)
            return 假, f"启动失败: {错误}"
        开始 = time.monotonic()
        while time.monotonic() - 开始 < self.启动超时秒:
            if self.进程.poll() is not None:
                self.状态 = 进程状态_故障
                self.退出码 = self.进程.returncode
                self._关闭管道()
                return 假, f"启动超时/提前退出（退出码 {self.退出码}）"
            try:
                # 分段限时读取：每次最多等 0.5 秒，超时走外层整体超时判定并强杀
                行 = self._读取一行(min(0.5, self.启动超时秒 - (time.monotonic() - 开始)))
            except (TimeoutError, ConnectionError, ValueError, OSError):
                行 = ""
            if "READY" in 行:
                self.状态 = 进程状态_运行中
                self._记录日志(f"启动成功（pid {self.进程.pid}）")
                return 真, "启动成功"
        self.强制终止()
        self.状态 = 进程状态_故障
        return 假, f"启动超时（> {self.启动超时秒} 秒）"

    def _发送请求(self, 请求: dict) -> dict:
        with self._通信锁:
            if self.进程 is None or self.进程.poll() is not None:
                raise ConnectionError("进程未运行")
            self.进程.stdin.write(json.dumps(请求, ensure_ascii=False) + "\n")
            self.进程.stdin.flush()
            行 = self._读取一行(self.调用超时秒)
            响应 = json.loads(行)
            if 响应.get("请求id") != 请求.get("请求id"):
                raise ConnectionError(
                    f"响应请求id不匹配: 期望 {请求.get('请求id')}，实际 {响应.get('请求id')}")
            return 响应

    def 调用(self, *, 能力id: str, 参数: dict | None = None,
             契约版本: str | None = None) -> 进程调用结果:
        """按统一中文协议调用能力（请求id/能力id/契约版本/参数/超时）。

        契约版本 缺省取唯一事实源（公共契约/版本规则/契约版本.py），不写死字面量。
        """
        契约版本 = 契约版本 or 取契约版本()
        if self.状态 != 进程状态_运行中:
            return 进程调用结果(假, 错误码="外部不可访问", 错误说明=f"进程未运行（状态 {self.状态}）")
        请求 = {
            "请求id": uuid.uuid4().hex[:12], "类型": "调用",
            "能力id": 能力id, "契约版本": 契约版本, "参数": 参数 or {},
            "超时秒": self.调用超时秒, "取消": 假,
        }
        try:
            响应 = self._发送请求(请求)
        except TimeoutError as 错误:
            self._记录日志(f"调用超时: {能力id}")
            return 进程调用结果(假, 错误码="超时", 错误说明=str(错误), 可重试=真)
        except (ConnectionError, json.JSONDecodeError) as 错误:
            self.崩溃检测()
            return 进程调用结果(假, 错误码="外部不可访问", 错误说明=str(错误), 可重试=真)
        return 进程调用结果(
            成功=响应.get("成功", 假), 值=响应.get("值"),
            错误码=响应.get("错误码", ""), 错误说明=响应.get("错误说明", ""),
            来源=响应.get("来源", "独立进程"), 可重试=响应.get("可重试", 假),
            详细信息=响应.get("详细信息", {}),
        )

    def 健康检查(self) -> bool:
        """健康检查：进程存活 + 健康请求响应。"""
        if self.进程 is None or self.进程.poll() is not None:
            return 假
        try:
            响应 = self._发送请求({"请求id": "健康", "类型": "健康"})
            return bool(响应.get("成功"))
        except (TimeoutError, ConnectionError, json.JSONDecodeError):
            return 假

    def 崩溃检测(self) -> bool:
        """崩溃检测：进程退出即崩溃；触发自动重启（限制次数）。"""
        if self.进程 is None:
            return 假
        退出码 = self.进程.poll()
        if 退出码 is None:
            return 假
        self.退出码 = 退出码
        self.状态 = 进程状态_故障
        self._记录日志(f"进程崩溃（退出码 {退出码}）")
        if self.重启次数 < self.最大重启次数:
            self.重启次数 += 1
            self._记录日志(f"自动重启（第 {self.重启次数} 次）")
            # 重启前必须显式关闭旧管道并重置读缓冲，避免旧 Popen 管道
            # 依赖垃圾回收、新进程继承旧半行/迟到响应造成协议串读。
            # （读缓冲/结束/超限标记由 _启动stdout消费 在起线程前统一重置）
            self._关闭管道()
            self._读取缓冲 = b""
            成功, 消息 = self.启动()
            if 成功:
                return 假  # 已重启恢复
            self._记录日志(f"自动重启失败: {消息}")
        return 真  # 崩溃且未恢复

    def _进程组存活(self) -> bool:
        """成员进程组是否仍存活（组长已回收但同组子孙仍在也算存活）。

        **为什么必须用「按组号」的收口原语**：收口层 `进程存活` / `终止进程组` 都以
        `os.getpgid(pid)` 为判定前提，而 `Popen.wait()/poll()` 一旦观察到组长退出就把
        它**回收**，回收后 `os.getpgid(组长pid)` 必然失败（收口只能如实判「进程不存在」）
        —— 于是「组长正常退出、同组子孙仍在」这条语义就判不出来了，而这正是本类必须
        覆盖的语义（测试中心/第一批维修/测试_Provider进程.py::test_P0_14_组长正常退出
        也必须回收同组子进程）。

        故先看句柄（句柄未回收即未退出 → 组必然活着），句柄已回收才用收口层为此场景
        专门补齐的 `按组号探活(组长pid)`（组号 == 组长 pid，由 `子进程组启动标志()` 保证）。
        平台差异（有无 `os.killpg`、Windows 无组概念）全部收口在
        `公共契约/运行时/进程终止.py`，**本调用点不做任何平台判断**。
        """
        进程 = self.进程
        if 进程 is None:
            return 假
        if 进程.poll() is None:
            return 真
        return 进程终止.按组号探活(进程.pid)

    def _等待进程组退出(self, 超时秒: float) -> bool:
        截止 = time.monotonic() + max(0.0, 超时秒)
        while self._进程组存活() and time.monotonic() < 截止:
            time.sleep(0.01)
        进程 = self.进程
        if 进程 is not None and 进程.poll() is None and not self._进程组存活():
            try:
                进程.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        return not self._进程组存活()

    def _发进程组信号(self, 信号名: str) -> None:
        """向成员进程组发信号：两发都走跨平台收口，**调用点不做任何平台判断**。

        第一发 `终止进程组(组长pid)`：组长仍活着（含僵尸）时收口按组长身份一次整组终止，
        非组长则退化为单进程（不误伤同组其他进程）—— 这正是原实现里自己拼
        `os.name == "posix"` + `killpg` + `pid != os.getpgrp()` 分支要表达的语义。

        组长已被 `Popen` 回收时收口取不到组号（只能如实回「进程不存在」），而组内子孙可能
        仍在，故第二发改用收口层专为此场景补齐的 `按组号终止(组长pid)` 补发一次 ——
        保住「组长已回收 ≠ 组已收敛」（测试中心/第一批维修/测试_Provider进程.py::test_P0_14）。

        `本进程组号` 由收口 `进程组号()` 取（非 POSIX 平台如实回 `None`），仅用于避免误伤
        本进程自己所在的组 —— 这不是平台判断，而是「不要打自己」的安全闸；收口两层都
        没真的发出信号时才退化为单进程句柄信号（与原实现 killpg 抛错后回退同语义）。
        """
        进程 = self.进程
        if 进程 is None:
            return
        if _已发出信号(进程终止.终止进程组(进程.pid, 信号=信号名)):
            return
        本进程组号 = 进程终止.进程组号(os.getpid())
        if 本进程组号 is None or 进程.pid != 本进程组号:
            if _已发出信号(进程终止.按组号终止(进程.pid, 信号=信号名)):
                return
        if 进程.poll() is None:
            try:
                进程.terminate() if 信号名 == 信号_终止 else 进程.kill()
            except (OSError, ProcessLookupError):
                pass

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


class 提供者进程池:
    """有界 Provider 进程池；资源键稳定绑定成员，每个成员独立管道和通信锁。"""

    def __init__(self, 名称: str, *, 池大小: int = 2, 最大资源键数: int = 4096,
                 工作器路径: Path | None = None, 启动超时秒: float = 5.0,
                 调用超时秒: float = 3.0, 最大重启次数: int = 3,
                 解释器路径: str | None = None, 提供者目录: Path | None = None) -> None:
        if not 1 <= int(池大小) <= 最大允许池大小:
            raise ValueError(f"池大小必须在 1..{最大允许池大小} 之间")
        if 最大资源键数 < 池大小:
            raise ValueError("最大资源键数不得小于池大小")
        self.名称 = 名称
        self.池大小 = int(池大小)
        self.最大资源键数 = int(最大资源键数)
        self.成员表 = [独立进程(
            f"{名称}#{序号 + 1}", 工作器路径=工作器路径,
            启动超时秒=启动超时秒, 调用超时秒=调用超时秒,
            最大重启次数=最大重启次数, 解释器路径=解释器路径,
            提供者目录=提供者目录) for 序号 in range(self.池大小)]
        self.资源分配: dict[str, int] = {}
        self._分配锁 = threading.Lock()
        self.关闭账本: list[dict[str, Any]] = []
        self.运行状态 = 进程状态_已创建

    def 启动(self) -> tuple[bool, str]:
        已启动: list[独立进程] = []
        for 成员 in self.成员表:
            成功, 消息 = 成员.启动()
            if not 成功:
                for 已有成员 in 已启动:
                    已有成员.关闭并清理()
                self.运行状态 = 进程状态_故障
                return 假, f"成员 {成员.名称} 启动失败: {消息}"
            已启动.append(成员)
        self.运行状态 = 进程状态_运行中
        return 真, f"Provider进程池启动成功（{self.池大小} 个成员）"

    def _分配成员(self, 资源键: str) -> 独立进程 | None:
        with self._分配锁:
            索引 = self.资源分配.get(资源键)
            if 索引 is None:
                if len(self.资源分配) >= self.最大资源键数:
                    return None
                摘要 = hashlib.sha256(资源键.encode("utf-8")).digest()
                索引 = int.from_bytes(摘要[:8], "big") % self.池大小
                self.资源分配[资源键] = 索引
            return self.成员表[索引]

    def 调用(self, *, 能力id: str, 参数: dict | None = None,
             契约版本: str | None = None, 资源键: str | None = None) -> 进程调用结果:
        契约版本 = 契约版本 or 取契约版本()
        键 = str(资源键 or 能力id)
        成员 = self._分配成员(键)
        if 成员 is None:
            return 进程调用结果(假, 错误码="资源繁忙",
                              错误说明="Provider资源键表已满", 可重试=真)
        return 成员.调用(能力id=能力id, 参数=参数, 契约版本=契约版本)

    def 健康检查(self) -> bool:
        return bool(self.成员表) and all(成员.健康检查() for 成员 in self.成员表)

    def _核对资源收敛(self) -> list[str]:
        未收敛: list[str] = []
        for 序号, 成员 in enumerate(self.成员表):
            未收敛.extend(f"成员{序号 + 1}:{问题}" for 问题 in 成员._核对资源收敛())
        return 未收敛

    def 关闭(self) -> dict[str, Any]:
        成员结果 = [成员.关闭并清理() for 成员 in self.成员表]
        未收敛 = self._核对资源收敛()
        成功 = not 未收敛 and all(结果["成功"] for 结果 in 成员结果)
        if not 成功 and not 未收敛:
            未收敛 = [结果["错误说明"] for 结果 in 成员结果 if not 结果["成功"]]
        self.运行状态 = 进程状态_已停止 if 成功 else 进程状态_故障
        结果 = {
            "成功": 成功, "错误码": "" if 成功 else "资源未收敛",
            "错误说明": "Provider进程池资源已收敛" if 成功 else f"Provider进程池资源未收敛: {'；'.join(未收敛)}",
            "可重试": not 成功, "未收敛": 未收敛,
            "已使用SIGKILL": any(项.get("已使用SIGKILL", 假) for 项 in 成员结果),
            "成员结果": 成员结果,
        }
        self.关闭账本.append(dict(结果, 时间=time.time()))
        return 结果

    def 重试关闭(self) -> dict[str, Any]:
        return self.关闭()

    def 状态(self) -> dict[str, Any]:
        成员状态 = [{
            "名称": 成员.名称,
            "状态": 成员.状态,
            "pid": 成员.进程.pid if 成员.进程 is not None else None,
            "stderr日志": list(成员.stderr日志),
            "退出码": 成员.退出码,
        } for 成员 in self.成员表]
        return {
            "状态": self.运行状态, "池大小": self.池大小,
            "pid表": [项["pid"] for 项 in 成员状态 if 项["pid"] is not None],
            "成员表": 成员状态, "资源分配": dict(self.资源分配),
            "关闭账本": list(self.关闭账本),
        }


class 进程管理器:
    """进程管理器（第五阶段兼容接口）：创建、监控、重启、隔离。"""

    def __init__(self) -> None:
        self.进程表: dict[str, 独立进程] = {}
        self.日志表: list[str] = []

    def 创建进程(self, 名称: str, *, 版本: str = "") -> 独立进程:
        进程 = 独立进程(名称)
        进程.版本号 = 版本
        self.进程表[名称] = 进程
        return 进程

    def 启动并检查(self, 进程: 独立进程) -> tuple[bool, str]:
        成功, 消息 = 进程.启动()
        if not 成功:
            return 假, f"启动失败: {消息}"
        if not 进程.健康检查():
            return 假, "健康检查失败（已触发崩溃重启）"
        return 真, f"运行正常（版本 {getattr(进程, '版本号', '未知')}）"

    def 记录日志(self, 进程: 独立进程, 消息: str) -> None:
        self.日志表.append(f"[{进程.名称}:{getattr(进程, '进程', None).pid if 进程.进程 else '无pid'}] {消息}")

    def 全部健康(self) -> bool:
        return all(进程.状态 == "运行中" for 进程 in self.进程表.values())

    def 停止全部(self, *, 优雅: bool = 真) -> list[str]:
        结果列表 = []
        for 进程 in self.进程表.values():
            if 进程.状态 == "运行中":
                if 优雅:
                    结果, 消息 = 进程.优雅停止()
                else:
                    结果, 消息 = 进程.强制终止()
                结果列表.append(f"{进程.名称}: {消息}")
        return 结果列表
