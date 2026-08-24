"""数据库适配器：契约 + 模拟提供者（不连接真实数据库）。

检查可用/获取版本/建立连接/执行最小操作/关闭连接/返回统一结果/
记录资源状态。真实数据库连接逻辑归未来提供者适配层。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.适配契约 import 资源状态_已关闭, 资源状态_已连接, 外部适配器


class 数据库适配器(外部适配器):
    """数据库适配器（当前为模拟提供者）。"""

    适配器名称 = "数据库适配器"
    适配器类型 = "数据库"

    def __init__(self, 驱动可用: bool = True, 版本: str = "模拟1.0.0") -> None:
        super().__init__()
        self.驱动可用 = 驱动可用
        self.版本号 = 版本

    def 检查可用(self) -> 结果:
        if not self.驱动可用:
            return 结果.失败("外部未安装", "数据库驱动不可用", 来源=self.适配器名称, 可重试=True)
        return 结果.成功结果(True)

    def 获取版本(self) -> 结果:
        return 结果.成功结果(self.版本号)

    def 建立连接(self) -> 结果:
        if not self.驱动可用:
            return 结果.失败("外部不可访问", "无法建立数据库连接", 来源=self.适配器名称, 可重试=True)
        self._记录状态(资源状态_已连接)
        return 结果.成功结果("已连接")

    def 执行最小操作(self, 参数: dict | None = None) -> 结果:
        if self.资源状态 != 资源状态_已连接:
            return 结果.失败("外部不可访问", "未连接数据库", 来源=self.适配器名称)
        查询 = (参数 or {}).get("查询", "SELECT 1")
        if "坏查询" in 查询:
            return 结果.失败("协议错误", f"查询语法错误: {查询}", 来源=self.适配器名称)
        return 结果.成功结果({"行": [(1,)], "来源": "模拟提供者"})

    def 关闭连接(self) -> 结果:
        self._记录状态(资源状态_已关闭)
        return 结果.成功结果("已关闭")

    def 执行查询(self, 查询: str) -> 结果:
        """数据库适配器专用最小操作（等价于 执行最小操作）。"""
        return self.执行最小操作({"查询": 查询})
