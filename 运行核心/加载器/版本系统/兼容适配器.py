"""兼容适配器：旧模块调用新支持库（或反之）的参数/返回/错误码转换。

适配器只允许：参数名称转换、参数结构转换、返回值转换、错误码转换、
旧行为兼容、版本兼容提示。
禁止：添加新业务流程、直接读取私有实现、绕过能力注册表、永久保留
无引用适配器、隐藏不兼容问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class 适配器声明:
    """一份兼容适配器声明。"""

    适配器id: str
    来源契约版本: str
    目标契约版本: str
    支持范围: str = "全部能力"
    弃用时间: str = ""
    验证场景: str = ""

    def 转字典(self) -> dict[str, Any]:
        return {
            "适配器id": self.适配器id,
            "来源契约版本": self.来源契约版本,
            "目标契约版本": self.目标契约版本,
            "支持范围": self.支持范围,
            "弃用时间": self.弃用时间,
            "验证场景": self.验证场景,
        }


class 兼容适配器:
    """适配器实例：注册转换函数、执行参数/返回值/错误码转换。"""

    def __init__(self, 声明: 适配器声明) -> None:
        self.声明 = 声明
        self.参数转换表: dict[str, Callable[[dict], dict]] = {}
        self.返回转换表: dict[str, Callable[[Any], Any]] = {}
        self.错误码转换表: dict[str, str] = {}

    def 注册参数转换(self, 能力id: str, 转换函数: Callable[[dict], dict]) -> None:
        self.参数转换表[能力id] = 转换函数

    def 注册返回转换(self, 能力id: str, 转换函数: Callable[[Any], Any]) -> None:
        self.返回转换表[能力id] = 转换函数

    def 注册错误码转换(self, 来源错误码: str, 目标错误码: str) -> None:
        self.错误码转换表[来源错误码] = 目标错误码

    def 转换参数(self, 能力id: str, 参数: dict[str, Any]) -> dict[str, Any]:
        """参数名称/结构转换；无转换函数时原样返回。"""
        转换函数 = self.参数转换表.get(能力id)
        if 转换函数 is None:
            return dict(参数)
        return 转换函数(参数)

    def 转换返回(self, 能力id: str, 值: Any) -> Any:
        转换函数 = self.返回转换表.get(能力id)
        if 转换函数 is None:
            return 值
        return 转换函数(值)

    def 转换错误码(self, 来源错误码: str) -> str:
        return self.错误码转换表.get(来源错误码, 来源错误码)

    def 适用于(self, 来源版本: str, 目标版本: str) -> bool:
        """是否适用于 来源版本 → 目标版本。"""
        return self.声明.来源契约版本 == 来源版本 and self.声明.目标契约版本 == 目标版本
