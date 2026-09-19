"""判定助手：统一结果信封判定 + 实现失败语义错误码提取（组件合规测试包拆分件）。

**判据唯一事实源**：统一结果结构（成功/错误码/错误/可重试）以
`公共契约/基础类型/结果类型.py` 为唯一事实源；本模块只**读取与自洽性判定**
（成功不得携带失败结构、失败必须带稳定错误码），不另立口径。
「无失败路径的能力空错误码合法」是失败语义场景的既有判据，`_提取函数错误码` 是它的实现腿。

本模块**只做代码搬家**，成员名/签名/默认值/正则与解析口径与拆分前逐字一致
（拆分前 blob 冻结于 `/tmp/拆分基线/合规测试包.py`，sha256 前16=`daa8fd30a0565f33`）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _成功标志(返回值: Any) -> bool | None:
    """提取统一结果的成功标志：dict 取 成功 键、对象取 成功 属性。

    非统一结果（普通业务数据）没有该标志，返回 None，调用方据此退化为
    “只看是否为空”的判据，与成功/失败两条路径保持同一口径。
    """
    if isinstance(返回值, dict):
        return bool(返回值["成功"]) if "成功" in 返回值 else None
    if hasattr(返回值, "成功"):
        return bool(返回值.成功)
    return None


def _统一结果错误码(返回值: Any) -> str:
    """提取统一结果的错误码（dict 取 错误码 键、对象取 错误码 属性）。"""
    if isinstance(返回值, dict):
        return str(返回值.get("错误码") or "")
    return str(getattr(返回值, "错误码", "") or "")


def _携带失败结构(返回值: Any) -> bool:
    """自称成功的统一结果是否携带失败结构（错误 或 错误码 非空）。"""
    if isinstance(返回值, dict):
        return bool(返回值.get("错误")) or bool(返回值.get("错误码"))
    return bool(getattr(返回值, "错误", None)) or bool(getattr(返回值, "错误码", ""))

def _提取函数错误码(实现目录: Path, 函数名: str) -> list[str]:
    """按函数名定位实现函数体，提取统一失败结果中的错误码。

    用于失败语义精确判定：实现有失败路径的能力必须声明对应错误码；
    实现无失败路径（纯查询/纯计算）的能力空错误码合法。
    """
    错误码: list[str] = []
    if not 实现目录.is_dir():
        return 错误码
    for 文件 in 实现目录.rglob("*.py"):
        try:
            内容 = 文件.read_text(encoding="utf-8")
        except Exception:
            continue
        模式 = re.compile(r"def\s+" + re.escape(函数名) + r"\s*\(.*?\n(.*?)(?=\ndef\s+|\Z)", re.S)
        匹配 = 模式.search(内容)
        if not 匹配:
            continue
        函数体 = 匹配.group(1)
        for m in re.findall(r'结果\.失败\(\s*["\']([^"\']+)["\']', 函数体):
            if m not in 错误码:
                错误码.append(m)
        # 兼容统一结果的字典返回写法：
        # {"成功": False, "错误码": "参数不合法"}。
        if re.search(r'["\']成功["\']\s*:\s*False', 函数体):
            for m in re.findall(r'["\']错误码["\']\s*:\s*["\']([^"\']+)["\']', 函数体):
                if m not in 错误码:
                    错误码.append(m)
        if 错误码:
            break
    return 错误码
