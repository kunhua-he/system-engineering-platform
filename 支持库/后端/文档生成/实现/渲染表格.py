"""PDF 表格渲染：按 表头/行 用 reportlab Table 构建表格元素。

独立子文件，避免 生成pdf.py 超过单文件行数上限。
"""

from __future__ import annotations

from 支持库.后端.文档生成.实现.共用解析 import 标准化行, 取单元格文本, 取列表


def 添加表格(元素列表: list, 块: dict, 正文字体: str, 粗体字体: str) -> None:
    """按 表头/行 构建 reportlab 表格并追加到元素列表。"""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer, Table, TableStyle

    表头 = 取列表(块.get("表头") or 块.get("header") or [])
    行列表 = 取列表(块.get("行") or 块.get("rows") or [])
    标准化行列表: list[list[str]] = []
    if 表头:
        标准化行列表.append([取单元格文本(单元格) for 单元格 in 表头])
    for 行 in 行列表:
        标准化行列表.append(标准化行(行, 表头))
    标准化行列表 = [行 for 行 in 标准化行列表 if 行]
    if not 标准化行列表:
        return
    列数 = max(len(行) for 行 in 标准化行列表)
    表格数据 = [行 + [""] * (列数 - len(行)) for 行 in 标准化行列表]
    表格 = Table(表格数据, colWidths=[4.5 * cm] * 列数)
    表格.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), 粗体字体),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2395bc")),
        ("FONTNAME", (0, 1), (-1, -1), 正文字体),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    元素列表.append(表格)
    元素列表.append(Spacer(1, 12))
