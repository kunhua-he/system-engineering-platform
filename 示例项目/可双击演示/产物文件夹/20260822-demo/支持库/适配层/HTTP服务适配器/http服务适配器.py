"""HTTP 服务适配器：契约 + 模拟提供者（不发起真实网络请求）。

模拟提供者不访问网络；真实 HTTP 客户端逻辑归未来提供者适配层。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.适配契约 import 资源状态_已关闭, 资源状态_已连接, 外部适配器


class HTTP服务适配器(外部适配器):
    """HTTP 服务适配器（当前为模拟提供者）。"""

    适配器名称 = "HTTP服务适配器"
    适配器类型 = "HTTP服务"

    def __init__(self, 服务可用: bool = True, 版本: str = "模拟1.0.0") -> None:
        super().__init__()
        self.服务可用 = 服务可用
        self.版本号 = 版本

    def 检查可用(self) -> 结果:
        if not self.服务可用:
            return 结果.失败("外部未安装", "HTTP 客户端不可用", 来源=self.适配器名称, 可重试=True)
        return 结果.成功结果(True)

    def 获取版本(self) -> 结果:
        return 结果.成功结果(self.版本号)

    def 建立连接(self) -> 结果:
        if not self.服务可用:
            return 结果.失败("外部不可访问", "无法连接 HTTP 服务", 来源=self.适配器名称, 可重试=True)
        self._记录状态(资源状态_已连接)
        return 结果.成功结果("已连接")

    def 执行最小操作(self, 参数: dict | None = None) -> 结果:
        if self.资源状态 != 资源状态_已连接:
            return 结果.失败("外部不可访问", "未连接 HTTP 服务", 来源=self.适配器名称)
        路径 = (参数 or {}).get("路径", "/")
        if 路径 == "/超时":
            return 结果.失败("超时", "请求超时", 来源=self.适配器名称, 可重试=True)
        if 路径 == "/错误":
            return 结果.失败("内部错误", "服务内部错误", 来源=self.适配器名称)
        return 结果.成功结果({"状态码": 200, "路径": 路径, "来源": "模拟提供者"})

    def 关闭连接(self) -> 结果:
        self._记录状态(资源状态_已关闭)
        return 结果.成功结果("已关闭")

    def 请求GET(self, 路径: str) -> 结果:
        """HTTP 适配器专用最小操作。"""
        return self.执行最小操作({"路径": 路径})
