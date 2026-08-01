"""原子能力实现（不对外暴露，只经包级中文入口调用）。"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="数据交换")


import csv
import io
import json


def 序列化JSON(数据: Any) -> 结果:
    try:
        return _成功(json.dumps(数据, ensure_ascii=False, indent=2))
    except (TypeError, ValueError) as 错误:
        return _失败("序列化失败", f"JSON 序列化失败: {错误}")


def 反序列化JSON(文本: str) -> 结果:
    try:
        return _成功(json.loads(文本))
    except (json.JSONDecodeError, TypeError) as 错误:
        return _失败("反序列化失败", f"JSON 解析失败: {错误}")


def 序列化CSV(行列表: list) -> 结果:
    try:
        缓冲区 = io.StringIO()
        写入器 = csv.writer(缓冲区)
        写入器.writerows(行列表)
        return _成功(缓冲区.getvalue())
    except (csv.Error, TypeError) as 错误:
        return _失败("序列化失败", f"CSV 序列化失败: {错误}")


def 反序列化CSV(文本: str) -> 结果:
    try:
        读取器 = csv.reader(io.StringIO(文本))
        return _成功([行 for 行 in 读取器])
    except csv.Error as 错误:
        return _失败("反序列化失败", f"CSV 解析失败: {错误}")
