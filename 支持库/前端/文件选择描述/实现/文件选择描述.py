"""前端描述模型实现（不对外暴露，只经包级中文入口调用）。"""

from __future__ import annotations

import json as _json
from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="文件选择描述")


def 创建文件选择描述(允许扩展名列表: list, 多选: bool = False) -> 结果:
    if not isinstance(允许扩展名列表, list):
        return _失败("参数不合法", "允许扩展名列表必须是列表")
    return _成功({
        "允许扩展名列表": list(允许扩展名列表),
        "多选": bool(多选),
        "起始目录": "",
    })


def 校验文件选择描述(文件选择描述: dict) -> 结果:
    if not isinstance(文件选择描述, dict):
        return _失败("参数不合法", "文件选择描述必须是字典")
    必填 = ("允许扩展名列表", "多选")
    for 字段 in 必填:
        if 字段 not in 文件选择描述:
            return _失败("参数不合法", f"文件选择描述缺少字段: {字段}")
    if not isinstance(文件选择描述["允许扩展名列表"], list):
        return _失败("参数不合法", "允许扩展名列表必须是列表")
    return _成功(True)
