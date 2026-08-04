"""前端描述模型实现（不对外暴露，只经包级中文入口调用）。

对外只返回统一结果：成功时 值 内放结构化描述数据，失败返回 结果.失败，
不泄漏任何内部对象；参数非法显式返回失败，不抛异常。
"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="资源描述")


def 创建资源描述(资源id: str, 资源类型: str, 来源: str) -> 结果:
    if not isinstance(资源id, str) or not 资源id:
        return _失败("参数不合法", "资源id 必须为非空文本")
    if not isinstance(资源类型, str) or not 资源类型:
        return _失败("参数不合法", "资源类型必须为非空文本")
    if 来源 is None:
        来源 = ""
    if not isinstance(来源, str):
        return _失败("参数不合法", "来源必须是文本")
    return _成功({"资源id": 资源id, "资源类型": 资源类型, "来源": 来源, "引用计数": 0})


def 校验资源引用(资源描述: dict) -> 结果:
    if not isinstance(资源描述, dict):
        return _失败("参数不合法", "资源描述必须是字典")
    必填 = ("资源id", "资源类型", "来源")
    for 字段 in 必填:
        if 字段 not in 资源描述 or not 资源描述[字段]:
            return _失败("资源引用不完整", f"资源描述缺少字段: {字段}")
    return _成功(True)
