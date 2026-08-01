"""本地进程适配器：契约 + 模拟提供者（不启动真实进程）。

模拟提供者只维护进程状态；真实子进程管理逻辑归未来提供者适配层。
"""

from __future__ import annotations

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
