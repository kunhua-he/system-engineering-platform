"""本地应用监听端口策略。

4780 是宿主机代理端口，只能作为出站代理使用，任何项目服务都不得监听。
"""

from __future__ import annotations


代理保留端口 = frozenset({4780})


def 校验应用监听端口(端口: int) -> None:
    """拒绝把应用服务绑定到宿主代理端口或非法端口。"""
    端口 = int(端口)
    if 端口 in 代理保留端口:
        raise ValueError(f"端口 {端口} 是宿主代理保留端口，应用服务不得监听")
    if not 0 <= 端口 <= 65535:
        raise ValueError(f"端口超出范围: {端口}")
