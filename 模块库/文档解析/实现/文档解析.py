"""文档解析模块实现：按格式选择独立提供者，返回平台通用文档。

模块只保存能力 id 与契约版本；提供者选择与调用由运行核心注入的
唯一能力调用服务完成（禁止直接 import 支持库/提供者实现）。

组合 支持库.适配层.*提供者（一第三方一支持库）公开能力，
统一错误码与返回结构；本模块不直接连接任何第三方库，
也不物理导入 支持库.后端.* 旧混装包（跨提供者目标上移为模块）。
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from 公共契约.基础类型.文档结构 import 通用文档, 文档块, 来源位置, 支持格式集合
from 公共契约.基础类型.结果类型 import 结果
from 公共契约.能力契约.调用器 import 获取能力调用器

# 格式 → 能力 id（提供者选择由唯一能力调用服务完成）
格式到能力id = {
    "doc": "LibreOffice转换.转换办公文件",
    "docx": "文字文档.解析文字文档",
    "xls": "LibreOffice转换.转换办公文件",
    "xlsx": "表格文档.解析表格文档",
    "ppt": "LibreOffice转换.转换办公文件",
    "pptx": "演示文稿.解析演示文稿",
    "pdf": "PDF文本表格.解析PDF",
}


def _解析旧格式(路径: str, 格式: str, 目标格式: str) -> 结果:
    """旧格式（doc/xls/ppt）经 LibreOffice 转现代格式后解析。"""
    服务 = 获取能力调用器()
    转换 = 服务.调用能力(
        "LibreOffice转换.转换办公文件",
        {"输入路径": 路径, "目标格式": 目标格式},
    )
    if not 转换.成功:
        return 转换
    值 = 转换.值
    if "字节b64" not in 值:
        return 结果.失败("转换失败", "LibreOffice 未产出字节", 来源="文档解析")
    临时 = Path(tempfile.mkdtemp(prefix="旧格式转换_"))
    try:
        临时文件 = 临时 / f"转换.{目标格式}"
        临时文件.write_bytes(base64.b64decode(值["字节b64"]))
        解析能力id = {
            "docx": "文字文档.解析文字文档",
            "xlsx": "表格文档.解析表格文档",
            "pptx": "演示文稿.解析演示文稿",
        }[目标格式]
        return 服务.调用能力(解析能力id, {"文件路径": str(临时文件)})
    finally:
        import shutil
        shutil.rmtree(临时, ignore_errors=True)


def _解析目标(格式: str, 路径: str, 资源预算: int):
    """按格式经唯一能力调用服务解析，返回 结果。"""
    服务 = 获取能力调用器()
    if 格式 in ("doc", "xls", "ppt"):
        目标格式 = {"doc": "docx", "xls": "xlsx", "ppt": "pptx"}[格式]
        return _解析旧格式(路径, 格式, 目标格式)
    if 格式 == "docx":
        return 服务.调用能力("文字文档.解析文字文档", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "xlsx":
        return 服务.调用能力("表格文档.解析表格文档", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "pptx":
        return 服务.调用能力("演示文稿.解析演示文稿", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "pdf":
        return 服务.调用能力("PDF文本表格.解析PDF", {"文件路径": 路径, "最大字节数": 资源预算})
    return 结果.失败("参数不合法", f"格式 '{格式}' 暂无解析提供者", 来源="文档解析")


def _统一为通用文档(值) -> Any:
    """把提供者返回值统一为 通用文档 dataclass（dict/通用文档 兼容）。"""
    if isinstance(值, 通用文档):
        return 值
    if not isinstance(值, dict):
        return 值
    # 内容-ir/v1 结构（文档类型/块列表）或 通用文档-v1 结构（content_type/块列表）
    文档类型 = 值.get("文档类型") or 值.get("content_type") or "文档"
    格式 = 值.get("格式") or 值.get("格式化") or ""
    if not 格式 and 值.get("content_type"):
        # 通用文档-v1：content_type 如 "word"/"spreadsheet"/"presentation"/"pdf" → 反查格式
        content映射 = {"word": "docx", "spreadsheet": "xlsx", "presentation": "pptx", "pdf": "pdf"}
        格式 = content映射.get(值["content_type"], "")
    块列表: list[文档块] = []
    for 块 in 值.get("块列表", []) or []:
        if isinstance(块, 文档块):
            块列表.append(块)
            continue
        if not isinstance(块, dict):
            continue
        来源 = 来源位置(
            页码=int(块.get("页码") or 块.get("来源位置", {}).get("页码", 1) or 1),
            工作表=块.get("来源位置", {}).get("工作表") if isinstance(块.get("来源位置"), dict) else None,
            幻灯片=块.get("来源位置", {}).get("幻灯片") if isinstance(块.get("来源位置"), dict) else None,
        )
        块列表.append(文档块(
            类型=块.get("类型", "段落"),
            文本=块.get("文本", ""),
            来源位置=来源,
            表格数据=块.get("表格数据"),
            资源引用=块.get("resource_ref") or 块.get("资源引用"),
            附加={},
        ))
    return 通用文档(
        文档类型=文档类型,
        格式=格式,
        标题=值.get("标题") or "",
        块列表=块列表,
        资源列表=[],
        保真级别=值.get("保真级别") or 值.get("解析方式") and "高" or "高",
        解析方式=值.get("解析方式") or "",
        警告=值.get("警告") or [],
        诊断=值.get("诊断") or [],
        原始文件摘要=值.get("原始文件摘要") or "",
    )


def 解析文档(文件路径: str, 格式: str, 资源预算: int = 200 * 1024 * 1024) -> 结果:
    """按格式解析文档为平台通用文档。

    参数：
        文件路径：待解析文件绝对路径。
        格式：doc/docx/xls/xlsx/ppt/pptx/pdf（自动归一化小写去点）。
        资源预算：最大文件字节数。
    返回：结果[通用文档]；缺提供者/损坏/超限等返回对应错误码。
    """
    归一化 = (格式 or "").lower().lstrip(".")
    if 归一化 not in 支持格式集合:
        return 结果.失败("参数不合法", f"不支持的格式 '{格式}'，支持：{sorted(支持格式集合)}", 来源="文档解析")
    提供者结果 = _解析目标(归一化, 文件路径, 资源预算)
    if not 提供者结果.成功:
        return 提供者结果
    return 结果.成功结果(_统一为通用文档(提供者结果.值))
