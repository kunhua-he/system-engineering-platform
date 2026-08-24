"""基础类型：跨包统一的结果、状态与简单类型校验。

统一结果必须至少支持：成功、值、错误码、错误说明、来源、可重试、
详细信息。成功结果不能携带失败状态；失败结果不能伪装成成功；
异常必须转换为稳定错误码和错误说明。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from 公共契约.错误结构 import 错误结构

值类型 = TypeVar("值类型")


@dataclass(frozen=True)
class 结果(Generic[值类型]):
    """统一结果：成功携带 值，失败携带 错误结构。"""

    成功: bool
    值: 值类型 | None = None
    错误: 错误结构 | None = None

    @property
    def 错误码(self) -> str:
        return self.错误.错误码 if self.错误 else ""

    @property
    def 错误说明(self) -> str:
        return self.错误.消息 if self.错误 else ""

    @property
    def 来源(self) -> str:
        return self.错误.来源 if self.错误 else ""

    @property
    def 可重试(self) -> bool:
        return self.错误.可重试 if self.错误 else False

    @property
    def 详细信息(self) -> dict[str, Any]:
        return self.错误.详情 if self.错误 else {}

    @classmethod
    def 成功结果(cls, 值: 值类型 | None = None) -> "结果[值类型]":
        return cls(成功=True, 值=值)

    @classmethod
    def 失败结果(cls, 错误: 错误结构) -> "结果[值类型]":
        return cls(成功=False, 错误=错误)

    @classmethod
    def 失败(
        cls,
        错误码: str,
        消息: str,
        *,
        来源: str = "",
        可恢复: bool = False,
        可重试: bool = False,
        详情: dict[str, Any] | None = None,
    ) -> "结果[值类型]":
        return cls(
            成功=False,
            错误=错误结构(
                错误码=错误码,
                消息=消息,
                来源=来源,
                可恢复=可恢复,
                可重试=可重试,
                详情=详情 or {},
            ),
        )

    def 转字典(self) -> dict[str, Any]:
        return {
            "成功": self.成功,
            "值": self.值,
            "错误": self.错误.转字典() if self.错误 else None,
        }

    def 确保成功(self) -> 值类型:
        """失败时抛 ValueError（把结果转异常，供上层异常边界使用）。"""
        if not self.成功:
            raise ValueError(f"{self.错误码}: {self.错误说明}")
        return self.值


def 确保文本(值: Any, 名称: str) -> str:
    """校验值必须为非空文本。"""
    if not isinstance(值, str) or not 值.strip():
        raise TypeError(f"{名称} 必须是非空文本")
    return 值


def 确保整数(值: Any, 名称: str, *, 最小值: int | None = None) -> int:
    """校验值必须为整数（可带最小值约束）。"""
    if not isinstance(值, int) or isinstance(值, bool):
        raise TypeError(f"{名称} 必须是整数")
    if 最小值 is not None and 值 < 最小值:
        raise ValueError(f"{名称} 不得小于 {最小值}")
    return 值


def 确保布尔(值: Any, 名称: str) -> bool:
    """校验值必须为布尔。"""
    if not isinstance(值, bool):
        raise TypeError(f"{名称} 必须是布尔")
    return 值
