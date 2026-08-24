"""外部适配契约：平台无关的外部资源适配器统一接口。

外部适配器（数据库/HTTP服务/本地进程/动态库）统一提供：
检查可用、获取版本、建立连接或启动资源、执行最小操作、关闭连接或
释放资源、返回统一结果、记录资源状态。

真实数据库、真实服务器、真实 DLL 的连接逻辑放在未来的提供者适配层，
本契约层只定义接口与资源状态机，不安装第三方库。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

资源状态_未连接 = "未连接"
资源状态_已连接 = "已连接"
资源状态_已关闭 = "已关闭"


class 外部适配器(ABC):
    """外部资源适配器契约基类。"""

    适配器名称: str = ""
    适配器类型: str = ""

    def __init__(self) -> None:
        self.资源状态 = 资源状态_未连接
        self.状态记录: list[str] = []

    def _记录状态(self, 状态: str) -> None:
        self.资源状态 = 状态
        self.状态记录.append(状态)

    @abstractmethod
    def 检查可用(self) -> 结果:
        """检查适配器是否可用（未安装/不可访问必须返回明确错误码）。"""

    @abstractmethod
    def 获取版本(self) -> 结果:
        """获取提供者版本。"""

    @abstractmethod
    def 建立连接(self) -> 结果:
        """建立连接或启动资源；成功后资源状态=已连接。"""

    @abstractmethod
    def 执行最小操作(self, 参数: dict | None = None) -> 结果:
        """执行最小操作（验证连通性的最小动作）。"""

    @abstractmethod
    def 关闭连接(self) -> 结果:
        """关闭连接或释放资源；成功后资源状态=已关闭。"""

    def 完整生命周期(self, 参数: dict | None = None) -> list[结果]:
        """按 检查→版本→连接→操作→关闭 顺序执行；任一失败即停。"""
        结果列表 = [
            self.检查可用(),
            self.获取版本(),
        ]
        if not all(结果.成功 for 结果 in 结果列表):
            return 结果列表
        结果列表.append(self.建立连接())
        if not 结果列表[-1].成功:
            return 结果列表
        结果列表.append(self.执行最小操作(参数))
        结果列表.append(self.关闭连接())
        return 结果列表
