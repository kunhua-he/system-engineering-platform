"""文档解析模块实现：按格式经唯一能力调用服务组合提供者，返回平台通用文档。

模块只保存能力 id 与契约版本；提供者选择与调用由运行核心注入的
唯一能力调用服务完成（禁止直接 import 支持库/提供者实现）。

组合 支持库.适配层.*提供者（一第三方一支持库）公开能力，
统一错误码与返回结构；本模块不直接连接任何第三方库。
旧格式（doc/xls/ppt）经 LibreOffice 转换能力输出到 资源管理 支持库
管理的临时目录（创建唯一运行目录 + 安全释放），临时文件生命周期
全部交由支持库层管理，本模块不触碰任何文件原子操作。
"""

from __future__ import annotations

import os
from collections import deque

from 公共契约.基础类型.文档结构 import 通用文档, 文档块, 来源位置, 支持格式集合
from 公共契约.基础类型.结果类型 import 结果
from 公共契约.能力契约.调用器 import 获取能力调用器

来源 = "文档解析"
释放诊断: deque[str] = deque(maxlen=100)  # 环形有界（无消费方的诊断数据不得无界增长）

# 格式 → 能力 id（提供者选择由唯一能力调用服务完成）
格式到能力id = {
    "doc": "LibreOffice转换.转换办公文件",
    "docx": "办公文档支持库.文字文档.解析文字文档",
    "xls": "LibreOffice转换.转换办公文件",
    "xlsx": "办公文档支持库.表格文档.解析表格文档",
    "ppt": "LibreOffice转换.转换办公文件",
    "pptx": "办公文档支持库.演示文稿.解析演示文稿",
    "pdf": "PDF文本表格.解析PDF",
}
旧格式到目标格式 = {"doc": "docx", "xls": "xlsx", "ppt": "pptx"}
转换结果解析能力id = {
    "docx": "办公文档支持库.文字文档.解析文字文档",
    "xlsx": "办公文档支持库.表格文档.解析表格文档",
    "pptx": "办公文档支持库.演示文稿.解析演示文稿",
}


def _失败(错误码: str, 错误说明: str) -> 结果:
    return 结果.失败(错误码, 错误说明, 来源=来源)


def _系统临时根() -> str:
    """系统临时根目录：临时文件生命周期交由 资源管理 支持库管理。"""
    return os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp"


def _解析旧格式(路径: str, 格式: str, 目标格式: str) -> 结果:
    """旧格式（doc/xls/ppt）经 LibreOffice 转现代格式后解析。

    临时目录由 系统核心支持库.资源管理.创建唯一运行目录 创建、解析后由
    系统核心支持库.资源管理.安全释放 回收；本模块不写临时文件、不解码字节。
    """
    服务 = 获取能力调用器()
    try:
        目录值 = 服务.调用能力(
            "系统核心支持库.资源管理.创建唯一运行目录", {"基础目录": _系统临时根()},
        )
    except Exception as 错误:
        return _失败("转换失败", f"创建转换临时目录失败: {错误}")
    if not 目录值.成功 or not isinstance(目录值.值, (str, os.PathLike)):
        return _失败("转换失败", "创建转换临时目录未返回目录路径")
    目录 = str(目录值.值)
    try:
        转换 = 服务.调用能力(
            "LibreOffice转换.转换办公文件",
            {"输入路径": 路径, "目标格式": 目标格式, "输出目录": 目录},
        )
        if not 转换.成功:
            return 转换
        转换值 = 转换.值
        输出路径 = 转换值.get("输出路径") if isinstance(转换值, dict) else None
        if not 输出路径:
            return _失败("转换失败", "LibreOffice 未产出输出路径")
        return 服务.调用能力(
            转换结果解析能力id[目标格式], {"文件路径": 输出路径},
        )
    finally:
        try:
            服务.调用能力("系统核心支持库.资源管理.安全释放", {"路径": 目录})
        except Exception as 错误:
            释放诊断.append(str(错误))

def _解析目标(格式: str, 路径: str, 资源预算: int):
    """按格式经唯一能力调用服务解析，返回 结果。"""
    服务 = 获取能力调用器()
    if 格式 in 旧格式到目标格式:
        return _解析旧格式(路径, 格式, 旧格式到目标格式[格式])
    if 格式 == "docx":
        return 服务.调用能力("办公文档支持库.文字文档.解析文字文档", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "xlsx":
        return 服务.调用能力("办公文档支持库.表格文档.解析表格文档", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "pptx":
        return 服务.调用能力("办公文档支持库.演示文稿.解析演示文稿", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "pdf":
        return 服务.调用能力("PDF文本表格.解析PDF", {"文件路径": 路径, "最大字节数": 资源预算})
    return _失败("参数不合法", f"格式 '{格式}' 暂无解析提供者")


def _统一为通用文档(值):
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
        return _失败("参数不合法", f"不支持的格式 '{格式}'，支持：{sorted(支持格式集合)}")
    提供者结果 = _解析目标(归一化, 文件路径, 资源预算)
    if not 提供者结果.成功:
        return 提供者结果
    return 结果.成功结果(_统一为通用文档(提供者结果.值))
