"""文档解析模块实现：按格式经 HTTP 连接器调用统一网关，返回平台通用文档。

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

来源 = "文档解析"
释放诊断: deque[str] = deque(maxlen=100)  # 环形有界（无消费方的诊断数据不得无界增长）

# 格式 → 能力 id（提供者选择由唯一能力调用服务完成）
格式到能力id = {
    "doc": "文档转换支持库.LibreOffice转换.转换办公文件",
    "docx": "办公文档支持库.文字文档.解析文字文档",
    "xls": "文档转换支持库.LibreOffice转换.转换办公文件",
    "xlsx": "办公文档支持库.表格文档.解析表格文档",
    "ppt": "文档转换支持库.LibreOffice转换.转换办公文件",
    "pptx": "办公文档支持库.演示文稿.解析演示文稿",
    "pdf": "文档转换支持库.PDF文本表格.解析PDF",
}
旧格式到目标格式 = {"doc": "docx", "xls": "xlsx", "ppt": "pptx"}
转换结果解析能力id = {
    "docx": "办公文档支持库.文字文档.解析文字文档",
    "xlsx": "办公文档支持库.表格文档.解析表格文档",
    "pptx": "办公文档支持库.演示文稿.解析演示文稿",
}

_连接器 = None


def 设置HTTP连接器(连接器) -> None:
    """由项目适配层装配连接器；主要用于启动装配与隔离测试。"""
    global _连接器
    _连接器 = 连接器


def _获取连接器():
    return _连接器


def _调用支持库(能力id: str, 参数: dict, *, 失败错误码: str = "提供者不可用") -> 结果:
    """经 HTTP 连接器按能力 id 调用统一网关；失败统一转为 结果。"""
    try:
        连接器 = _获取连接器()
        if 连接器 is None:
            return 结果.失败(失败错误码, "HTTP 连接器未装配", 来源=来源)
        响应 = 连接器.调用能力(能力id, 参数)
        if isinstance(响应, 结果):
            return 响应
        if not isinstance(响应, dict):
            return 结果.失败("返回结果不符合契约", "网关返回不是对象", 来源=来源)
        if 响应.get("成功"):
            return 结果.成功结果(响应.get("值"))
        return 结果.失败(响应.get("错误码") or 失败错误码, 响应.get("错误说明") or "网关调用失败", 来源=来源)
    except FileNotFoundError as 错误:
        return 结果.失败("文件不存在", str(错误), 来源=来源)
    except Exception as 错误:
        return 结果.失败(失败错误码, f"{能力id} 调用失败: {错误}", 来源=来源)


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
    目录值 = _调用支持库(
        "系统核心支持库.资源管理.创建唯一运行目录", {"基础目录": _系统临时根()},
        失败错误码="转换失败",
    )
    if not 目录值.成功 or not isinstance(目录值.值, (str, os.PathLike)):
        return _失败("转换失败", "创建转换临时目录未返回目录路径")
    目录 = str(目录值.值)
    try:
        转换 = _调用支持库(
            "文档转换支持库.LibreOffice转换.转换办公文件",
            {"输入路径": 路径, "目标格式": 目标格式, "输出目录": 目录},
            失败错误码="转换失败",
        )
        if not 转换.成功:
            主结果 = 转换
        else:
            转换值 = 转换.值
            输出路径 = 转换值.get("输出路径") if isinstance(转换值, dict) else None
            if not 输出路径:
                主结果 = _失败("转换失败", "LibreOffice 未产出输出路径")
            else:
                主结果 = _调用支持库(
                    转换结果解析能力id[目标格式], {"文件路径": 输出路径},
                    失败错误码="转换失败",
                )
    except Exception as 错误:
        主结果 = _失败("转换失败", f"旧格式解析流程异常: {错误}")

    释放失败原因: list[str] = []
    try:
        释放结果 = _调用支持库("系统核心支持库.资源管理.安全释放", {"路径": 目录})
        if not isinstance(释放结果, 结果):
            释放失败原因.append("安全释放未返回统一结果")
        elif not 释放结果.成功:
            释放失败原因.append(
                f"安全释放返回失败: {释放结果.错误码}: {释放结果.错误说明}"
            )
    except Exception as 错误:
        释放失败原因.append(f"安全释放调用抛出异常: {错误}")

    if os.path.exists(目录):
        释放失败原因.append("安全释放后目录仍存在")

    if 释放失败原因:
        失败说明 = "；".join(释放失败原因)
        释放诊断.append(失败说明)
        详细信息 = {"释放失败原因": 释放失败原因, "释放目录": 目录}
        if not 主结果.成功:
            详细信息["原主错误"] = {
                "错误码": 主结果.错误码,
                "错误说明": 主结果.错误说明,
                "详细信息": 主结果.详细信息,
            }
        return 结果.失败(
            "资源释放失败", "旧格式文档解析临时资源释放失败",
            来源=来源, 详情=详细信息,
        )
    return 主结果


def _解析目标(格式: str, 路径: str, 资源预算: int):
    """按格式经 HTTP 连接器调用统一网关解析，返回 结果。"""
    if 格式 in 旧格式到目标格式:
        return _解析旧格式(路径, 格式, 旧格式到目标格式[格式])
    if 格式 == "docx":
        return _调用支持库("办公文档支持库.文字文档.解析文字文档", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "xlsx":
        return _调用支持库("办公文档支持库.表格文档.解析表格文档", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "pptx":
        return _调用支持库("办公文档支持库.演示文稿.解析演示文稿", {"文件路径": 路径, "最大字节数": 资源预算})
    if 格式 == "pdf":
        return _调用支持库("文档转换支持库.PDF文本表格.解析PDF", {"文件路径": 路径, "最大字节数": 资源预算})
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
