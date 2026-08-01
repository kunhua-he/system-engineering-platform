"""提供者注册表：外部提供者注册与唯一选择。

规则：同一适配能力只能选择一个提供者；提供者必须声明名称、版本、
能力和配置需求；提供者不可用时返回明确错误；提供者初始化失败必须
回滚；提供者停止后必须释放运行时状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.配置契约.提供者配置契约 import 提供者配置需求


@dataclass
class 提供者声明:
    """一份提供者注册声明。"""

    名称: str
    版本: str
    能力列表: list[str]
    配置需求: list[提供者配置需求] = field(default_factory=list)
    创建函数: Callable[..., Any] | None = None  # 接收配置字典，返回适配器实例


class 提供者注册表:
    """提供者注册表：注册、唯一选择、初始化（含回滚）、停止（含释放）。"""

    def __init__(self) -> None:
        self.注册表: dict[str, 提供者声明] = {}  # 提供者名称 → 声明
        self.能力映射: dict[str, str] = {}  # 能力id → 提供者名称
        self.活动实例: dict[str, Any] = {}  # 能力id → 运行中适配器实例
        self.状态表: dict[str, str] = {}  # 能力id → 运行状态

    def 注册提供者(self, 声明: 提供者声明) -> 结果:
        """注册提供者；重名或同能力多提供者必须失败。"""
        if 声明.名称 in self.注册表:
            return 结果.失败("提供者冲突", f"提供者已注册: {声明.名称}", 来源="提供者注册表")
        for 能力id in 声明.能力列表:
            if 能力id in self.能力映射:
                return 结果.失败(
                    "提供者冲突",
                    f"能力 {能力id} 已有提供者 {self.能力映射[能力id]}，同一能力只能选择一个提供者",
                    来源="提供者注册表",
                )
        self.注册表[声明.名称] = 声明
        for 能力id in 声明.能力列表:
            self.能力映射[能力id] = 声明.名称
        return 结果.成功结果(声明.名称)

    def 选择提供者(self, 能力id: str) -> 结果:
        """按能力选择唯一提供者；无提供者返回明确错误。"""
        提供者名称 = self.能力映射.get(能力id)
        if 提供者名称 is None:
            return 结果.失败(
                "外部未安装", f"能力 {能力id} 无可用提供者", 来源="提供者注册表", 可重试=True
            )
        return 结果.成功结果(self.注册表[提供者名称])

    def 初始化提供者(self, 能力id: str, 配置: dict[str, Any] | None = None) -> 结果:
        """初始化提供者（创建实例+建立连接）；失败回滚并释放。"""
        配置 = 配置 or {}
        选择结果 = self.选择提供者(能力id)
        if not 选择结果.成功:
            return 选择结果
        声明 = 选择结果.值
        if 能力id in self.活动实例:
            return 结果.失败("提供者冲突", f"能力 {能力id} 已初始化", 来源="提供者注册表")
        try:
            实例 = 声明.创建函数(配置) if 声明.创建函数 else None
            if 实例 is None:
                return 结果.失败("内部错误", f"提供者 {声明.名称} 创建失败", 来源="提供者注册表")
            检查结果 = 实例.检查可用()
            if not 检查结果.成功:
                return 检查结果
            连接结果 = 实例.建立连接()
            if not 连接结果.成功:
                return 连接结果
            self.活动实例[能力id] = 实例
            self.状态表[能力id] = "已连接"
            return 结果.成功结果(实例)
        except Exception as 错误:
            self.活动实例.pop(能力id, None)
            self.状态表.pop(能力id, None)
            return 结果.失败("内部错误", f"提供者初始化失败已回滚: {错误}", 来源="提供者注册表")

    def 调用提供者(self, 能力id: str, 参数: dict | None = None) -> 结果:
        """调用已初始化提供者的最小操作；未初始化返回明确错误。"""
        实例 = self.活动实例.get(能力id)
        if 实例 is None:
            return 结果.失败(
                "外部不可访问", f"能力 {能力id} 提供者未初始化", 来源="提供者注册表"
            )
        try:
            return 实例.执行最小操作(参数)
        except Exception as 错误:
            return 结果.失败("内部错误", f"提供者调用异常: {错误}", 来源="提供者注册表")

    def 停止提供者(self, 能力id: str) -> 结果:
        """停止提供者（关闭+释放运行时状态）；重复停止幂等。"""
        实例 = self.活动实例.get(能力id)
        if 实例 is None:
            return 结果.成功结果("已停止")  # 重复停止幂等
        try:
            关闭结果 = 实例.关闭连接()
            if not 关闭结果.成功:
                return 关闭结果
        finally:
            self.活动实例.pop(能力id, None)
            self.状态表.pop(能力id, None)
        return 结果.成功结果("已停止并释放")

    def 已初始化(self, 能力id: str) -> bool:
        return 能力id in self.活动实例
