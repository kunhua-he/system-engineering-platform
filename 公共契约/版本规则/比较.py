"""版本检查：x.y.z 版本比较、兼容性与升级方向判定。

版本语义：主版本.次版本.修订。主版本不一致视为不兼容；
升级只允许向更高版本，禁止跨主版本自动升级。
"""

from __future__ import annotations

from dataclasses import dataclass

from 公共契约.包声明 import 校验版本
from 公共契约.基础类型.逻辑类型 import 真, 假


@dataclass(frozen=True)
class 版本号:
    """三段式版本号。"""

    主: int
    次: int
    修订: int

    @classmethod
    def 解析(cls, 文本: str) -> "版本号":
        校验版本(文本)
        主, 次, 修订 = (int(部分) for 部分 in 文本.split("."))
        return cls(主=主, 次=次, 修订=修订)

    def 转文本(self) -> str:
        return f"{self.主}.{self.次}.{self.修订}"

    def __lt__(self, 其他: "版本号") -> bool:
        return (self.主, self.次, self.修订) < (其他.主, 其他.次, 其他.修订)

    def __le__(self, 其他: "版本号") -> bool:
        return (self.主, self.次, self.修订) <= (其他.主, 其他.次, 其他.修订)

    def __gt__(self, 其他: "版本号") -> bool:
        return (self.主, self.次, self.修订) > (其他.主, 其他.次, 其他.修订)

    def 兼容(self, 其他: "版本号") -> bool:
        """主版本一致即视为兼容。"""
        return self.主 == 其他.主


@dataclass(frozen=True)
class 版本判定:
    """一次版本比较的结论。"""

    当前: 版本号
    目标: 版本号
    可升级: bool
    可回滚: bool
    兼容: bool
    说明: str


def 比较版本(当前文本: str, 目标文本: str) -> 版本判定:
    """判定从当前版本到目标版本的升级/回滚/兼容性。"""
    当前 = 版本号.解析(当前文本)
    目标 = 版本号.解析(目标文本)
    if 目标 > 当前:
        说明 = "目标高于当前：允许升级"
        if 目标.主 != 当前.主:
            说明 += "，但跨主版本，需人工确认"
        return 版本判定(当前, 目标, 可升级=真, 可回滚=假, 兼容=当前.兼容(目标), 说明=说明)
    if 目标 < 当前:
        return 版本判定(当前, 目标, 可升级=假, 可回滚=真, 兼容=当前.兼容(目标), 说明="目标低于当前：仅允许回滚")
    return 版本判定(当前, 目标, 可升级=假, 可回滚=假, 兼容=真, 说明="版本一致")


def 满足约束(版本文本: str, 约束文本: str) -> bool:
    """判断版本是否满足约束（>=、>、==、<=、<；逗号分隔多约束且关系）。

    空约束（None/空串/只有逗号与空白）一律判不满足：没有可比对的约束就放行，
    会让依赖绑定校验变成恒真门禁（判据① 空跑）。调用方要表达「无约束」应在
    调用前判断，不要靠本函数兜底。
    """
    if not isinstance(约束文本, str) or not 约束文本.strip():
        return 假
    约束表 = [约束.strip() for 约束 in 约束文本.split(",") if 约束.strip()]
    if not 约束表:
        return 假
    try:
        版本 = 版本号.解析(版本文本)
    except ValueError:
        return 假
    import re as _正则

    for 约束 in 约束表:
        匹配 = _正则.match(r"^(>=|<=|==|!=|>|<)?\s*v?(\d+\.\d+\.\d+)$", 约束)
        if not 匹配:
            return 假
        运算符 = 匹配.group(1) or "=="
        目标 = 版本号.解析(匹配.group(2))
        if 运算符 == ">=" and not 版本 >= 目标:
            return 假
        if 运算符 == "<=" and not 版本 <= 目标:
            return 假
        if 运算符 == "==" and not 版本 == 目标:
            return 假
        if 运算符 == "!=" and 版本 == 目标:
            return 假
        if 运算符 == ">" and not 版本 > 目标:
            return 假
        if 运算符 == "<" and not 版本 < 目标:
            return 假
    return 真
