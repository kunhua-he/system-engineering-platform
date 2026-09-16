"""动态库提供者的能力实现层（能力边界，统一结果契约）。"""
from __future__ import annotations

from typing import Any

from 平台控制面.提供者.动态库提供者.动态库实现 import (
    调用 as 动态库调用,
    可用库列表 as 探测可用库表,
    宿主可用性 as 探测宿主可用性,
)

来源名称 = "动态库提供者"


def 调用动态库(库名: str = "", 函数名: str = "", 参数表: list | None = None) -> Any:
    """真实加载动态库并真实调用函数；失败按 HOST_UNAVAILABLE 等稳定错误码透传，不伪装成功。"""
    from 公共契约.基础类型.结果类型 import 结果

    if not 库名 or not 函数名:
        return 结果.失败("参数不合法", "库名与函数名必须给齐", 来源=来源名称)
    if 参数表 is None:
        参数表 = []
    if not isinstance(参数表, (list, tuple)):
        return 结果.失败("参数不合法", "参数表必须是列表", 来源=来源名称)
    return 动态库调用(库名, 函数名, list(参数表))


def 可用库列表() -> Any:
    """真实探测已知系统库：返回库名/真实路径/可用状态；不可用状态为 HOST_UNAVAILABLE。"""
    from 公共契约.基础类型.结果类型 import 结果

    return 结果.成功结果({"库表": 探测可用库表()})


def 宿主可用性() -> Any:
    """探测当前宿主能否真实提供动态库调用；不可用时状态为 HOST_UNAVAILABLE。"""
    from 公共契约.基础类型.结果类型 import 结果

    return 结果.成功结果(探测宿主可用性())
