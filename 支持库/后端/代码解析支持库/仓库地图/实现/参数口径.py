"""仓库地图入参口径：类型不符、缺必填、枚举不认识一律 `参数不合法`（纯函数，无副作用）。

与 代码地图.参数口径 同形，但不复用它：跨包只许走对方**包级公开入口**，
且它没有本包需要的「自由文本列表」形态（排除目录/锚点不是枚举）。
"""

from __future__ import annotations

from typing import Any


class 参数错误(Exception):
    """入参不合契约：携带统一错误码与点名说明。"""

    def __init__(self, 说明: str, 错误码: str = "参数不合法") -> None:
        super().__init__(说明)
        self.错误码 = 错误码
        self.说明 = 说明


def 取文本(参数名: str, 值: Any, *, 必填: bool, 默认: str = "") -> str:
    """取文本参数：非文本拒绝；必填缺省拒绝；空串按缺省处理。"""
    if 值 is None or (isinstance(值, str) and not 值.strip()):
        if 必填:
            raise 参数错误(f"缺少必填参数 {参数名}（类型 文本型）")
        return 默认
    if not isinstance(值, str):
        raise 参数错误(f"参数 {参数名} 类型不符（期望 文本型，实际 {type(值).__name__}）")
    return 值.strip()


def 取整数(参数名: str, 值: Any, *, 默认: int, 最小: int, 最大: int) -> int:
    """取整数参数：逻辑型不算整数；越界拒绝。"""
    if 值 is None:
        return 默认
    if isinstance(值, bool) or not isinstance(值, int):
        raise 参数错误(f"参数 {参数名} 类型不符（期望 整数型，实际 {type(值).__name__}）")
    if not 最小 <= 值 <= 最大:
        raise 参数错误(f"参数 {参数名} 超出范围（{最小}~{最大}，实际 {值}）")
    return 值


def 取文本列表(参数名: str, 值: Any) -> list[str]:
    """取自由文本列表：非列表拒绝，元素必须是非空文本（不做枚举收窄）。"""
    if 值 is None:
        return []
    if not isinstance(值, list):
        raise 参数错误(f"参数 {参数名} 类型不符（期望 列表型，实际 {type(值).__name__}）")
    结果表 = []
    for 元素 in 值:
        if not isinstance(元素, str) or not 元素.strip():
            raise 参数错误(f"参数 {参数名} 含非法元素 {元素!r}（期望非空文本）")
        结果表.append(元素.strip())
    return 结果表


def 取枚举列表(参数名: str, 值: Any, *, 允许值: tuple[str, ...]) -> list[str]:
    """取枚举列表：元素不在允许值表内拒绝（fail-closed）。"""
    取值表 = 取文本列表(参数名, 值)
    for 元素 in 取值表:
        if 元素 not in 允许值:
            raise 参数错误(
                f"参数 {参数名} 含不认识的值 {元素!r}（允许值：{'、'.join(允许值)}）"
            )
    return 取值表
