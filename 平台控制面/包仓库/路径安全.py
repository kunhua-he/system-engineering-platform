"""路径安全：制品内相对路径校验与规范化（包仓库共用）。"""

from __future__ import annotations


def 规范化相对路径(路径: str) -> str:
    """校验并规范化制品内相对路径；非法路径抛 ValueError。"""
    if not 路径 or 路径 in (".", "/", "\\"):
        raise ValueError(f"空或根路径不允许: {路径!r}")
    if 路径.startswith("/") or 路径.startswith("\\") or 路径[1:2] == ":":
        raise ValueError(f"绝对路径不允许: {路径!r}")
    if any(段 in ("..", ".") for 段 in 路径.replace("\\", "/").split("/")):
        raise ValueError(f"路径逃逸不允许: {路径!r}")
    if "\\" in 路径:
        raise ValueError(f"反斜杠分隔符不允许: {路径!r}")
    return 路径
