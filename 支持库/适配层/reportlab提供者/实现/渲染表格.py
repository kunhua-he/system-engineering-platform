"""PDF 表格渲染：按 表头/行 用 reportlab Table 构建表格元素。

从 支持库.后端.文档生成.实现.渲染表格.py 收拢到本提供者（独立子文件，
避免 生成PDF.py 超过单文件行数上限）。
"""

from __future__ import annotations


def 添加表格(元素列表: list, 表格, 正文字体: str, 粗体字体: str) -> None:
    """按 表头/行 构建 reportlab 表格并追加到元素列表。"""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer, Table, TableStyle

    if not isinstance(表格, dict):
        return
    表头 = 表格.get("表头") or 表格.get("header") or []
    行列表 = 表格.get("行") or 表格.get("rows") or []
    if not isinstance(表头, list) or not isinstance(行列表, list):
        raise ValueError("表格的表头/行必须是列表")
    数据列表: list[list[str]] = []
    if 表头:
        数据列表.append([_取单元格文本(单元格) for 单元格 in 表头])
    for 行 in 行列表:
        标准化行 = _标准化行(行, 表头)
        if 标准化行:
            数据列表.append(标准化行)
    if not 数据列表:
        return
    列数 = max(len(行) for 行 in 数据列表)
    数据列表 = [行 + [""] * (列数 - len(行)) for 行 in 数据列表]
    表格元素 = Table(数据列表, colWidths=[4.5 * cm] * 列数)
    表格元素.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), 粗体字体),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2395bc")),
        ("FONTNAME", (0, 1), (-1, -1), 正文字体),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    元素列表.append(表格元素)
    元素列表.append(Spacer(1, 12))


def _标准化行(行, 表头: list) -> list[str]:
    """行（字典/列表/标量）按表头顺序转为文本行。"""
    if isinstance(行, dict):
        if 表头:
            return [_取单元格文本(行.get(单元格)) for 单元格 in 表头]
        return [_取单元格文本(值) for 值 in 行.values()]
    if isinstance(行, (list, tuple)):
        return [_取单元格文本(值) for 值 in 行]
    return [_取单元格文本(行)]


def _取单元格文本(值) -> str:
    """把单元格值转为文本；字典取 文本/text/标注/value/name 键。"""
    if isinstance(值, dict):
        for 键 in ("文本", "text", "标注", "value", "name"):
            if 键 in 值 and 值[键] is not None:
                return str(值[键])
        return str(值)
    return "" if 值 is None else str(值)
