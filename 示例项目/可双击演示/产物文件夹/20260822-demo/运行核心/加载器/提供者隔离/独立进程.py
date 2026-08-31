"""真实独立进程：subprocess 运行的工作进程管理。

支持：启动（含启动超时）、标准输入输出通信、请求id、调用超时、取消、
健康检查、崩溃检测、自动重启（次数限制）、资源状态记录、优雅停止、
强制终止、进程退出码记录、日志隔离。

核心只能通过统一中文协议调用提供者，不得泄漏原生进程对象。
"""

from __future__ import annotations

import json
import hashlib
import os
import signal
import select
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

进程状态_已创建 = "已创建"
进程状态_启动中 = "启动中"
进程状态_运行中 = "运行中"
进程状态_已停止 = "已停止"
进程状态_故障 = "故障"

日志上限 = 200  # 日志列表环形裁剪上限（对齐 提供者生命周期._日志上限）
stderr日志上限 = 200
最大允许池大小 = 16


@dataclass
class 进程调用结果:
    """一次进程调用的统一结果（不泄漏原生对象）。"""

    成功: bool
    值: Any = None
    错误码: str = ""
    错误说明: str = ""
    来源: str = "独立进程"
    可重试: bool = False
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
        self._读取缓冲 = b""  # os.read 直读内核的行缓冲（绕开 TextIOWrapper 预读）
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
        """带超时的行读取：select + os.read 直读内核，避免 readline/缓冲预读无界阻塞。

        内部缓冲保存半行/多行数据（响应行上限 1MB，防恶意无界行）；
        超过 超时秒 未读到完整行抛 TimeoutError；管道 EOF 抛 ConnectionError。
        """
        行缓冲上限 = 1024 * 1024
        截止 = time.monotonic() + max(0.01, 超时秒)
        描述符 = self.进程.stdout.fileno()
        while True:
            if b"\n" in self._读取缓冲:
                行, 剩余 = self._读取缓冲.split(b"\n", 1)
                self._读取缓冲 = 剩余
                return 行.decode("utf-8", "replace")
            剩余时间 = 截止 - time.monotonic()
            if 剩余时间 <= 0:
                raise TimeoutError(f"读取响应超时（> {超时秒} 秒）")
            可读, _, _ = select.select([描述符], [], [], 剩余时间)
            if not 可读:
                raise TimeoutError(f"读取响应超时（> {超时秒} 秒）")
            try:
                块 = os.read(描述符, 4096)
            except OSError as 错误:
                raise ConnectionError(f"读取响应失败: {错误}") from 错误
            if not 块:
                raise ConnectionError("进程已退出（无响应）")
            self._读取缓冲 += 块
            if len(self._读取缓冲) > 行缓冲上限:
                raise ConnectionError(f"响应行超过上限（{行缓冲上限} 字节）")

    def _关闭管道(self) -> None:
        """关闭已结束进程的标准管道，避免文件描述符泄漏。"""
        if self.进程 is None:
            return
        for 管道 in (self.进程.stdin, self.进程.stdout, self.进程.stderr):
            if 管道 is not None and not 管道.closed:
                try:
                    管道.close()
                except OSError:
                    pass
        if (self._stderr线程 is not None
                and self._stderr线程 is not threading.current_thread()):
            self._stderr线程.join(timeout=1.0)

    def 启动(self) -> tuple[bool, str]:
        """启动子进程并等待 READY（启动超时失败）。"""
        if self.状态 == 进程状态_运行中:
            return True, "已在运行"
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
                start_new_session=(os.name == "posix"),
            )
            self._启动stderr消费(self.进程)
        except OSError as 错误:
            self.状态 = 进程状态_故障
            return False, f"启动失败: {错误}"
        except RuntimeError as 错误:
            # 解释器解析/环境构建异常（如提供者隔离环境不可用）：状态置故障，
            # 清空句柄并统一返回失败结果，避免卡在“启动中”且进程表未登记。
            self.状态 = 进程状态_故障
            try:
                self._关闭管道()
            except Exception:
                pass
            return False, f"启动失败: {错误}"
        开始 = time.monotonic()
        while time.monotonic() - 开始 < self.启动超时秒:
            if self.进程.poll() is not None:
                self.状态 = 进程状态_故障
                self.退出码 = self.进程.returncode
                self._关闭管道()
                return False, f"启动超时/提前退出（退出码 {self.退出码}）"
            try:
                # 分段限时读取：每次最多等 0.5 秒，超时走外层整体超时判定并强杀
                行 = self._读取一行(min(0.5, self.启动超时秒 - (time.monotonic() - 开始)))
            except (TimeoutError, ConnectionError, ValueError, OSError):
                行 = ""
            if "READY" in 行:
                self.状态 = 进程状态_运行中
                self._记录日志(f"启动成功（pid {self.进程.pid}）")
                return True, "启动成功"
        self.强制终止()
        self.状态 = 进程状态_故障
        return False, f"启动超时（> {self.启动超时秒} 秒）"

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
             契约版本: str = "1.0.0") -> 进程调用结果:
        """按统一中文协议调用能力（请求id/能力id/契约版本/参数/超时）。"""
        if self.状态 != 进程状态_运行中:
            return 进程调用结果(False, 错误码="外部不可访问", 错误说明=f"进程未运行（状态 {self.状态}）")
        请求 = {
            "请求id": uuid.uuid4().hex[:12], "类型": "调用",
            "能力id": 能力id, "契约版本": 契约版本, "参数": 参数 or {},
            "超时秒": self.调用超时秒, "取消": False,
        }
        try:
            响应 = self._发送请求(请求)
        except TimeoutError as 错误:
            self._记录日志(f"调用超时: {能力id}")
            return 进程调用结果(False, 错误码="超时", 错误说明=str(错误), 可重试=True)
        except (ConnectionError, json.JSONDecodeError) as 错误:
            self.崩溃检测()
            return 进程调用结果(False, 错误码="外部不可访问", 错误说明=str(错误), 可重试=True)
        return 进程调用结果(
            成功=响应.get("成功", False), 值=响应.get("值"),
            错误码=响应.get("错误码", ""), 错误说明=响应.get("错误说明", ""),
            来源=响应.get("来源", "独立进程"), 可重试=响应.get("可重试", False),
            详细信息=响应.get("详细信息", {}),
        )

    def 健康检查(self) -> bool:
        """健康检查：进程存活 + 健康请求响应。"""
        if self.进程 is None or self.进程.poll() is not None:
            return False
        try:
            响应 = self._发送请求({"请求id": "健康", "类型": "健康"})
            return bool(响应.get("成功"))
        except (TimeoutError, ConnectionError, json.JSONDecodeError):
            return False

    def 崩溃检测(self) -> bool:
        """崩溃检测：进程退出即崩溃；触发自动重启（限制次数）。"""
        if self.进程 is None:
            return False
        退出码 = self.进程.poll()
        if 退出码 is None:
            return False
        self.退出码 = 退出码
        self.状态 = 进程状态_故障
        self._记录日志(f"进程崩溃（退出码 {退出码}）")
        if self.重启次数 < self.最大重启次数:
            self.重启次数 += 1
            self._记录日志(f"自动重启（第 {self.重启次数} 次）")
            # 重启前必须显式关闭旧管道并重置读缓冲，避免旧 Popen 管道
            # 依赖垃圾回收、新进程继承旧半行/迟到响应造成协议串读。
            self._关闭管道()
            self._读取缓冲 = b""
            成功, 消息 = self.启动()
            if 成功:
                return False  # 已重启恢复
            self._记录日志(f"自动重启失败: {消息}")
        return True  # 崩溃且未恢复

    def _进程组存活(self) -> bool:
        进程 = self.进程
        if 进程 is None:
            return False
        if os.name != "posix":
            return 进程.poll() is None
        try:
            os.killpg(进程.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

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

    def _发进程组信号(self, 信号值: int) -> None:
        进程 = self.进程
        if 进程 is None:
            return
        try:
            if os.name == "posix" and 进程.pid != os.getpgrp():
                os.killpg(进程.pid, 信号值)
                return
        except (OSError, ProcessLookupError):
            pass
        if 进程.poll() is None:
            try:
                进程.terminate() if 信号值 == signal.SIGTERM else 进程.kill()
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
        return 未收敛

    def _关闭结果(self, *, 已使用SIGKILL: bool = False) -> dict[str, Any]:
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
        已使用SIGKILL = False
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
                self._发进程组信号(signal.SIGTERM)
                self._等待进程组退出(min(max(self.调用超时秒, 0.05), 1.0))
            if self._进程组存活():
                已使用SIGKILL = True
                self._发进程组信号(signal.SIGKILL)
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
        已使用SIGKILL = False
        if self._进程组存活():
            self._发进程组信号(signal.SIGTERM)
            self._等待进程组退出(min(max(self.调用超时秒, 0.05), 1.0))
            if self._进程组存活():
                已使用SIGKILL = True
                self._发进程组信号(signal.SIGKILL)
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
                return False, f"成员 {成员.名称} 启动失败: {消息}"
            已启动.append(成员)
        self.运行状态 = 进程状态_运行中
        return True, f"Provider进程池启动成功（{self.池大小} 个成员）"

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
             契约版本: str = "1.0.0", 资源键: str | None = None) -> 进程调用结果:
        键 = str(资源键 or 能力id)
        成员 = self._分配成员(键)
        if 成员 is None:
            return 进程调用结果(False, 错误码="资源繁忙",
                              错误说明="Provider资源键表已满", 可重试=True)
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
            "已使用SIGKILL": any(项.get("已使用SIGKILL", False) for 项 in 成员结果),
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
            return False, f"启动失败: {消息}"
        if not 进程.健康检查():
            return False, "健康检查失败（已触发崩溃重启）"
        return True, f"运行正常（版本 {getattr(进程, '版本号', '未知')}）"

    def 记录日志(self, 进程: 独立进程, 消息: str) -> None:
        self.日志表.append(f"[{进程.名称}:{getattr(进程, '进程', None).pid if 进程.进程 else '无pid'}] {消息}")

    def 全部健康(self) -> bool:
        return all(进程.状态 == "运行中" for 进程 in self.进程表.values())

    def 停止全部(self, *, 优雅: bool = True) -> list[str]:
        结果列表 = []
        for 进程 in self.进程表.values():
            if 进程.状态 == "运行中":
                if 优雅:
                    结果, 消息 = 进程.优雅停止()
                else:
                    结果, 消息 = 进程.强制终止()
                结果列表.append(f"{进程.名称}: {消息}")
        return 结果列表
