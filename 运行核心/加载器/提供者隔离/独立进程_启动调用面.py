"""启动调用面：启动握手、协议问答、健康/崩溃检测与世代落账（混入类）。

**为什么独立成文件**：这一簇是「一问一答」协议与启动/重启闭环的实现 ——
解释器解析（`_确定解释器`：声明提供者环境时失败必须阻断，禁止回退）、
环形日志（`_记录日志`）、启动握手（`启动`：subprocess + READY 判定 + 启动超时 +
成功后落世代账本）、请求发送（`_发送请求`：响应请求id 必须匹配）、
`调用` / `健康检查` / `崩溃检测`（崩溃即自动重启并限次数；重启前显式关闭旧管道
并重置读缓冲，避免旧 Popen 管道依赖垃圾回收、新进程继承旧半行造成协议串读）、
世代账本落账/销账（`_登记世代账本` / `_注销世代账本`）。

**为什么落账失败不阻断启动**：账本是**跨重启兜底**，不是启动前置条件 ——
账本库不可写（只读盘/权限）时若拒绝启动，等于把「诊断账本不可用」升级成
「提供者全线不可用」。故失败只如实记进 `账本错误` 与环形日志，代价是这一代进程
失去跨重启回收能力（已知剩余风险，不静默）。

**对外零变化（2026-09-19 拆分）**：正文逐字取自冻结基线
`/tmp/拆分基线/独立进程.py`（1044 行，sha256 前16 = 963513edb4dd3228）。

**导入方向**：本文件只被 `独立进程.py` 模块级导入，**不得反向导入**它；
世代身份与账本读写全部来自叶子模块 `独立进程_账本.py`，
结果类型来自叶子模块 `独立进程_调用面.py`，故不存在任何环。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.版本规则.契约版本 import 取契约版本
from 公共契约.运行时 import 平台适配, 进程终止
from 运行核心.加载器.提供者隔离.独立进程_对象 import (
    进程状态_运行中, 进程状态_启动中, 进程状态_故障, 响应行上限字节, 日志上限)
from 运行核心.加载器.提供者隔离.独立进程_调用面 import 进程调用结果
from 运行核心.加载器.提供者隔离.独立进程_账本 import (
    _定位系统根, _登记常驻进程, _注销常驻进程, 当前网关世代id)


class 启动调用面:
    """启动 / 协议问答 / 健康崩溃检测 / 世代落账簇。

    宿主契约（类注解，真源＝`独立进程.独立进程.__init__`）：名称 / 工作器路径 /
    启动超时秒 / 调用超时秒 / 最大重启次数 / 解释器路径 / 提供者目录 / 端口 /
    资源键 / 账本错误 / 状态 / 进程 / 重启次数 / 退出码 / 日志列表 / 关闭账本。
    协作方（运行时经 `self` 解析，由兄弟混入面提供）：`_关闭管道` / `_读取一行`
    （管道读取面）、`强制终止`（进程组收口面）。
    """

    # ---- 宿主契约（由 独立进程.__init__ 提供，只声明不赋值） ----
    名称: str
    工作器路径: Path
    启动超时秒: float
    调用超时秒: float
    最大重启次数: int
    解释器路径: str | None
    提供者目录: Path | None
    端口: int | None
    资源键: str
    账本错误: str
    状态: str
    进程: subprocess.Popen | None
    重启次数: int
    退出码: int | None
    日志列表: list[str]
    关闭账本: list[dict[str, Any]]

    # ---- 协作方契约（由兄弟混入面提供，**只声明类型不赋值**：写同名占位方法会按 MRO 遮蔽真实实现） ----
    _关闭管道: Any
    _读取一行: Any
    强制终止: Any


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

    def 启动(self) -> tuple[bool, str]:
        """启动子进程并等待 READY（启动超时失败）；成功后把常驻身份落进世代账本。"""
        if self.状态 == 进程状态_运行中:
            return 真, "已在运行"
        self.状态 = 进程状态_启动中
        self.账本错误 = ""
        try:
            # -S 跳过 site 初始化加速子进程启动（工作器自行注入系统根路径）
            系统根 = _定位系统根()
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
                self._登记世代账本()
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

    def _登记世代账本(self) -> None:
        """把本常驻进程的身份原子落进世代账本（失败可见，不静默）。

        为什么落账失败不阻断启动：账本是**跨重启兜底**，不是启动前置条件 —— 账本库
        不可写（只读盘/权限）时若拒绝启动，等于把「诊断账本不可用」升级成「提供者
        全线不可用」。故失败只如实记进 `账本错误` 与环形日志（调用方/诊断可读），
        代价是这一代进程失去跨重启回收能力，属已知剩余风险。
        """
        进程 = self.进程
        if 进程 is None:
            return
        try:
            _登记常驻进程({
                "网关世代id": 当前网关世代id(),
                "网关进程id": os.getpid(),
                "提供者id": self.名称,
                "组长进程id": 进程.pid,
                "进程组号": 进程终止.进程组号(进程.pid),
                "端口": self.端口,
                "资源键": self.资源键,
                "启动时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "启动时间戳": time.time(),
            })
            self.账本错误 = ""
        except Exception as 错误:  # noqa: BLE001 —— 账本不可用必须可见（哲学第 3 条）
            self.账本错误 = f"常驻进程世代账本落账失败: {type(错误).__name__}: {错误}"
            self._记录日志(self.账本错误)

    def _注销世代账本(self) -> None:
        """确认整组收敛后销账（销不掉不影响关闭结论：留行只会让下一世代再收一次）。"""
        try:
            _注销常驻进程(当前网关世代id(), self.名称)
            self.账本错误 = ""
        except Exception as 错误:  # noqa: BLE001 —— 销账失败必须可见
            self.账本错误 = f"常驻进程世代账本销账失败: {type(错误).__name__}: {错误}"
            self._记录日志(self.账本错误)
