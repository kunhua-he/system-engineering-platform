"""环境变量原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：环境变量读/写/删/列（参考易语言系统核心支持库）。
纯标准库 os.environ，不做业务逻辑。
"""

from __future__ import annotations

import os

from 公共契约.基础类型.结果类型 import 结果


def 获取环境变量(名称: str = None) -> 结果:
    """获取环境变量。返回 {名称, 值, 存在}。"""
    if not isinstance(名称, str) or not 名称.strip():
        return 结果.失败("参数不合法", "名称必须是非空字符串", 来源="环境变量")
    名称 = 名称.strip()
    if 名称 not in os.environ:
        return 结果.成功结果({"名称": 名称, "值": None, "存在": False})
    return 结果.成功结果({"名称": 名称, "值": os.environ[名称], "存在": True})


def 设置环境变量(名称: str = None, 值: str = None) -> 结果:
    """设置环境变量（进程内）。返回 {名称, 值}。"""
    if not isinstance(名称, str) or not 名称.strip():
        return 结果.失败("参数不合法", "名称必须是非空字符串", 来源="环境变量")
    if 值 is None:
        return 结果.失败("参数不合法", "值不能为空", 来源="环境变量")
    名称 = 名称.strip()
    os.environ[名称] = str(值)
    return 结果.成功结果({"名称": 名称, "值": str(值), "说明": "仅对当前进程生效"})


def 删除环境变量(名称: str = None) -> 结果:
    """删除环境变量。返回 {名称, 已删除}。"""
    if not isinstance(名称, str) or not 名称.strip():
        return 结果.失败("参数不合法", "名称必须是非空字符串", 来源="环境变量")
    名称 = 名称.strip()
    已删除 = 名称 in os.environ
    if 已删除:
        os.environ.pop(名称, None)
    return 结果.成功结果({"名称": 名称, "已删除": 已删除})


def 列出环境变量(前缀: str = None) -> 结果:
    """列出环境变量（可过滤前缀）。返回 {数量, 变量列表}。"""
    前缀 = (前缀 or "").strip()
    变量列表 = [{"名称": 键, "值": 值} for 键, 值 in os.environ.items()
               if not 前缀 or 键.startswith(前缀)]
    return 结果.成功结果({"数量": len(变量列表), "变量列表": 变量列表})
