"""前端描述模型实现（不对外暴露，只经包级中文入口调用）。"""

from __future__ import annotations

import json as _json
from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="基础组件描述")


def 创建组件定义(组件id: str, 组件类型: str, 属性: dict) -> 结果:
    if not 组件id or not 组件类型:
        return _失败("参数不合法", "组件id 与组件类型不能为空")
    return _成功({
        "组件id": 组件id, "组件类型": 组件类型,
        "属性": dict(属性 or {}), "事件列表": [],
    })


def 校验组件属性(组件定义: dict) -> 结果:
    if not isinstance(组件定义, dict):
        return _失败("参数不合法", "组件定义必须是字典")
    必填 = ("组件id", "组件类型", "属性")
    for 字段 in 必填:
        if 字段 not in 组件定义:
            return _失败("参数不合法", f"组件定义缺少字段: {字段}")
    if not isinstance(组件定义["属性"], dict):
        return _失败("参数不合法", "组件属性必须是字典")
    return _成功(True)


def 声明事件(组件定义: dict, 事件名称: str) -> 结果:
    if not 事件名称:
        return _失败("参数不合法", "事件名称不能为空")
    新定义 = dict(组件定义)
    事件列表 = list(新定义.get("事件列表") or [])
    if 事件名称 not in 事件列表:
        事件列表.append(事件名称)
    新定义["事件列表"] = 事件列表
    return _成功(新定义)
