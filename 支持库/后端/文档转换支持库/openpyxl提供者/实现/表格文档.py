"""openpyxl 独立提供者解析实现：XLSX → 平台通用文档字典。

公式/值契约：数据模式=True 取缓存值，缓存缺失→None→空字符串→整行空则
过滤该行；数据模式=False 返回公式文本本身。OOXML 按不可信 ZIP 校验；
损坏/伪装→文件损坏，加密→文件加密。稳定错误码：文件不存在/参数不合法/
提供者不可用/文件损坏/文件加密/超出限制。
"""

from __future__ import annotations

import hashlib
import time
import zipfile
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

默认最大字节数 = 200 * 1024 * 1024
默认最大工作表数 = 50
默认最大行数 = 200_000
最大成员数 = 2000
最大单项字节 = 100 * 1024 * 1024
最大解压总字节 = 400 * 1024 * 1024
最大压缩比 = 200.0

_提供者缓存: dict[str, Any] | None = None


def 加载提供者() -> dict[str, Any]:
    """惰性加载 openpyxl；导入失败记为不可用，不抛异常。"""
    global _提供者缓存
    if _提供者缓存 is not None:
        return _提供者缓存
    状态: dict[str, Any] = {"openpyxl": None, "版本": {}}
    try:
        import openpyxl
        状态["openpyxl"] = openpyxl
        状态["版本"]["openpyxl"] = str(getattr(openpyxl, "__version__", "未知"))
    except Exception:
        状态["版本"]["openpyxl"] = "不可用"
    _提供者缓存 = 状态
    return _提供者缓存


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="openpyxl提供者", 可重试=可重试)


def _文件摘要(文件路径: Path) -> str:
    摘要器 = hashlib.sha256()
    with open(文件路径, "rb") as 流:
        while 数据块 := 流.read(1024 * 1024):
            摘要器.update(数据块)
    return 摘要器.hexdigest()


def 校验OOXML安全(文件路径: Path) -> 结果:
    """不可信 ZIP 检查：成员数/单项大小/总大小/压缩比/路径逃逸/外部关系。"""
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
                规范路径 = 成员.filename.replace("\\", "/")
                if ".." in 规范路径.split("/") or 规范路径.startswith("/"):
                    return _失败("文件损坏", f"OOXML 成员路径越界: {成员.filename}")
                if 成员.filename.lower().endswith(".rels"):
                    内容 = 压缩包.read(成员).decode("utf-8", errors="ignore")
                    if 'TargetMode="External"' in 内容:
                        return _失败("文件损坏", f"OOXML 含外部关系: {成员.filename}")
            if 原始总字节 > 0 and 总解压字节 / 原始总字节 > 最大压缩比:
                return _失败("超出限制", f"OOXML 压缩比超过上限 {最大压缩比}")
    except zipfile.BadZipFile as 错误:
        return _失败("文件损坏", f"不是有效 OOXML 压缩包: {错误}")
    except OSError as 错误:
        return _失败("文件损坏", f"OOXML 读取失败: {错误}")
    return 结果.成功结果(None)


def _解析xlsx内容(文件路径: Path, 数据模式: bool, 最大工作表数: int, 最大行数: int) -> tuple[list[dict], dict[str, Any]]:
    """read_only 双开值/公式：data_only=数据模式；None→空串；整行空则过滤。"""
    提供者 = 加载提供者()
    工作簿 = 提供者["openpyxl"].load_workbook(str(文件路径), data_only=数据模式, read_only=True)
    块列表: list[dict] = []
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
            块列表.append({
                "类型": "工作表",
                "文本": "\n".join(" | ".join(行) for 行 in 行列表)[:1024 * 1024],
                "来源位置": {"工作表": 工作表.title},
                "资源引用": None,
                "表格数据": 行列表,
            })
    finally:
        工作簿.close()
    元数据 = {"工作表数": 工作表数, "总行数": sum(len(块["表格数据"] or []) for 块 in 块列表)}
    return 块列表, 元数据


def _加密或损坏(错误: Exception) -> 结果:
    消息 = str(错误).lower()
    if "encrypt" in 消息 or "密码" in 消息 or "口令" in 消息:
        return _失败("文件加密", f"XLSX 已加密: {错误}")
    return _失败("文件损坏", f"XLSX 解析失败: {错误}")


def 解析表格文档(文件路径: str, 数据模式: bool = True, 最大工作表数: int = 默认最大工作表数, 最大行数: int = 默认最大行数, 最大字节数: int = 默认最大字节数) -> 结果:
    """解析 XLSX 为通用文档字典（与 通用文档.转字典() 键结构兼容）。"""
    路径 = Path(文件路径)
    if not 路径.is_file():
        return _失败("文件不存在", f"文件不存在: {路径}")
    if not isinstance(数据模式, bool):
        return _失败("参数不合法", "数据模式必须是布尔值")
    大小 = 路径.stat().st_size
    if 大小 > 最大字节数:
        return _失败("超出限制", f"文件大小 {大小} 超过上限 {最大字节数}")
    提供者 = 加载提供者()
    if 提供者["openpyxl"] is None:
        return _失败("提供者不可用", "openpyxl 不可用，无法解析表格文档", 可重试=True)
    安全结果 = 校验OOXML安全(路径)
    if not 安全结果.成功:
        return 安全结果
    开始时刻 = time.monotonic()
    try:
        块列表, 元数据 = _解析xlsx内容(路径, 数据模式, 最大工作表数, 最大行数)
    except Exception as 错误:
        return _加密或损坏(错误)
    return 结果.成功结果({
        "文档类型": "表格", "格式": "xlsx", "标题": 路径.name,
        "块列表": 块列表, "资源列表": [], "保真级别": "高",
        "解析方式": "openpyxl", "警告": [], "诊断": [], "耗时秒": round(time.monotonic() - 开始时刻, 3),
        "提供者版本": dict(提供者["版本"]), "原始文件摘要": _文件摘要(路径),
        "附加": 元数据,
    })
