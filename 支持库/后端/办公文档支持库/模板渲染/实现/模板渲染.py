"""模板渲染原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：用简单占位符语法渲染文本模板（借鉴 Coze Prompt 变量层思路，但保持原子）。
语法：{{变量名}} 替换；未知变量按 缺失行为（保留原文/替换为空/报错）处理。
只做文本替换，不做业务逻辑；不依赖第三方库。
"""

from __future__ import annotations

import re

from 公共契约.基础类型.结果类型 import 结果

_占位符 = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def 渲染模板(模板: str = None, 变量: dict = None, 缺失行为: str = None) -> 结果:
    """渲染模板。变量 为 {名称: 值}；缺失行为 ∈ 保留原文/替换为空/报错（默认 保留原文）。"""
    if not isinstance(模板, str):
        return 结果.失败("参数不合法", "模板必须是非空字符串", 来源="模板渲染")
    变量表 = dict(变量 or {})
    行为 = (缺失行为 or "保留原文").strip()
    if 行为 not in ("保留原文", "替换为空", "报错"):
        return 结果.失败("参数不合法", f"缺失行为必须是 保留原文/替换为空/报错: {缺失行为}", 来源="模板渲染")

    def _替换(match: re.Match) -> str:
        名称 = match.group(1).strip()
        if 名称 in 变量表:
            值 = 变量表[名称]
            return str(值) if 值 is not None else ""
        if 行为 == "替换为空":
            return ""
        if 行为 == "报错":
            raise ValueError(f"模板变量缺失: {名称}")
        return match.group(0)

    try:
        结果文本 = _占位符.sub(_替换, 模板)
    except ValueError as 错误:
        return 结果.失败("变量缺失", str(错误), 来源="模板渲染")
    return 结果.成功结果({"渲染结果": 结果文本, "变量数": len(变量表)})


def 提取变量名(模板: str = None) -> 结果:
    """提取模板中出现的全部变量名（去重保序）。"""
    if not isinstance(模板, str):
        return 结果.失败("参数不合法", "模板必须是非空字符串", 来源="模板渲染")
    名称表 = []
    已见 = set()
    for match in _占位符.finditer(模板):
        名称 = match.group(1).strip()
        if 名称 not in 已见:
            已见.add(名称)
            名称表.append(名称)
    return 结果.成功结果({"变量名列表": 名称表})
