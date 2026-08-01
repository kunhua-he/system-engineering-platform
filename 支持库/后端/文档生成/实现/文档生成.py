"""文档生成支持库原子能力：DOCX/XLSX/PPTX/PDF 生成 + 签名校验。

能力签名：生成DOCX/生成XLSX/生成PPTX/生成PDF(参数dict) → 结果[生成产物]。
统一错误码：缺库=提供者不可用；参数非法=参数不合法；生成或签名失败=生成失败。
报告：提供者版本、生成耗时、签名校验结论（附加/诊断）。
"""

from __future__ import annotations

import hashlib
import time

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.文档结构 import 生成产物
from 支持库.后端.文档生成.实现.生成docx import 生成DOCX字节
from 支持库.后端.文档生成.实现.生成pdf import 生成PDF字节
from 支持库.后端.文档生成.实现.生成pptx import 生成PPTX字节
from 支持库.后端.文档生成.实现.生成xlsx import 生成XLSX字节
from 支持库.后端.文档生成.实现.提供者 import 提供者版本, 提供者可用
from 支持库.后端.文档生成.实现.签名校验 import 校验签名

媒体类型表 = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}

# 格式 → (生成函数名, 能力名)
生成器表 = {
    "docx": ("生成DOCX字节", "生成DOCX"),
    "xlsx": ("生成XLSX字节", "生成XLSX"),
    "pptx": ("生成PPTX字节", "生成PPTX"),
    "pdf": ("生成PDF字节", "生成PDF"),
}


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
    """统一生成流程：提供者检查 → 生成 → 空字节检查 → 签名校验 → 产物。"""
    函数名, 能力名 = 生成器表[格式]
    开始时刻 = time.monotonic()
    if not isinstance(参数, dict):
        return 结果.失败("参数不合法", "参数必须是字典", 来源=能力名)
    if not 提供者可用(格式):
        return 结果.失败(
            "提供者不可用",
            f"{格式} 生成提供者不可用（缺少第三方库）",
            来源=能力名,
        )
    try:
        字节 = globals()[函数名](参数)
    except ImportError as 错误:
        return 结果.失败(
            "提供者不可用",
            f"{格式} 生成提供者不可用: {错误}",
            来源=能力名,
        )
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源=能力名)
    except Exception as 错误:
        return 结果.失败("生成失败", f"{格式} 生成异常: {错误}", 来源=能力名)

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

    版本表 = 提供者版本(格式)
    诊断 = [
        f"{格式} 生成成功，耗时 {耗时秒:.3f} 秒",
        "签名校验通过：" + "；".join(校验.值 or []),
    ]
    产物 = 生成产物(
        格式=格式,
        字节=字节,
        媒体类型=媒体类型表[格式],
        摘要=hashlib.sha256(字节).hexdigest(),
        诊断=诊断,
        附加={
            "提供者版本": 版本表,
            "生成耗时秒": round(耗时秒, 4),
            "字节数": len(字节),
            "签名校验": True,
        },
    )
    return 结果.成功结果(产物)
