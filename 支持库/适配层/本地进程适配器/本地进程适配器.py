"""本地进程适配器：契约 + 模拟提供者（不启动真实进程）。

模拟提供者只维护进程状态；真实子进程管理逻辑归未来提供者适配层。
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.适配契约 import 资源状态_已关闭, 资源状态_已连接, 外部适配器


class 本地进程适配器(外部适配器):
    """本地进程适配器（当前为模拟提供者）。"""

    适配器名称 = "本地进程适配器"
    适配器类型 = "本地进程"

    def __init__(self, 程序可用: bool = True, 版本: str = "模拟1.0.0") -> None:
        super().__init__()
        self.程序可用 = 程序可用
        self.版本号 = 版本
        self.运行进程: subprocess.Popen | None = None
        self.临时资源表: list[str] = []

    def 检查可用(self) -> 结果:
        if not self.程序可用:
            return 结果.失败("外部未安装", "本地程序不可用", 来源=self.适配器名称, 可重试=True)
        return 结果.成功结果(True)

    def 获取版本(self) -> 结果:
        return 结果.成功结果(self.版本号)

    def 建立连接(self) -> 结果:
        if not self.程序可用:
            return 结果.失败("外部不可访问", "无法启动本地进程", 来源=self.适配器名称, 可重试=True)
        self._记录状态(资源状态_已连接)
        return 结果.成功结果("已启动")

    def 执行最小操作(self, 参数: dict | None = None) -> 结果:
        if self.资源状态 != 资源状态_已连接:
            return 结果.失败("外部不可访问", "本地进程未启动", 来源=self.适配器名称)
        命令 = (参数 or {}).get("命令", "echo")
        if 命令 == "坏命令":
            return 结果.失败("参数错误", f"未知命令: {命令}", 来源=self.适配器名称)
        return 结果.成功结果({"命令": 命令, "退出码": 0, "来源": "模拟提供者"})

    def 关闭连接(self) -> 结果:
        self._记录状态(资源状态_已关闭)
        return 结果.成功结果("已停止")

    def 执行命令(self, 命令: str) -> 结果:
        """本地进程适配器专用最小操作。"""
        return self.执行最小操作({"命令": 命令})

    def 执行命令受控(
        self,
        命令列表: list[str],
        *,
        超时秒: float = 30.0,
        输出上限字节: int = 1024 * 1024,
        工作目录: str = "",
    ) -> 结果:
        """真实子进程执行：独立进程组 + 超时 killpg 回收 + 输出上限。

        覆盖：启动失败→参数错误；执行超时→超时并 killpg 终止进程组；
        输出超过上限→超出限制；非零退出→执行失败。
        """
        if not isinstance(命令列表, list) or not 命令列表 or not all(
            isinstance(项, str) for 项 in 命令列表
        ):
            return 结果.失败("参数错误", "命令列表必须为非空文本列表", 来源=self.适配器名称)
        try:
            进程 = subprocess.Popen(
                命令列表,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=工作目录 or None,
                start_new_session=True,
            )
        except OSError as 错误:
            return 结果.失败("启动失败", f"无法启动本地进程: {错误}", 来源=self.适配器名称, 可重试=True)
        self.运行进程 = 进程
        try:
            标准输出, _标准错误 = 进程.communicate(timeout=超时秒)
        except subprocess.TimeoutExpired:
            self._终止进程组(进程)
            return 结果.失败("超时", f"本地进程执行超过 {超时秒} 秒", 来源=self.适配器名称, 可重试=True)
        finally:
            self.运行进程 = None
            for 流 in (进程.stdout, 进程.stderr):
                try:
                    if 流 is not None:
                        流.close()
                except (OSError, ValueError):
                    pass
        if len(标准输出) > 输出上限字节:
            return 结果.失败("超出限制", f"本地进程输出超过上限 {输出上限字节} 字节", 来源=self.适配器名称)
        if 进程.returncode != 0:
            return 结果.失败("执行失败", f"本地进程退出码 {进程.returncode}", 来源=self.适配器名称)
        return 结果.成功结果({"输出": 标准输出.decode("utf-8", errors="replace"), "退出码": 进程.returncode})

    def _终止进程组(self, 进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
        """killpg 回收整个进程组（SIGTERM → 宽限 → SIGKILL），零残留。"""
        try:
            os.killpg(os.getpgid(进程.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            进程.wait(timeout=宽限秒)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(os.getpgid(进程.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            进程.wait(timeout=宽限秒)
        except subprocess.TimeoutExpired:
            pass

    def 取消运行(self) -> 结果:
        """取消正在运行的子进程（killpg 终止进程组）。"""
        进程 = self.运行进程
        if 进程 is None or 进程.poll() is not None:
            return 结果.成功结果("无运行进程")
        self._终止进程组(进程)
        self.运行进程 = None
        return 结果.成功结果("已取消")

    def 登记临时资源(self, 路径: str) -> 结果:
        """登记进程产生的临时资源（文件或目录），由 清理临时资源 统一释放。"""
        if not isinstance(路径, str) or not 路径.strip():
            return 结果.失败("参数错误", "路径必须为非空文本", 来源=self.适配器名称)
        if 路径 not in self.临时资源表:
            self.临时资源表.append(路径)
        return 结果.成功结果(len(self.临时资源表))

    def 清理临时资源(self) -> 结果:
        """清理全部已登记临时资源（文件删除/目录递归删除，幂等）。"""
        from pathlib import Path as 路径类
        失败表 = []
        for 路径 in list(self.临时资源表):
            try:
                目标 = 路径类(路径)
                if 目标.is_dir():
                    shutil.rmtree(目标)
                else:
                    目标.unlink(missing_ok=True)
            except OSError as 错误:
                失败表.append(f"{路径}: {错误}")
        self.临时资源表.clear()
        if 失败表:
            return 结果.失败("清理失败", "；".join(失败表), 来源=self.适配器名称)
        return 结果.成功结果()
