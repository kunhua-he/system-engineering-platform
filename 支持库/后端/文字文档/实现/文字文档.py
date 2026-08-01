"""文字文档原子能力实现：python-docx（DOCX 原生）+ 文档转换（DOC 旧格式）中文适配。

安全覆盖（统一返回稳定错误码，底层异常不泄漏）：
- OOXML 按不可信 ZIP：文件数/单项大小/总解压大小/压缩比上限、路径逃逸拒绝；
- 损坏文件 → "文件损坏"；缺 python-docx → "提供者不可用"（不跳过）；
- 旧格式 DOC 经 文档转换 支持库转换后解析，转换提供者缺失 → "提供者不可用"。
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path
from typing import Any

from 公共契约.基础类型.文档结构 import (
    保真_高, 保真_中, 块_表格, 块_图像, 块_段落, 块_标题,
    文档块, 文档资源, 来源位置, 通用文档,
)
from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.文档转换 import 转换办公文件 as _转换办公文件

默认最大字节数 = 200 * 1024 * 1024
默认超时秒 = 60.0
最大压缩比 = 200.0
最大成员数 = 500
最大单项字节 = 100 * 1024 * 1024
最大解压总字节 = 300 * 1024 * 1024
最大图像数 = 50

_提供者缓存: dict[str, Any] | None = None


def 加载提供者() -> dict[str, Any]:
    """惰性加载 python-docx；导入失败记为不可用，不抛异常。"""
    global _提供者缓存
    if _提供者缓存 is None:
        状态: dict[str, Any] = {"docx": None, "版本": {}}
        try:
            import docx
            状态["docx"] = docx
            状态["版本"]["python-docx"] = str(getattr(docx, "__version__", "未知"))
        except Exception:
            状态["版本"]["python-docx"] = "不可用"
        _提供者缓存 = 状态
    return _提供者缓存


def _失败(错误码: str, 消息: str, *, 可重试: bool = False, 详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源="文字文档", 可重试=可重试, 详情=详情 or {})


def _成功(值: Any) -> 结果:
    return 结果.成功结果(值)


def _文件摘要(文件路径: Path) -> str:
    import hashlib
    摘要器 = hashlib.sha256()
    with 文件路径.open("rb") as 流:
        while 数据块 := 流.read(1024 * 1024):
            摘要器.update(数据块)
    return 摘要器.hexdigest()


def 校验OOXML安全(文件路径: Path) -> 结果:
    """不可信 ZIP 检查：文件数/单项大小/总大小/压缩比/路径逃逸/宏/外部关系。"""
    try:
        with zipfile.ZipFile(str(文件路径)) as 压缩包:
            成员列表 = 压缩包.infolist()
            if not 成员列表:
                return _失败("文件损坏", "DOCX 压缩包内无任何成员")
            if len(成员列表) > 最大成员数:
                return _失败("超出限制", f"OOXML 成员数 {len(成员列表)} 超过上限 {最大成员数}")
            总解压字节 = 0
            原始总字节 = 0
            for 成员 in 成员列表:
                if 成员.file_size > 最大单项字节:
                    return _失败("超出限制", f"OOXML 单项 {成员.filename} 解压后超过上限")
                总解压字节 += 成员.file_size
                原始总字节 += 成员.compress_size
                if 总解压字节 > 最大解压总字节:
                    return _失败("超出限制", f"OOXML 总解压体积超过上限 {最大解压总字节}")
                # 路径逃逸
                规范化路径 = 成员.filename.replace("\\", "/")
                if ".." in 规范化路径.split("/") or 规范化路径.startswith("/"):
                    return _失败("文件损坏", f"OOXML 成员路径越界: {成员.filename}")
                # 宏文件
                if 成员.filename.lower().endswith((".vba", ".bin")) and "vba" in 成员.filename.lower():
                    return _失败("文件损坏", f"OOXML 包含宏文件: {成员.filename}")
                # 外部关系
                if 成员.filename.lower().endswith(".rels"):
                    内容 = 压缩包.read(成员).decode("utf-8", errors="ignore")
                    if "TargetMode=\"External\"" in 内容:
                        return _失败("文件损坏", f"OOXML 含外部关系: {成员.filename}")
            if 原始总字节 > 0 and 总解压字节 / 原始总字节 > 最大压缩比:
                return _失败("超出限制", f"OOXML 压缩比 {总解压字节 / 原始总字节:.1f} 超过上限 {最大压缩比}")
    except zipfile.BadZipFile as 错误:
        return _失败("文件损坏", f"不是有效 OOXML 压缩包: {错误}")
    except OSError as 错误:
        return _失败("文件损坏", f"OOXML 读取失败: {错误}")
    return _成功(None)


def _解析docx内容(文件路径: Path, 最大字节数: int) -> tuple[list[文档块], list[文档资源], dict[str, Any]]:
    提供者 = 加载提供者()
    文档模块 = 提供者["docx"]
    文档对象 = 文档模块.Document(str(文件路径))
    块列表: list[文档块] = []
    资源列表: list[文档资源] = []
    段落计数器 = 0
    表格计数器 = 0
    图像计数器 = 0

    from docx.oxml.ns import qn  # noqa: PLC0415
    from docx.oxml.table import CT_Tbl  # noqa: PLC0415
    from docx.oxml.text.paragraph import CT_P  # noqa: PLC0415
    from docx.table import Table  # noqa: PLC0415
    from docx.text.paragraph import Paragraph  # noqa: PLC0415

    for 子节点 in 文档对象.element.body.iterchildren():
        if isinstance(子节点, CT_P):
            段落计数器 += 1
            段落 = Paragraph(子节点, 文档对象)
            文本内容 = "\n".join(行.rstrip() for 行 in 段落.text.splitlines()).strip()
            if 文本内容:
                样式名 = str(段落.style.name) if 段落.style else ""
                块类型 = 块_标题 if ("heading" in 样式名.lower() or "标题" in 样式名) else 块_段落
                块列表.append(文档块(
                    类型=块类型,
                    文本=文本内容[:最大字节数],
                    来源位置=来源位置(段落序号=段落计数器),
                ))
            for 关联id in _段落图像relid(段落, qn):
                图像计数器 += 1
                if 图像计数器 > 最大图像数:
                    break
                资源项, 引用 = _提取图像资源(文档对象, 关联id, 图像计数器, qn)
                块列表.append(文档块(类型=块_图像, 文本="", 来源位置=来源位置(段落序号=段落计数器), 资源引用=引用))
                资源列表.append(资源项)
        elif isinstance(子节点, CT_Tbl):
            表格计数器 += 1
            表格对象 = Table(子节点, 文档对象)
            表格数据 = _表格转二维(表格对象)
            if 表格数据:
                文本 = "\n".join(" | ".join(行) for 行 in 表格数据)
                块列表.append(文档块(
                    类型=块_表格,
                    文本=文本[:最大字节数],
                    表格数据=表格数据,
                    来源位置=来源位置(附加={"表格": 表格计数器}),
                ))

    元数据 = {
        "段落数": 段落计数器,
        "表格数": 表格计数器,
        "图像数": 图像计数器,
    }
    return 块列表, 资源列表, 元数据


def _段落图像relid(段落: Any, qn: Any) -> list[str]:
    关联id列表: list[str] = []
    for 节点 in 段落._p.iter():
        if not str(节点.tag).endswith("}blip"):
            continue
        关联id = 节点.get(qn("r:嵌入")) or 节点.get(qn("r:link"))
        if 关联id:
            关联id列表.append(关联id)
    return 关联id列表


def _提取图像资源(文档对象: Any, 关联id: str, 资源编号: int, qn: Any) -> tuple[文档资源, int]:
    媒体类型 = "image/png"
    文件名 = "图像.png"
    字节数据 = b""
    try:
        关联关系 = 文档对象.part.rels[关联id]
        目标引用 = str(getattr(关联关系, "target_ref", "") or "")
        目标部件 = 关联关系.target_part
        字节数据 = 目标部件.blob
        媒体类型 = getattr(目标部件, "content_type", None) or "image/png"
        文件名 = 目标引用.rsplit("/", 1)[-1] if "/" in 目标引用 else (目标引用 or "图像.png")
    except Exception:
        pass
    return (
        文档资源(
            类型="图像",
            媒体类型=媒体类型,
            文件名=文件名,
            描述=f"DOCX 内嵌图像 ({关联id})",
            字节数据b64=base64.b64encode(字节数据).decode("ascii") if 字节数据 else "",
        ),
        资源编号,
    )


def _表格转二维(表格: Any) -> list[list[str]]:
    行列表: list[list[str]] = []
    for 行 in 表格.rows:
        单元格列表 = [单元格.text.strip() for 单元格 in 行.cells]
        if any(单元格列表):
            行列表.append(单元格列表)
    return 行列表


def 解析文字文档(
    文件路径: str,
    格式: str = "docx",
    最大字节数: int = 默认最大字节数,
    超时秒: float = 默认超时秒,
) -> 结果:
    """解析 DOC/DOCX 为平台通用文档。docx 原生，doc 经文档转换。"""
    路径 = Path(文件路径)
    if not 路径.is_file():
        return _失败("文件不存在", f"文件不存在: {路径}")
    格式 = (格式 or "").lower().lstrip(".")
    if 格式 not in {"doc", "docx"}:
        return _失败("参数不合法", f"不支持的格式 '{格式}'")
    if 路径.stat().st_size > 最大字节数:
        return _失败("超出限制", f"文件大小 {路径.stat().st_size} 超过上限 {最大字节数}")

    提供者 = 加载提供者()
    if 提供者["docx"] is None:
        return _失败("提供者不可用", "python-docx 不可用，无法解析文字文档", 可重试=True)

    实际路径 = 路径
    转换说明 = "原生"
    保真 = 保真_高
    if 格式 == "doc":
        try:
            转换结果 = _转换办公文件(str(路径), "docx", 超时秒=超时秒)
        except Exception:
            转换结果 = _失败("转换失败", "调用文档转换支持库异常")
        if not 转换结果.成功:
            return 转换结果
        实际路径 = Path(转换结果.值["路径"])
        转换说明 = "LibreOffice 转换"
        保真 = 保真_中

    安全结果 = 校验OOXML安全(实际路径)
    if not 安全结果.成功:
        return 安全结果

    try:
        块列表, 资源列表, 元数据 = _解析docx内容(实际路径, 最大字节数)
    except Exception as 错误:
        return _失败("文件损坏", f"DOCX 解析失败: {错误}")

    文档类型 = "文本" if 格式 == "docx" else "文本"
    文档 = 通用文档(
        文档类型=文档类型,
        格式=格式,
        标题=路径.name,
        块列表=块列表,
        资源列表=资源列表,
        保真级别=保真,
        解析方式=转换说明,
        警告=[] if 格式 == "docx" else ["converted_from_doc"],
        诊断=[],
        提供者版本=dict(提供者["版本"]),
        原始文件摘要=_文件摘要(路径),
        附加=元数据,
    )
    return _成功(文档)
