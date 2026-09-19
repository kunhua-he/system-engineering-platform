"""基础类型：跨包统一的结果、状态与简单类型校验。

统一结果必须至少支持：成功、值、错误码、错误说明、来源、可重试、
详细信息。成功结果不能携带失败状态；失败结果不能伪装成成功；
异常必须转换为稳定错误码和错误说明。

**`结果型` 的两个曾用名（2026-09-19 E-8 收口）**：

- 判定层：`校验结果类型` / `确保结果类型` 收口在本文件（**类型判定的唯一真源**）。
  收口前它只是网关 `类型匹配表` 里的一个私有 helper，公共契约里没有可复用层；
  而 `结果型` 是全平台**返回类型位第二高**的正式类型（现场实测 564 处 /
  16 包 701 能力里的绝大多数能力返回）。
- 信封内 `值` 的类型与 `结果` 自身是**两条轴**：`值` 必须由契约的
  `返回.值结构` 单独声明真实数据类型（铁律：信封不为「值是什么」背书）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from 公共契约.错误结构 import 错误结构
from 公共契约.基础类型.逻辑类型 import 真, 假

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
        return self.错误.可重试 if self.错误 else 假

    @property
    def 详细信息(self) -> dict[str, Any]:
        return self.错误.详情 if self.错误 else {}

    @classmethod
    def 成功结果(cls, 值: 值类型 | None = None) -> "结果[值类型]":
        return cls(成功=真, 值=值)

    @classmethod
    def 失败结果(cls, 错误: 错误结构) -> "结果[值类型]":
        return cls(成功=假, 错误=错误)

    @classmethod
    def 失败(
        cls,
        错误码: str,
        消息: str,
        *,
        来源: str = "",
        可恢复: bool = 假,
        可重试: bool = 假,
        详情: dict[str, Any] | None = None,
    ) -> "结果[值类型]":
        return cls(
            成功=假,
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
    """校验值必须为非空文本。

    **不重复判定边界**：是否「文本型」由唯一真源 `校验文本类型` 定（本函数只加
    「非空」这层业务限制，业务限制不属于类型边界）。
    """
    from 公共契约.基础类型.文本类型 import 校验文本类型
    if not 校验文本类型(值) or not 值.strip():
        raise TypeError(f"{名称} 必须是非空文本")
    return 值


def 确保整数(值: Any, 名称: str, *, 最小值: int | None = None) -> int:
    """校验值必须为整数（可带最小值约束）。

    **不重复判定边界**：64 位边界与「布尔不算整数」由唯一真源
    `公共契约/基础类型/数值类型.py:确保数值类型` 定（本函数只加最小值这层业务限制）。
    """
    from 公共契约.基础类型.数值类型 import 确保数值类型
    try:
        确保数值类型(值, "整数型")
    except (TypeError, ValueError) as 错误:
        raise TypeError(f"{名称} 必须是整数") from 错误
    if 最小值 is not None and 值 < 最小值:
        raise ValueError(f"{名称} 不得小于 {最小值}")
    return 值


def 确保布尔(值: Any, 名称: str) -> bool:
    """校验值必须为布尔。

    **不重复判定边界**：委托唯一真源 `公共契约/基础类型/逻辑类型.py:确保逻辑类型`。
    """
    from 公共契约.基础类型.逻辑类型 import 确保逻辑类型
    try:
        确保逻辑类型(值)
    except TypeError as 错误:
        raise TypeError(f"{名称} 必须是布尔") from 错误
    return 值


def 校验结果类型(值: Any) -> bool:
    """严格校验值是否为 `结果型`（统一成功／失败信封）：至少带布尔 ``成功`` 字段。

    **`结果型` 判定的唯一真源**（2026-09-19 E-8 收口；收口前该判定只存在于网关
    `类型匹配表` 的私有 helper `_是结果值`，公共契约里没有可复用层）。

    判据与网关 JSON 边界逐项同强度：
    - 必须是 `dict`：结果跨网络只以字典形态到达（进程内是 `结果` 数据类实例，
      由调用方在边界前转字典）；
    - 必须有 `成功` 且其值是真 `bool`（`1`／`"true"` 不算——见铁律「`逻辑型` 是
      真正 bool」）。

    **相对安全（哲学第 9 条 9.5）**：只保证「是信封」——不校验 `成功=真` 时
    `错误` 为空、`成功=假` 时 `错误码` 非空等一致性（那由 `结果` 类自身的构造
    与 `确保成功` 保证），也不校验信封内 `值` 的类型（那是契约 `返回.值结构`
    的轴，本函数不越权）。
    """
    return isinstance(值, dict) and isinstance(值.get("成功"), bool)


def 确保结果类型(值: Any) -> dict:
    """校验并返回 `结果型`；不符合时抛稳定的 ``TypeError``。"""
    if not isinstance(值, dict):
        raise TypeError(f"值不符合结果型契约：{值!r}（结果型是字典形态的信封）")
    if not isinstance(值.get("成功"), bool):
        raise TypeError(
            f"值不符合结果型契约：{值!r}"
            "（信封必须带布尔 成功 字段；1／\"true\" 不算逻辑型）"
        )
    return 值


__all__ = [
    "结果", "确保文本", "确保整数", "确保布尔",
    "校验结果类型", "确保结果类型",
]
