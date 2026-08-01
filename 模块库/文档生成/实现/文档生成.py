"""文档生成模块：按格式组合文档生成支持库能力，返回统一 生成产物。

能力签名：生成文档(格式, 内容参数) → 结果[生成产物]。
- 格式非法（非 docx/xlsx/pptx/pdf）→ 错误码“参数不合法”
- 支持库缺库 → 错误码“提供者不可用”（透传）
- 生成字节为空 → 错误码“生成失败”
"""

from __future__ import annotations

import base64

from 公共契约.基础类型.文档结构 import 生成产物
from 支持库.适配层.python_docx提供者 import 生成文字文档 as _生成docx
from 支持库.适配层.openpyxl提供者 import 生成表格文档 as _生成xlsx
from 支持库.适配层.python_pptx提供者 import 生成演示文稿 as _生成pptx
from 支持库.适配层.reportlab提供者 import 生成PDF as _生成pdf

# 格式 → 提供者生成函数（一格式一权威提供者）
生成函数表 = {
    "docx": _生成docx,
    "xlsx": _生成xlsx,
    "pptx": _生成pptx,
    "pdf": _生成pdf,
}
可生成格式 = set(生成函数表)


def 生成文档(格式: str, 内容参数: dict):
    """按格式生成文档，返回 结果[生成产物]。"""
    from 公共契约.基础类型.文档结构 import 归一化格式

    标准格式 = _归一化格式(格式)
    if 标准格式 not in 可生成格式:
        return _失败(
            "参数不合法",
            f"暂不支持生成格式 '{标准格式}'，仅支持 {sorted(可生成格式)}",
        )
    if not isinstance(内容参数, dict):
        return _失败("参数不合法", "内容参数必须是字典")

    try:
        支持库结果 = 生成函数表[标准格式](内容参数)
    except Exception as 错误:
        return _失败("生成失败", f"{标准格式} 生成器异常: {错误}")
    if not 支持库结果.成功:
        return 支持库结果  # 透传：提供者不可用 / 参数不合法 / 生成失败
    值 = 支持库结果.值
    if isinstance(值, 生成产物):
        产物 = 值
    elif isinstance(值, dict) and 值.get("字节b64"):
        字节 = base64.b64decode(值["字节b64"])
        产物 = 生成产物(
            格式=标准格式,
            字节=字节,
            媒体类型=值.get("媒体类型", ""),
            摘要=值.get("摘要", ""),
            诊断=值.get("诊断", []),
            附加=值.get("附加", {}),
        )
    else:
        return _失败("生成失败", f"{标准格式} 生成产物为空")

    if not 产物.字节:
        return _失败("生成失败", f"{标准格式} 生成产物为空")

    补充摘要(产物)
    from 公共契约.基础类型.结果类型 import 结果
    return 结果.成功结果(产物)


def 补充摘要(产物) -> None:
    """产物摘要为空时按字节补齐（统一 生成产物 摘要字段）。"""
    import hashlib

    if not 产物.摘要 and 产物.字节:
        object.__setattr__(产物, "摘要", hashlib.sha256(产物.字节).hexdigest())


def _归一化格式(格式: str) -> str:
    """格式统一为小写无点前缀；非法格式抛 ValueError。"""
    from 公共契约.基础类型.文档结构 import 归一化格式

    try:
        return 归一化格式(格式)
    except ValueError:
        return str(格式 or "").lower().lstrip(".")


def _失败(错误码: str, 消息: str):
    from 公共契约.基础类型.结果类型 import 结果

    return 结果.失败(错误码, 消息, 来源="文档生成")
