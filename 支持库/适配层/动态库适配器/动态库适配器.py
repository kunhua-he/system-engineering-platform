"""动态库适配器：契约 + 模拟提供者（不加载真实动态库）。

模拟提供者只维护库状态；真实 dlopen/ctypes 加载逻辑归未来提供者
适配层，核心支持库不直接依赖平台加载机制。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.适配契约 import 资源状态_已关闭, 资源状态_已连接, 外部适配器


class 动态库适配器(外部适配器):
    """动态库适配器（当前为模拟提供者）。"""

    适配器名称 = "动态库适配器"
    适配器类型 = "动态库"

    def __init__(self, 库可用: bool = True, 版本: str = "模拟1.0.0") -> None:
        super().__init__()
        self.库可用 = 库可用
        self.版本号 = 版本

    def 检查可用(self) -> 结果:
        if not self.库可用:
            return 结果.失败("外部未安装", "动态库不可用", 来源=self.适配器名称, 可重试=True)
        return 结果.成功结果(True)

    def 获取版本(self) -> 结果:
        return 结果.成功结果(self.版本号)

    def 建立连接(self) -> 结果:
        if not self.库可用:
            return 结果.失败("外部不可访问", "无法加载动态库", 来源=self.适配器名称, 可重试=True)
        self._记录状态(资源状态_已连接)
        return 结果.成功结果("已加载")

    def 执行最小操作(self, 参数: dict | None = None) -> 结果:
        if self.资源状态 != 资源状态_已连接:
            return 结果.失败("外部不可访问", "动态库未加载", 来源=self.适配器名称)
        函数名 = (参数 or {}).get("函数", "示例函数")
        if 函数名 == "不存在的函数":
            return 结果.失败("版本不兼容", f"函数 {函数名} 不存在", 来源=self.适配器名称)
        return 结果.成功结果({"函数": 函数名, "返回": "模拟结果", "来源": "模拟提供者"})

    def 关闭连接(self) -> 结果:
        self._记录状态(资源状态_已关闭)
        return 结果.成功结果("已卸载")

    def 调用函数(self, 函数名: str) -> 结果:
        """动态库适配器专用最小操作。"""
        return self.执行最小操作({"函数": 函数名})
