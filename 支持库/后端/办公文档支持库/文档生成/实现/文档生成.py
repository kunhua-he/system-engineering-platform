"""文档生成支持库原子能力：DOCX/XLSX/PPTX/PDF 生成 + 签名校验。

能力签名：生成DOCX/生成XLSX/生成PPTX/生成PDF(参数dict) → 结果[生成产物]。
第三方生成能力经 能力调用器 调用受管提供者能力（本模块绝不 import
第三方库/适配层实现）：
- docx → `内部.文字文档.生成`（python_docx提供者）
- xlsx → `办公文档支持库.表格文档.生成表格文档`（openpyxl提供者）
- pptx → `内部.演示文稿.生成`（python_pptx提供者）
- pdf  → `文档转换支持库.PDF生成.生成PDF`（reportlab提供者）
调用器未装配时如实返回 提供者不可用。

统一错误码：缺库=提供者不可用；参数非法=参数不合法；生成或签名失败=生成失败。
报告：提供者版本、生成耗时、签名校验结论（附加/诊断）。
"""

from __future__ import annotations

import base64
import hashlib
import time
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.文档结构 import 生成产物
from 支持库.后端.办公文档支持库.文档生成.实现.签名校验 import 校验签名

来源 = "文档生成"
生成能力id表 = {
    # Provider 生成实现使用内部能力 id；公开生成能力由本支持库唯一拥有。
    "docx": "内部.文字文档.生成",
    "xlsx": "办公文档支持库.表格文档.生成表格文档",
    "pptx": "内部.演示文稿.生成",
    "pdf": "文档转换支持库.PDF生成.生成PDF",
}
媒体类型表 = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}
# 格式 → 能力名（错误来源标识）
能力名表 = {
    "docx": "生成DOCX",
    "xlsx": "生成XLSX",
    "pptx": "生成PPTX",
    "pdf": "生成PDF",
}


def _调用(能力id: str, 请求参数: dict) -> 结果:
    """经唯一能力调用服务调用受管提供者能力；调用器未装配时如实失败。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器

    try:
        return 获取能力调用器().调用能力(能力id, 请求参数, 调用方=来源)
    except RuntimeError as 错误:
        return 结果.失败("提供者不可用", str(错误), 来源=来源, 可重试=True)


def 生成DOCX(参数: dict) -> 结果:
    """按内容块列表生成 DOCX，返回 结果[生成产物]。"""
    return _生成("docx", 参数)


def 生成XLSX(参数: dict) -> 结果:
    """按工作表列表生成 XLSX，返回 结果[生成产物]。"""
    return _生成("xlsx", 参数)


def 生成PPTX(参数: dict) -> 结果:
    """按幻灯片列表生成 PPTX，返回 结果[生成产物]。"""
    return _生成("pptx", 参数)


def 生成PDF(参数: dict) -> 结果:
    """按内容块列表生成 PDF，返回 结果[生成产物]。"""
    return _生成("pdf", 参数)


def _生成(格式: str, 参数: dict) -> 结果:
    """统一生成流程：参数校验 → 受管提供者生成 → 空字节检查 → 签名校验 → 产物。"""
    能力名 = 能力名表[格式]
    开始时刻 = time.monotonic()
    if not isinstance(参数, dict):
        return 结果.失败("参数不合法", "参数必须是字典", 来源=能力名)
    if 格式 == "pdf":
        try:
            提供者参数 = _归一化PDF参数(参数)
        except ValueError as 错误:
            return 结果.失败("参数不合法", str(错误), 来源=能力名)
    else:
        提供者参数 = 参数
        if not isinstance(参数.get("内容块列表") or 参数.get("工作表列表") or 参数.get("幻灯片列表"), list):
            return 结果.失败("参数不合法", f"{能力名} 缺少内容列表参数", 来源=能力名)

    调用参数名 = "内容参数"  # 各受管提供者（docx/pptx/xlsx/pdf）统一契约参数名
    调用结果 = _调用(生成能力id表[格式], {调用参数名: 提供者参数})
    if not 调用结果.成功:
        return 调用结果
    值 = 调用结果.值
    if not isinstance(值, dict) or not 值.get("字节b64"):
        return 结果.失败("生成失败", f"{格式} 生成结果为空", 来源=能力名)

    字节 = base64.b64decode(值["字节b64"])
    耗时秒 = time.monotonic() - 开始时刻
    if not 字节:
        return 结果.失败("生成失败", f"{格式} 生成结果为空", 来源=能力名)

    校验 = 校验签名(格式, 字节)
    if not 校验.成功:
        return 结果.失败(
            "生成失败",
            f"{格式} 签名校验未通过: {校验.错误说明}",
            来源=能力名,
        )

    附加: dict[str, Any] = {
        k: v for k, v in 值.items()
        if k not in ("字节b64", "媒体类型", "摘要", "诊断", "格式", "字节数")
    }
    附加["生成耗时秒"] = round(耗时秒, 4)
    附加["签名校验"] = True
    产物 = 生成产物(
        格式=格式,
        字节=字节,
        媒体类型=值.get("媒体类型") or 媒体类型表[格式],
        摘要=值.get("摘要") or hashlib.sha256(字节).hexdigest(),
        诊断=值.get("诊断", []) + [f"{格式} 生成成功，耗时 {耗时秒:.3f} 秒", "签名校验通过"],
        附加=附加,
    )
    return 结果.成功结果(产物)


def _归一化PDF参数(参数: dict) -> dict:
    """把 内容块列表（标题/段落/表格/分页）归一化为提供者 PDF 参数形状。

    reportlab提供者 期望 {标题, 段落列表[{文本,加粗}], 表格列表[{表头,行}]}；
    标题块 按加粗段落渲染，保持平台 内容块列表 语义。
    """
    标题 = str(参数.get("标题") or "")
    段落列表: list[dict[str, Any]] = []
    表格列表: list[dict[str, Any]] = []
    内容块列表 = 参数.get("内容块列表")
    # PDF 支持库的公开参数本身允许标题/段落列表/表格列表；模块入口
    # 统一使用内容块列表。两种公开契约在这里收口，避免跨层参数漂移。
    if not isinstance(内容块列表, list):
        内容块列表 = []
        for 段落 in 参数.get("段落列表") or []:
            if isinstance(段落, dict):
                内容块列表.append({"类型": "段落", **段落})
            else:
                内容块列表.append({"类型": "段落", "文本": 段落})
        for 表格 in 参数.get("表格列表") or []:
            if isinstance(表格, dict):
                内容块列表.append({"类型": "表格", **表格})
        if 标题 and not any(str(块.get("类型", "")).lower() in {"标题", "heading", "h1"}
                            for 块 in 内容块列表 if isinstance(块, dict)):
            内容块列表.insert(0, {"类型": "标题", "文本": 标题})
    for 块 in 内容块列表:
        if not isinstance(块, dict):
            continue
        类型 = str(块.get("类型") or 块.get("type") or "段落").lower()
        映射类型 = {
            "标题": "标题", "heading": "标题", "head": "标题",
            "h1": "标题", "h2": "标题", "h3": "标题", "h4": "标题",
            "段落": "段落", "paragraph": "段落", "文本": "段落",
            "表格": "表格", "table": "表格",
        }.get(类型, "段落")
        数据 = 块.get("data") if isinstance(块.get("data"), dict) else {}
        文本 = str(
            块.get("文本") or 块.get("text") or 块.get("标题")
            or 数据.get("文本") or 数据.get("text") or ""
        )
        if 映射类型 == "表格":
            表格列表.append({
                "表头": 块.get("表头") or 块.get("header") or [],
                "行": 块.get("行") or 块.get("rows") or [],
            })
        elif 文本:
            段落列表.append({
                "文本": 文本,
                "加粗": 映射类型 == "标题" or bool(块.get("加粗") or 块.get("bold")),
            })
    if not 标题 and not 段落列表 and not 表格列表:
        raise ValueError("内容不能为空：标题/段落列表/表格列表至少提供一项")
    return {"标题": 标题, "段落列表": 段落列表, "表格列表": 表格列表}
