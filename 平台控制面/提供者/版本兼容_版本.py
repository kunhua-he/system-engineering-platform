"""核心双版本状态兼容·版本比较工具（无依赖，防循环导入）。"""
from __future__ import annotations

from 运行核心.权威状态 import 版本元组


def 解析兼容范围(范围: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """"1.0.0-1.4.0" → ((1,0,0), (1,4,0))；版本比较必须用元组，禁止字符串字典序。"""
    低, 高 = 范围.split("-")
    return 版本元组(低.strip()), 版本元组(高.strip())


def 版本在范围内(版本: str, 范围: str) -> bool:
    """版本是否落在 兼容范围 "低-高" 内；范围格式非法视为不兼容（安全默认：阻止）。"""
    try:
        低, 高 = 解析兼容范围(范围)
        return 低 <= 版本元组(版本) <= 高
    except (ValueError, TypeError):
        return False
