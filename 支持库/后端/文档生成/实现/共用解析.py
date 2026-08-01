"""文档生成共用解析：内容块字段中文兼容提取与表格数据标准化。

内容块字段同时兼容中文键（类型/文本/级别）与英文键（type/text/level），
供 DOCX/XLSX/PPTX/PDF 生成器复用。
"""

from __future__ import annotations


def 取类型(块: dict, 默认值: str = "段落") -> str:
    """取块类型，统一小写；中文类型名映射为内部类型。"""
    类型值 = str(
        块.get("类型") or 块.get("type") or 默认值
    ).lower()
    映射表 = {
        "标题": "标题", "heading": "标题", "head": "标题",
        "h1": "标题", "h2": "标题", "h3": "标题", "h4": "标题",
        "段落": "段落", "paragraph": "段落", "文本": "段落",
        "textbox": "段落", "列出": "段落", "code": "段落",
        "表格": "表格", "table": "表格",
        "分页": "分页", "page_break": "分页", "pagebreak": "分页",
    }
    return 映射表.get(类型值, "段落")


def 取文本(块: dict) -> str:
    """取块文本；支持 块.文本 / 块.data.文本 / 块.text。"""
    数据 = 块.get("data") if isinstance(块.get("data"), dict) else {}
    for 键 in ("文本", "text", "标题", "title", "name", "value"):
        if 键 in 块 and 块[键] is not None:
            return str(块[键])
    for 键 in ("文本", "text", "标题", "title", "name", "value"):
        if 键 in 数据 and 数据[键] is not None:
            return str(数据[键])
    return ""


def 取级别(块: dict) -> int:
    """取标题级别，默认 1。"""
    原始值 = 块.get("级别") or 块.get("level") or 1
    if isinstance(块.get("data"), dict):
        原始值 = 原始值 or 块["data"].get("level", 1)
    try:
        return int(原始值 or 1)
    except (TypeError, ValueError):
        return 1


def 取单元格文本(值) -> str:
    """把单元格值转为文本；字典取 文本/text/标注/value/name 键。"""
    if isinstance(值, dict):
        for 键 in ("文本", "text", "标注", "value", "name"):
            if 键 in 值 and 值[键] is not None:
                return str(值[键])
        return str(值)
    return "" if 值 is None else str(值)


def 标准化行(行, 表头: list) -> list[str]:
    """行数据（dict/list/标量）按表头顺序转为文本行。"""
    if isinstance(行, dict):
        if 表头:
            return [取单元格文本(行.get(表头单元格)) for 表头单元格 in 表头]
        return [取单元格文本(值) for 值 in 行.values()]
    if isinstance(行, (list, tuple)):
        return [取单元格文本(值) for 值 in 行]
    return [取单元格文本(行)]


def 取列表(值) -> list:
    """安全取列表；非列表返回空列表。"""
    return 值 if isinstance(值, list) else []
