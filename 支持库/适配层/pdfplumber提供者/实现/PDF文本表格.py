"""pdfplumber 独立提供者实现：PDF → 平台通用文档字典（文本块/表格块）。

pdfplumber 为纯 Python 库，主进程直接 import（缺库 → 提供者不可用）；
解析超时通过工作线程 join 强约束（超时 → 超时，可重试）；稳定错误码：
文件不存在/参数不合法/提供者不可用/文件损坏/文件加密/超出限制/超时。
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any

from 公共契约.基础类型.文档结构 import (
    块_段落, 块_表格, 错误_参数不合法, 错误_提供者不可用, 错误_文件不存在,
    错误_文件加密, 错误_文件损坏, 错误_超出限制, 错误_超时,
)
from 公共契约.基础类型.结果类型 import 结果

默认最大页数 = 500
默认最大字节数 = 200 * 1024 * 1024
默认超时秒 = 60.0
_提供者缓存: dict[str, Any] | None = None


def 加载提供者() -> dict[str, Any]:
    """惰性加载 pdfplumber；缺库/被环境变量禁用记为不可用，不抛异常。"""
    global _提供者缓存
    if _提供者缓存 is not None:
        return _提供者缓存
    import os
    if os.environ.get("pdfplumber提供者_禁用库") == "pdfplumber":
        return {"pdfplumber": None, "版本": {"pdfplumber": "不可用"}}
    try:
        import pdfplumber
    except Exception:
        return {"pdfplumber": None, "版本": {"pdfplumber": "不可用"}}
    _提供者缓存 = {"pdfplumber": pdfplumber,
                  "版本": {"pdfplumber": str(getattr(pdfplumber, "__version__", "未知"))}}
    return _提供者缓存

def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="pdfplumber提供者", 可重试=可重试)

def _非负整数(值: Any) -> bool:
    """是否为不小于 0 的整数（布尔不算）。"""
    return isinstance(值, int) and not isinstance(值, bool) and 值 >= 0

def _疑似加密(错误: Exception) -> bool:
    """加密检测：消息/类型名/被包装的原始异常命中加密关键词。"""
    消息 = str(错误).lower()
    原始 = 错误.args[0] if 错误.args and isinstance(错误.args[0], Exception) else None
    类型名 = type(错误).__name__ + (type(原始).__name__ if 原始 else "")
    return (
        any(词 in 消息 for 词 in ("encrypt", "decrypt", "password"))
        or "PasswordIncorrect" in 类型名 or "EncryptionError" in 类型名
    )

def _文件摘要(路径: Path) -> str:
    摘要器 = hashlib.sha256()
    with 路径.open("rb") as 流:
        while 数据块 := 流.read(1024 * 1024):
            摘要器.update(数据块)
    return 摘要器.hexdigest()

def _构造块(类型: str, 页码: int, *, 文本: str = "", 表格数据=None) -> dict[str, Any]:
    """构造与 文档块.转字典() 兼容的块字典。"""
    块 = {"类型": 类型, "文本": 文本, "来源位置": {"页码": 页码}, "资源引用": None, "附加": {}}
    if 表格数据 is not None:
        块["表格数据"] = 表格数据
    return 块

def _解析为字典(pdfplumber模块, 路径: Path, 最大页数: int) -> dict[str, Any]:
    """打开并提取 PDF 为通用文档字典；失败返回含 错误码 的错误字典。"""
    开始时刻 = time.monotonic()
    try:
        pdf = pdfplumber模块.open(str(路径))
    except Exception as 错误:
        if _疑似加密(错误):
            return {"错误码": 错误_文件加密, "错误说明": f"PDF 已加密，需要密码才能解析: {错误}"}
        return {"错误码": 错误_文件损坏, "错误说明": f"pdfplumber 打开失败: {错误}"}
    try:
        if 最大页数 > 0 and len(pdf.pages) > 最大页数:
            return {"错误码": 错误_超出限制, "错误说明": f"PDF 共 {len(pdf.pages)} 页超过上限 {最大页数} 页"}
        块列表: list[dict] = []
        标题 = ""
        for 页码, 页面 in enumerate(pdf.pages, start=1):
            文本 = 页面.extract_text() or ""
            if not 标题 and 文本.strip():
                标题 = 文本.strip().splitlines()[0][:60]
            for 行 in [行.strip() for 行 in 文本.splitlines() if 行.strip()]:
                块列表.append(_构造块(块_段落, 页码, 文本=行))
            for 表格 in (页面.extract_tables() or []):
                行表 = [[(单元格 or "") for 单元格 in 行] for 行 in 表格]
                块列表.append(_构造块(块_表格, 页码, 表格数据=行表))
        return {
            "文档类型": "PDF", "格式": "pdf", "标题": 标题,
            "块列表": 块列表, "资源列表": [],
            "保真级别": "高", "解析方式": "pdfplumber",
            "警告": [], "诊断": [], "耗时秒": round(time.monotonic() - 开始时刻, 3),
            "提供者版本": {"pdfplumber": str(getattr(pdfplumber模块, "__version__", "未知"))},
            "原始文件摘要": _文件摘要(路径), "附加": {},
        }
    finally:
        try:
            pdf.close()
        except Exception:
            pass

def _提取工作(结果箱: dict[str, Any], pdfplumber模块, 路径: Path, 最大页数: int) -> None:
    """工作线程入口：任何异常都转为稳定错误字典，不向主线程抛出。"""
    try:
        结果箱["结果"] = _解析为字典(pdfplumber模块, 路径, 最大页数)
    except Exception as 错误:
        结果箱["结果"] = {"错误码": 错误_文件损坏, "错误说明": f"PDF 解析失败: {错误}"}

def 解析PDF(
    文件路径: str,
    最大页数: int = 默认最大页数,
    最大字节数: int = 默认最大字节数,
    超时秒: float = 默认超时秒,
) -> 结果:
    """解析 PDF 为通用文档字典（值结构兼容 通用文档.转字典()）。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return _失败(错误_参数不合法, "文件路径必须为非空文本")
    if not _非负整数(最大页数):
        return _失败(错误_参数不合法, f"最大页数必须为不小于 0 的整数，收到 {最大页数!r}")
    if not _非负整数(最大字节数):
        return _失败(错误_参数不合法, f"最大字节数必须为不小于 0 的整数，收到 {最大字节数!r}")
    if isinstance(超时秒, bool) or not isinstance(超时秒, (int, float)):
        return _失败(错误_参数不合法, f"超时秒必须为数字，收到 {超时秒!r}")
    路径 = Path(文件路径)
    if not 路径.is_file():
        return _失败(错误_文件不存在, f"文件不存在: {文件路径}")
    大小 = 路径.stat().st_size
    if 最大字节数 > 0 and 大小 > 最大字节数:
        return _失败(错误_超出限制, f"文件 {大小} 字节超过上限 {最大字节数} 字节")
    提供者状态 = 加载提供者()
    if 提供者状态["pdfplumber"] is None:
        return _失败(错误_提供者不可用, "pdfplumber 不可用，无法解析 PDF", 可重试=True)
    结果箱: dict[str, Any] = {}
    工作线程 = threading.Thread(target=_提取工作, args=(结果箱, 提供者状态["pdfplumber"], 路径, 最大页数), daemon=True)
    工作线程.start()
    工作线程.join(max(超时秒, 0.0))
    if 工作线程.is_alive():
        return _失败(错误_超时, f"PDF 解析超过 {超时秒} 秒", 可重试=True)
    字典 = 结果箱["结果"]
    if "错误码" in 字典:
        return _失败(字典["错误码"], str(字典.get("错误说明") or "PDF 解析失败"),
                     可重试=字典["错误码"] in {错误_提供者不可用, 错误_超时})
    return 结果.成功结果(字典)

def 提取表格(文件路径: str, 页序号: int) -> 结果:
    """提取指定页（从 1 开始）第一张表格为二维数组；无表格或页越界返回 []。"""
    if not isinstance(页序号, int) or isinstance(页序号, bool) or 页序号 < 1:
        return _失败(错误_参数不合法, f"页序号必须为不小于 1 的整数，收到 {页序号!r}")
    结果 = 解析PDF(文件路径)
    if not 结果.成功:
        return 结果
    for 块 in 结果.值["块列表"]:
        if 块["类型"] == 块_表格 and 块.get("来源位置", {}).get("页码") == 页序号:
            return 结果.成功结果(块["表格数据"])
    return 结果.成功结果([])
