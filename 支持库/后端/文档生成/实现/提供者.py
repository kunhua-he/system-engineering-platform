"""第三方提供者探测：各格式生成库的可用性与版本。

- docx: python-docx
- xlsx: openpyxl
- pptx: python-pptx
- pdf:  reportlab
缺库时 提供者可用 返回 False，由上层转为 错误码“提供者不可用”。
"""

from __future__ import annotations

import importlib

提供者库表 = {
    "docx": ("docx", "python-docx"),
    "xlsx": ("openpyxl", "openpyxl"),
    "pptx": ("pptx", "python-pptx"),
    "pdf": ("reportlab", "reportlab"),
}


def 提供者可用(格式: str) -> bool:
    """判断指定格式的生成库是否可导入。"""
    模块名, _ = 提供者库表.get(格式, ("", ""))
    if not 模块名:
        return False
    try:
        importlib.import_module(模块名)
        return True
    except Exception:
        return False


def 提供者版本(格式: str) -> dict[str, str]:
    """返回指定格式生成库的版本字典（库名: 版本）。"""
    模块名, 库名 = 提供者库表.get(格式, ("", ""))
    if not 模块名:
        return {}
    try:
        模块 = importlib.import_module(模块名)
        版本 = getattr(模块, "__version__", None) or getattr(模块, "Version", "未知")
        return {库名: str(版本)}
    except Exception:
        return {}
