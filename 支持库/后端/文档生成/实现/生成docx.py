"""DOCX 原子生成：按内容块列表用 python-docx 生成字节。

只负责生成字节；缺库抛 ImportError（由上层转为 提供者不可用）、
参数非法抛 ValueError（由上层转为 参数不合法）、其余异常抛原异常。
"""

from __future__ import annotations

import io

from 支持库.后端.文档生成.实现.共用解析 import 取文本, 取类型, 取级别


def 生成DOCX字节(参数: dict) -> bytes:
    """按 内容块列表 生成 DOCX 字节。"""
    from docx import Document  # 缺库时 ImportError 冒泡
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    内容块列表 = 参数.get("内容块列表") or []
    if not isinstance(内容块列表, list) or not 内容块列表:
        raise ValueError("内容块列表不能为空，至少需要一个可渲染块")

    文档 = Document()
    渲染数 = 0
    for 块 in 内容块列表:
        if not isinstance(块, dict):
            continue
        类型 = 取类型(块)
        if 类型 == "标题":
            文档.add_heading(取文本(块), level=min(取级别(块), 4))
            渲染数 += 1
        elif 类型 == "段落":
            段落 = 文档.add_paragraph()
            文本 = 取文本(块)
            if 文本:
                运行 = 段落.add_run(文本)
                运行.bold = bool(块.get("加粗", 块.get("bold", False)))
                运行.font.size = Pt(12)
            对齐值 = str(块.get("对齐", 块.get("对齐", "left")) or "left").lower()
            段落.alignment = {
                "left": WD_ALIGN_PARAGRAPH.LEFT,
                "center": WD_ALIGN_PARAGRAPH.CENTER,
                "right": WD_ALIGN_PARAGRAPH.RIGHT,
                "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
            }.get(对齐值, WD_ALIGN_PARAGRAPH.LEFT)
            渲染数 += 1
        elif 类型 == "表格":
            表格 = _构建表格(文档, 块)
            if 表格:
                渲染数 += 1
        elif 类型 == "分页":
            文档.add_page_break()

    if 渲染数 == 0:
        raise ValueError("内容块列表中没有可渲染块（标题/段落/表格/分页）")

    缓冲 = io.BytesIO()
    文档.save(缓冲)
    return 缓冲.getvalue()


def _构建表格(文档, 块: dict):
    """按 表头/行 构建表格，返回是否成功渲染。"""
    表头 = _取列表(块.get("表头") or 块.get("header") or 块.get("columns") or [])
    行列表 = _取列表(块.get("行") or 块.get("rows") or [])
    标准化行列表: list[list[str]] = []
    if 表头:
        标准化行列表.append([_取单元格文本(单元格) for 单元格 in 表头])
    for 行 in 行列表:
        标准化行列表.append(_标准化行(行, 表头))
    标准化行列表 = [行 for 行 in 标准化行列表 if 行]
    if not 标准化行列表:
        return False
    列数 = max(len(行) for 行 in 标准化行列表)
    表格 = 文档.add_table(rows=len(标准化行列表), cols=列数)
    try:
        表格.style = "Table Grid"
    except Exception:
        pass
    for 行序号, 行数据 in enumerate(标准化行列表):
        for 列序号, 单元格文本 in enumerate(行数据):
            表格.rows[行序号].cells[列序号].text = 单元格文本
    return True


def _标准化行(行, 表头: list) -> list[str]:
    if isinstance(行, dict):
        if 表头:
            return [_取单元格文本(行.get(表头单元格)) for 表头单元格 in 表头]
        return [_取单元格文本(值) for 值 in 行.values()]
    if isinstance(行, (list, tuple)):
        return [_取单元格文本(值) for 值 in 行]
    return [_取单元格文本(行)]


def _取单元格文本(值) -> str:
    if isinstance(值, dict):
        for 键 in ("文本", "标注", "value", "name"):
            if 键 in 值 and 值[键] is not None:
                return str(值[键])
        return str(值)
    return "" if 值 is None else str(值)


def _取列表(值) -> list:
    return 值 if isinstance(值, list) else []
