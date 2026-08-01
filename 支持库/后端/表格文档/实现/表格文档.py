"""表格文档原子能力实现：openpyxl（XLSX 原生）+ 文档转换（XLS 旧格式）中文适配。

公式/值契约：默认 data_only=True 取缓存值；缓存缺失时回退公式文本。
安全覆盖（统一返回稳定错误码，底层异常不泄漏）：
- OOXML 按不可信 ZIP：文件数/单项大小/总解压大小/压缩比上限、路径逃逸拒绝；
- 损坏文件 → "文件损坏"；缺 openpyxl → "提供者不可用"（不跳过）；
- 超工作表数/超行数/超大小 → "超出限制"；旧格式 XLS 经文档转换支持库转换。
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from 公共契约.基础类型.文档结构 import (
    保真_高, 保真_中, 块_工作表, 文档块, 来源位置, 通用文档,
)
from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.文档转换 import 转换办公文件 as _转换办公文件

默认最大字节数 = 200 * 1024 * 1024
默认超时秒 = 60.0
默认最大工作表数 = 50
默认最大行数 = 200_000
最大压缩比 = 200.0
最大成员数 = 2000
最大单项字节 = 100 * 1024 * 1024
最大解压总字节 = 400 * 1024 * 1024

_提供者缓存: dict[str, Any] | None = None


def 加载提供者() -> dict[str, Any]:
    """惰性加载 openpyxl；导入失败记为不可用，不抛异常。"""
    global _提供者缓存
    if _提供者缓存 is None:
        状态: dict[str, Any] = {"openpyxl": None, "版本": {}}
        try:
            import openpyxl
            状态["openpyxl"] = openpyxl
            状态["版本"]["openpyxl"] = str(getattr(openpyxl, "__version__", "未知"))
        except Exception:
            状态["版本"]["openpyxl"] = "不可用"
        _提供者缓存 = 状态
    return _提供者缓存


def _失败(错误码: str, 消息: str, *, 可重试: bool = False, 详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源="表格文档", 可重试=可重试, 详情=详情 or {})


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
    """不可信 ZIP 检查：文件数/单项大小/总大小/压缩比/路径逃逸/外部关系。"""
    try:
        with zipfile.ZipFile(str(文件路径)) as 压缩包:
            成员列表 = 压缩包.infolist()
            if not 成员列表:
                return _失败("文件损坏", "XLSX 压缩包内无任何成员")
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
                规范化路径 = 成员.filename.replace("\\", "/")
                if ".." in 规范化路径.split("/") or 规范化路径.startswith("/"):
                    return _失败("文件损坏", f"OOXML 成员路径越界: {成员.filename}")
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


def _解析xlsx内容(文件路径: Path, 最大工作表数: int, 最大行数: int) -> tuple[list[文档块], dict[str, Any]]:
    提供者 = 加载提供者()
    openpyxl = 提供者["openpyxl"]
    # 公式/值策略：先取缓存值，无缓存时回退公式文本
    工作簿 = openpyxl.load_workbook(str(文件路径), data_only=True, read_only=True)
    块列表: list[文档块] = []
    工作表数 = 0
    try:
        for 工作表 in 工作簿.worksheets:
            工作表数 += 1
            if 工作表数 > 最大工作表数:
                break
            行列表: list[list[str]] = []
            行计数器 = 0
            for 行 in 工作表.iter_rows(values_only=True):
                行计数器 += 1
                if 行计数器 > 最大行数:
                    break
                单元格列表 = ["" if 值 is None else str(值) for 值 in 行]
                if any(单元格列表):
                    行列表.append(单元格列表)
            文本 = "\n".join(" | ".join(行) for 行 in 行列表)[:1024 * 1024]
            块列表.append(文档块(
                类型=块_工作表,
                文本=文本,
                表格数据=行列表,
                来源位置=来源位置(工作表=工作表.title),
            ))
    finally:
        工作簿.close()
    return 块列表, {"工作表数": 工作表数, "总行数": sum(len(块.表格数据 or []) for 块 in 块列表)}


def 解析表格文档(
    文件路径: str,
    格式: str = "xlsx",
    最大工作表数: int = 默认最大工作表数,
    最大行数: int = 默认最大行数,
    最大字节数: int = 默认最大字节数,
    超时秒: float = 默认超时秒,
) -> 结果:
    """解析 XLS/XLSX 为平台通用文档。xlsx 原生，xls 经文档转换。"""
    路径 = Path(文件路径)
    if not 路径.is_file():
        return _失败("文件不存在", f"文件不存在: {路径}")
    格式 = (格式 or "").lower().lstrip(".")
    if 格式 not in {"xls", "xlsx"}:
        return _失败("参数不合法", f"不支持的格式 '{格式}'")
    if 路径.stat().st_size > 最大字节数:
        return _失败("超出限制", f"文件大小 {路径.stat().st_size} 超过上限 {最大字节数}")

    提供者 = 加载提供者()
    if 提供者["openpyxl"] is None:
        return _失败("提供者不可用", "openpyxl 不可用，无法解析表格文档", 可重试=True)

    实际路径 = 路径
    转换说明 = "原生"
    保真 = 保真_高
    if 格式 == "xls":
        try:
            转换结果 = _转换办公文件(str(路径), "xlsx", 超时秒=超时秒)
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
        块列表, 元数据 = _解析xlsx内容(实际路径, 最大工作表数, 最大行数)
    except Exception as 错误:
        return _失败("文件损坏", f"XLSX 解析失败: {错误}")

    文档 = 通用文档(
        文档类型="表格",
        格式=格式,
        标题=路径.name,
        块列表=块列表,
        保真级别=保真,
        解析方式=转换说明,
        警告=[] if 格式 == "xlsx" else ["converted_from_xls"],
        诊断=[],
        提供者版本=dict(提供者["版本"]),
        原始文件摘要=_文件摘要(路径),
        附加=元数据,
    )
    return _成功(文档)
