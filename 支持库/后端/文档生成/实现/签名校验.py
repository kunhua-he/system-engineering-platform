"""签名校验：生成后验证 OOXML 为有效 ZIP 且含必要成员，PDF 校验头尾并可重开。

- docx: [Content_Types].xml + word/document.xml
- xlsx: [Content_Types].xml + xl/workbook.xml
- pptx: [Content_Types].xml + ppt/presentation.xml
- pdf:  %PDF 头 + %%EOF 尾 + 可重新打开（经受管提供者能力 PDF隔离提供者.校验PDF）
"""

from __future__ import annotations

import io
import zipfile

from 公共契约.基础类型.结果类型 import 结果

来源 = "文档生成"
校验PDF能力id = "PDF隔离提供者.校验PDF"
OOXML必要成员表 = {
    "docx": ["[Content_Types].xml", "word/document.xml"],
    "xlsx": ["[Content_Types].xml", "xl/workbook.xml"],
    "pptx": ["[Content_Types].xml", "ppt/presentation.xml"],
}


def 校验签名(格式: str, 字节: bytes) -> 结果:
    """校验生成产物签名；成功值 = 诊断文本列表。"""
    if not isinstance(字节, bytes):
        return 结果.失败("参数不合法", "字节必须是二进制数据", 来源=来源)
    格式 = str(格式 or "").lower().lstrip(".")
    if 格式 in OOXML必要成员表:
        return _校验OOXML(格式, 字节)
    if 格式 == "pdf":
        return _校验PDF(字节)
    return 结果.失败("参数不合法", f"不支持的签名校验格式 '{格式}'", 来源=来源)


def _校验OOXML(格式: str, 字节: bytes) -> 结果:
    """校验 OOXML 压缩包有效且必要成员齐全。"""
    try:
        with zipfile.ZipFile(io.BytesIO(字节)) as 压缩包:
            if 压缩包.testzip() is not None:
                return 结果.失败("生成失败", "OOXML 压缩包存在损坏成员", 来源=来源)
            名称表 = set(压缩包.namelist())
    except (zipfile.BadZipFile, OSError) as 错误:
        return 结果.失败("生成失败", f"不是有效 ZIP 压缩包: {错误}", 来源=来源)
    缺失成员 = [成员 for 成员 in OOXML必要成员表[格式] if 成员 not in 名称表]
    if 缺失成员:
        return 结果.失败(
            "生成失败",
            f"{格式} 缺少必要成员: {缺失成员}",
            来源=来源,
        )
    return 结果.成功结果([f"{格式} 为有效 ZIP，必要成员齐全"])


def _校验PDF(字节: bytes) -> 结果:
    """校验 PDF 头尾并尝试重新打开。"""
    if not 字节.startswith(b"%PDF"):
        return 结果.失败("生成失败", "PDF 缺少 %PDF 文件头", 来源=来源)
    尾部 = 字节[-2048:].rstrip(b"\r\n \t")
    if not 尾部.endswith(b"%%EOF") and b"%%EOF" not in 尾部:
        return 结果.失败("生成失败", "PDF 缺少 %%EOF 文件尾", 来源=来源)
    页数 = _尝试重开(字节)
    if 页数 is None:
        return 结果.失败("生成失败", "PDF 无法重新打开解析", 来源=来源)
    if 页数 == 0:
        return 结果.成功结果(["PDF 头尾齐全；PDF 隔离提供者不可用，未执行重开校验"])
    return 结果.成功结果([f"PDF 头尾齐全，可重新打开（{页数} 页）"])


def _尝试重开(字节: bytes) -> int | None:
    """经受管提供者能力 PDF隔离提供者.校验PDF 重开 PDF，返回页数。

    主进程不加载 fitz/pdfplumber（PyMuPDF SWIG 崩溃隔离）；
    提供者不可用/子进程崩溃时返回 None（签名校验降级为仅头尾检查）。
    """
    from 公共契约.能力契约.调用器 import 获取能力调用器

    try:
        结果 = 获取能力调用器().调用能力(校验PDF能力id, {"字节": 字节}, 调用方=来源)
    except RuntimeError:
        # 装配测试/最小运行单元可能没有带上隔离提供者；头尾校验仍可
        # 作为明确降级结果返回。真实解析失败不走此分支，仍然阻断。
        return 0
    if not 结果.成功:
        if 结果.错误码 in {"提供者不可用", "能力不存在", "CAPABILITY_NOT_FOUND", "PROVIDER_UNAVAILABLE"}:
            return 0
        return None
    值 = 结果.值
    if not isinstance(值, dict) or "错误码" in 值:
        return None
    try:
        return int(值.get("页数") or 0) or None
    except (TypeError, ValueError):
        return None
