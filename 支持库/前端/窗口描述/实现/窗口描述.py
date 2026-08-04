"""前端描述模型实现（不对外暴露，只经包级中文入口调用）。

对外只返回统一结果：成功时 值 内放结构化描述数据，失败返回 结果.失败，
不泄漏任何内部对象；参数非法显式返回失败，不抛异常。
"""

from __future__ import annotations

import json as _json
from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="窗口描述")


def _是正整数(值: Any) -> bool:
    return isinstance(值, int) and not isinstance(值, bool) and 值 > 0


def 创建窗口定义(窗口id: str, 标题: str, 宽度: int, 高度: int) -> 结果:
    if not isinstance(窗口id, str) or not 窗口id:
        return _失败("参数不合法", "窗口id 必须为非空文本")
    if not isinstance(标题, str) or not 标题:
        return _失败("参数不合法", "标题必须为非空文本")
    if not _是正整数(宽度):
        return _失败("参数不合法", "宽度必须为正整数")
    if not _是正整数(高度):
        return _失败("参数不合法", "高度必须为正整数")
    return _成功({
        "窗口id": 窗口id, "标题": 标题, "宽度": 宽度, "高度": 高度,
        "组件列表": [], "可调整大小": True, "模态": False,
    })


def 校验窗口定义(窗口定义: dict) -> 结果:
    if not isinstance(窗口定义, dict):
        return _失败("参数不合法", "窗口定义必须是字典")
    必填 = ("窗口id", "标题", "宽度", "高度", "组件列表")
    for 字段 in 必填:
        if 字段 not in 窗口定义:
            return _失败("参数不合法", f"窗口定义缺少字段: {字段}")
    if not _是正整数(窗口定义["宽度"]):
        return _失败("参数不合法", "宽度必须为正整数")
    if not _是正整数(窗口定义["高度"]):
        return _失败("参数不合法", "高度必须为正整数")
    if not isinstance(窗口定义["组件列表"], list):
        return _失败("参数不合法", "组件列表必须是列表")
    return _成功(True)


def 序列化窗口定义(窗口定义: dict) -> 结果:
    if not isinstance(窗口定义, dict):
        return _失败("参数不合法", "窗口定义必须是字典")
    return _成功(_json.dumps(窗口定义, ensure_ascii=False, indent=2))


def 反序列化窗口定义(文本: str) -> 结果:
    if not isinstance(文本, str) or not 文本:
        return _失败("参数不合法", "文本必须为非空文本")
    try:
        数据 = _json.loads(文本)
    except (_json.JSONDecodeError, TypeError) as 错误:
        return _失败("反序列化失败", f"窗口定义解析失败: {错误}")
    校验结果 = 校验窗口定义(数据)
    if not 校验结果.成功:
        return _失败("反序列化失败", "还原后的窗口定义校验不通过")
    return _成功(数据)
