"""reportlab 独立提供者实现：PDF生成.生成PDF（主进程直接 import reportlab）。

按内容参数字典 {标题, 段落列表, 表格列表?} 生成 PDF，返回
结果[生成产物字典{字节b64, 媒体类型, 摘要, 格式, 字节数, 诊断}]。
中文字体：优先注册系统 PingFang.ttc/STSong.ttf/Songti.ttc，
失败回退 reportlab 内置 STSong-Light CID 字体。
表格渲染收拢在 渲染表格.py；reportlab 为纯 Python 库，主进程直接加载。
错误码：参数不合法 / 提供者不可用 / 生成失败。
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import io
import os

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.reportlab提供者.实现.渲染表格 import 添加表格

媒体类型PDF = "application/pdf"
能力名 = "PDF生成.生成PDF"
字体候选路径表 = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STSong.ttf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]


def 生成PDF(参数: dict) -> 结果:
    """按内容参数字典生成 PDF，返回 结果[生成产物字典]。"""
    if not isinstance(参数, dict):
        return 结果.失败("参数不合法", "参数必须是字典", 来源=能力名)
    if not _提供者可用():
        return 结果.失败("提供者不可用", "reportlab 未安装，无法生成 PDF", 来源=能力名)
    try:
        字节 = _生成PDF字节(参数)
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源=能力名)
    except Exception as 错误:
        return 结果.失败("生成失败", f"PDF 生成异常: {错误}", 来源=能力名)
    if not 字节:
        return 结果.失败("生成失败", "PDF 生成结果为空", 来源=能力名)
    return 结果.成功结果({
        "格式": "pdf",
        "字节b64": base64.b64encode(字节).decode("ascii"),
        "媒体类型": 媒体类型PDF,
        "摘要": hashlib.sha256(字节).hexdigest(),
        "字节数": len(字节),
        "提供者版本": _提供者版本(),
        "诊断": [f"PDF 生成成功，共 {len(字节)} 字节"],
    })


def _提供者可用() -> bool:
    """reportlab 是否可导入（纯 Python，主进程直接加载）。"""
    try:
        importlib.import_module("reportlab")
        return True
    except Exception:
        return False


def _提供者版本() -> dict[str, str]:
    """返回 reportlab 版本字典。"""
    try:
        模块 = importlib.import_module("reportlab")
        return {"reportlab": str(getattr(模块, "Version", "未知"))}
    except Exception:
        return {}


def _生成PDF字节(参数: dict) -> bytes:
    """按 标题/段落列表/表格列表 渲染 PDF 字节。"""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    标题 = 参数.get("标题") or ""
    段落列表 = 参数.get("段落列表") or []
    表格列表 = 参数.get("表格列表") or []
    if not isinstance(标题, str):
        raise ValueError("标题必须是文本")
    if not isinstance(段落列表, list):
        raise ValueError("段落列表必须是列表")
    if not isinstance(表格列表, list):
        raise ValueError("表格列表必须是列表")
    if not 标题 and not 段落列表 and not 表格列表:
        raise ValueError("内容不能为空：标题/段落列表/表格列表至少提供一项")

    正文字体, 粗体字体 = _注册中文字体()
    缓冲 = io.BytesIO()
    文档 = SimpleDocTemplate(
        缓冲, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    样式表 = getSampleStyleSheet()
    元素列表: list = []
    if 标题:
        标题样式 = ParagraphStyle(
            "文档标题", parent=样式表["Heading1"],
            fontSize=22, alignment=TA_CENTER, spaceAfter=12, spaceBefore=6,
            fontName=粗体字体, textColor=HexColor("#2395bc"),
        )
        元素列表.append(Paragraph(标题, 标题样式))
        元素列表.append(Spacer(1, 8))
    for 项 in 段落列表:
        if isinstance(项, dict):
            文本 = str(项.get("文本") or 项.get("text") or "")
            加粗 = bool(项.get("加粗") or 项.get("bold") or False)
        else:
            文本 = "" if 项 is None else str(项)
            加粗 = False
        if not 文本.strip():
            continue
        样式 = ParagraphStyle(
            "正文", parent=样式表["Normal"],
            fontSize=12, alignment=TA_LEFT, spaceAfter=8, leading=20,
            fontName=粗体字体 if 加粗 else 正文字体,
        )
        元素列表.append(Paragraph(文本, 样式))
    for 表格 in 表格列表:
        添加表格(元素列表, 表格, 正文字体, 粗体字体)
    if not 元素列表:
        raise ValueError("没有可渲染内容（标题/段落/表格均为空）")
    文档.build(元素列表)
    return 缓冲.getvalue()


def _注册中文字体() -> tuple[str, str]:
    """注册中文字体，返回 (正文字体名, 粗体字体名)。"""
    from reportlab.pdfbase import pdfmetrics

    for 路径 in 字体候选路径表:
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
