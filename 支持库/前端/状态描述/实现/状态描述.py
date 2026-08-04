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
    return 结果.失败(错误码, 消息, 来源="状态描述")


_合法状态集合 = {"关闭", "打开", "最小化", "最大化"}

_允许流转表 = {
    "关闭": {"打开"},
    "打开": {"关闭", "最小化", "最大化"},
    "最小化": {"打开", "关闭"},
    "最大化": {"打开", "关闭"},
}


def 创建窗口状态(窗口id: str, 初始状态: str = "关闭") -> 结果:
    if not isinstance(窗口id, str) or not 窗口id:
        return _失败("参数不合法", "窗口id 必须为非空文本")
    if not isinstance(初始状态, str) or 初始状态 not in _合法状态集合:
        return _失败("参数不合法", f"初始状态不合法: {初始状态}")
    return _成功({"窗口id": 窗口id, "状态": 初始状态, "流转记录": []})


def 状态流转校验(当前状态: str, 目标状态: str) -> 结果:
    if not isinstance(当前状态, str) or 当前状态 not in _合法状态集合:
        return _失败("参数不合法", "当前状态必须在合法集合内")
    if not isinstance(目标状态, str) or 目标状态 not in _合法状态集合:
        return _失败("参数不合法", "目标状态必须在合法集合内")
    if 目标状态 in _允许流转表.get(当前状态, set()):
        return _成功(True)
    return _失败("状态流转不合法", f"不允许从 {当前状态} 流转到 {目标状态}")
