"""幂等消息支持库包级中文入口。

调用者只能从此入口导入，禁止深入 实现/ 目录。
"""

from __future__ import annotations

from 支持库.后端.幂等消息.实现.幂等消息 import 生成id
from 支持库.后端.幂等消息.实现.幂等消息 import 校验id

__all__ = [
    "生成id",
    "校验id",
]


def 注册能力(注册表) -> None:
    """由支持库加载器调用。"""
