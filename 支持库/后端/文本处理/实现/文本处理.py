"""原子能力实现（不对外暴露，只经包级中文入口调用）。"""

from __future__ import annotations

from typing import Any

from 公共契约.基础类型.结果类型 import 结果


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="文本处理")


def 分割文本(文本: str, 分隔符: str) -> 结果:
    if not isinstance(文本, str):
        return _失败("参数不合法", "文本必须为字符串")
    return _成功(文本.split(分隔符))


def 合并文本(片段列表: list, 分隔符: str) -> 结果:
    return _成功(分隔符.join(str(片段) for 片段 in 片段列表))


def 替换文本(文本: str, 旧文本: str, 新文本: str) -> 结果:
    if 旧文本 == "":
        return _失败("参数不合法", "旧文本不能为空")
    return _成功(文本.replace(旧文本, 新文本))


def 查找文本(文本: str, 目标: str) -> 结果:
    return _成功(文本.find(目标))


def 去空白(文本: str) -> 结果:
    return _成功(文本.strip())


def 转大写(文本: str) -> 结果:
    return _成功(文本.upper())


def 转小写(文本: str) -> 结果:
    return _成功(文本.lower())


def 统计长度(文本: str) -> 结果:
    return _成功(len(文本))


def 按行分割(文本: str) -> 结果:
    return _成功(文本.splitlines())
