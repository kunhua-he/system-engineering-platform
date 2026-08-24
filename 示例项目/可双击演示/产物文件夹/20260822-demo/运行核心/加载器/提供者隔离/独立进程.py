"""真实独立进程：subprocess 运行的工作进程管理。

支持：启动（含启动超时）、标准输入输出通信、请求id、调用超时、取消、
健康检查、崩溃检测、自动重启（次数限制）、资源状态记录、优雅停止、
强制终止、进程退出码记录、日志隔离。

核心只能通过统一中文协议调用提供者，不得泄漏原生进程对象。
"""

from __future__ import annotations

import json
import os
import signal
import select
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

进程状态_已创建 = "已创建"
进程状态_启动中 = "启动中"
进程状态_运行中 = "运行中"
进程状态_已停止 = "已停止"
进程状态_故障 = "故障"

日志上限 = 200  # 日志列表环形裁剪上限（对齐 提供者生命周期._日志上限）


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
        self._读取缓冲 = b""  # os.read 直读内核的行缓冲（绕开 TextIOWrapper 预读）

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
        except OSError as 错误:
            self.状态 = 进程状态_故障
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
        if self.进程 is None or self.进程.poll() is not None:
            raise ConnectionError("进程未运行")
        self.进程.stdin.write(json.dumps(请求, ensure_ascii=False) + "\n")
        self.进程.stdin.flush()
        行 = self._读取一行(self.调用超时秒)
        return json.loads(行)

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
            成功, 消息 = self.启动()
            if 成功:
                return False  # 已重启恢复
        return True  # 崩溃且未恢复

    def 优雅停止(self) -> tuple[bool, str]:
        """优雅停止：发送停止请求，等待退出（超时强制终止）。"""
        if self.状态 == 进程状态_已停止:
            return True, "已停止（幂等）"
        if self.进程 is None:
            self.状态 = 进程状态_已停止
            return True, "无进程，视为已停止"
        try:
            响应 = self._发送请求({"请求id": "停止", "类型": "停止"})
            if not isinstance(响应, dict) or not 响应.get("成功", False):
                return self.强制终止()
            self._记录日志(f"优雅停止（{响应.get('值', '')}）")
        except (TimeoutError, ConnectionError, json.JSONDecodeError):
            return self.强制终止()
        进程 = self.进程
        try:
            进程.wait(timeout=self.调用超时秒)
        except subprocess.TimeoutExpired:
            return self.强制终止()
        self.退出码 = 进程.returncode
        self.状态 = 进程状态_已停止
        self._关闭管道()
        return self.退出码 == 0, f"优雅停止完成（退出码 {self.退出码}）"

    def 强制终止(self) -> tuple[bool, str]:
        """强制终止兜底。"""
        if self.进程 is not None and self.进程.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(self.进程.pid, signal.SIGTERM)
                else:
                    self.进程.terminate()
            except OSError:
                pass
            try:
                self.进程.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "posix":
                        os.killpg(self.进程.pid, signal.SIGKILL)
                    else:
                        self.进程.kill()
                except OSError:
                    pass
                try:
                    self.进程.wait(timeout=2)
                except subprocess.TimeoutExpired as 错误:
                    self.状态 = 进程状态_故障
                    self._关闭管道()
                    return False, f"强制终止超时，进程组未回收: {错误}"
            self.退出码 = self.进程.returncode
        self.状态 = 进程状态_已停止 if self.进程 is None or self.进程.poll() is not None else 进程状态_故障
        self._关闭管道()
        return self.状态 == 进程状态_已停止, f"强制终止完成（退出码 {self.退出码}）"

    def 停止(self) -> tuple[bool, str]:
        return self.优雅停止()

    def 关闭并清理(self) -> None:
        """关闭 stdin/stdout/stderr（资源释放）。"""
        try:
            if self.进程 is not None and self.进程.poll() is None:
                self.强制终止()
            self._关闭管道()
        except (AttributeError, OSError):
            pass


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
