"""PDF 原子生成：按内容块列表用 reportlab 生成字节，支持中文。

中文字体策略：优先注册系统 STSong/PingFang/Songti 字体文件，
失败回退 reportlab 内置 STSong-Light CID 字体（无需字体文件）。
缺库抛 ImportError（上层转 提供者不可用）、参数非法抛 ValueError。
表格渲染在 渲染表格.py，解析辅助在 共用解析.py。
"""

from __future__ import annotations

import io
import os

from 支持库.后端.文档生成.实现.共用解析 import 取级别, 取类型, 取文本
from 支持库.后端.文档生成.实现.渲染表格 import 添加表格


def 生成PDF字节(参数: dict) -> bytes:
    """按 内容块列表 生成 PDF 字节。"""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    内容块列表 = 参数.get("内容块列表") or []
    if not isinstance(内容块列表, list) or not 内容块列表:
        raise ValueError("内容块列表不能为空，至少需要一个可渲染块")

    正文字体, 粗体字体 = _注册中文字体()

    缓冲 = io.BytesIO()
    文档 = SimpleDocTemplate(
        缓冲, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    样式表 = getSampleStyleSheet()
    对齐映射表 = {
        "left": TA_LEFT, "center": TA_CENTER,
        "right": TA_RIGHT, "justify": TA_JUSTIFY,
    }
    元素列表: list = []
    for 块 in 内容块列表:
        if not isinstance(块, dict):
            continue
        类型 = 取类型(块)
        文本 = 取文本(块)
        对齐 = 对齐映射表.get(str(块.get("对齐", "left") or "left").lower(), TA_LEFT)
        if 类型 == "标题":
            级别 = 取级别(块)
            字号 = {1: 22, 2: 18, 3: 16, 4: 14}.get(级别, 18)
            样式 = ParagraphStyle(
                f"标题{级别}", parent=样式表["Heading1"],
                fontSize=字号, alignment=对齐, spaceAfter=12, spaceBefore=18,
                fontName=粗体字体, textColor=HexColor("#2395bc"),
            )
            元素列表.append(Paragraph(文本, 样式))
            元素列表.append(Spacer(1, 6))
        elif 类型 == "段落":
            加粗 = bool(块.get("加粗", 块.get("bold", False)))
            样式 = ParagraphStyle(
                "正文", parent=样式表["Normal"],
                fontSize=12, alignment=对齐, spaceAfter=8, leading=20,
                fontName=粗体字体 if 加粗 else 正文字体,
            )
            元素列表.append(Paragraph(文本, 样式))
        elif 类型 == "表格":
            添加表格(元素列表, 块, 正文字体, 粗体字体)
        elif 类型 == "分页":
            元素列表.append(PageBreak())

    if not 元素列表:
        raise ValueError("内容块列表中没有可渲染块（标题/段落/表格/分页）")

    文档.build(元素列表)
    return 缓冲.getvalue()


def _注册中文字体() -> tuple[str, str]:
    """注册中文字体，返回 (正文字体名, 粗体字体名)。"""
    from reportlab.pdfbase import pdfmetrics

    候选路径表 = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STSong.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
    for 路径 in 候选路径表:
        if not os.path.exists(路径):
            continue
        try:
            from reportlab.pdfbase.ttfonts import TTFont

            pdfmetrics.registerFont(TTFont("STSong", 路径))
            pdfmetrics.registerFont(TTFont("STSong-Bold", 路径))
            return "STSong", "STSong-Bold"
        except Exception:
            continue
    # 回退：reportlab 内置 STSong-Light CID 字体（无需字体文件）
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:
        pass
    return "STSong-Light", "STSong-Light"
