"""子进程解析逻辑：在隔离子进程内执行 PDF 解析/校验/版本探测。

本模块只在子进程中导入（见 子进程入口.py）；这里可以安全使用
pdfplumber/fitz，崩溃不影响平台主进程。所有函数返回 JSON 可序列化
的纯 dict（通用文档转字典结构，与 文档结构.py 的 转字典 兼容）。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

单图最大像素 = 40_000_000
最大图像数 = 50
默认最大页数 = 500


def _加载库(禁用库表: set[str]) -> dict[str, Any]:
    """惰性加载 pdfplumber/fitz；导入失败记为不可用，不抛异常。"""
    状态: dict[str, Any] = {"pdfplumber": None, "fitz": None, "版本": {}}
    if "pdfplumber" not in 禁用库表:
        try:
            import pdfplumber
            状态["pdfplumber"] = pdfplumber
            状态["版本"]["pdfplumber"] = str(getattr(pdfplumber, "__version__", "未知"))
        except Exception:
            状态["版本"]["pdfplumber"] = "不可用"
    else:
        状态["版本"]["pdfplumber"] = "不可用"
    if "fitz" not in 禁用库表:
        try:
            import fitz
            状态["fitz"] = fitz
            状态["版本"]["fitz"] = str(getattr(fitz, "VersionBind", "未知"))
        except Exception:
            状态["版本"]["fitz"] = "不可用"
    else:
        状态["版本"]["fitz"] = "不可用"
    return 状态


def 获取提供者版本(禁用库表: set[str]) -> dict[str, Any]:
    return {"提供者版本": _加载库(禁用库表)["版本"]}


def _文件摘要(路径: Path) -> str:
    摘要器 = hashlib.sha256()
    with 路径.open("rb") as 流:
        while 数据块 := 流.read(1024 * 1024):
            摘要器.update(数据块)
    return 摘要器.hexdigest()


def _疑似加密(错误: Exception) -> bool:
    消息 = str(错误).lower()
    if "decrypt" in 消息 or "encrypt" in 消息 or "password" in 消息:
        return True
    return type(错误).__name__ == "PdfminerException" and not 消息.strip()


def _检测加密与页数(fitz模块: Any, 路径: Path) -> tuple[bool, int | None]:
    try:
        文档 = fitz模块.open(str(路径))
        try:
            return bool(文档.needs_pass), 文档.page_count
        finally:
            文档.close()
    except Exception:
        return False, None


def _渲染页面图像(fitz文档: Any, 页码: int) -> list[tuple[bytes, str]]:
    结果表: list[tuple[bytes, str]] = []
    try:
        fitz页面 = fitz文档[页码 - 1]
        for 信息 in fitz页面.get_images(full=True):
            xref, 宽, 高 = 信息[0], 信息[2], 信息[3]
            if 宽 * 高 > 单图最大像素:
                continue
            try:
                数据 = fitz文档.extract_image(xref)
            except Exception:
                continue
            结果表.append((数据["image"], 数据["ext"]))
    except Exception:
        return []
    return 结果表


def _提取页面图像(页面: Any, fitz文档: Any | None, 页码: int, 资源列表: list[dict], 警告表: list[str], 已提取数: int) -> tuple[list[dict], int]:
    渲染表 = _渲染页面图像(fitz文档, 页码) if fitz文档 else []
    块列表: list[dict] = []
    序号 = 0
    for 图像 in (页面.images or []):
        已提取数 += 1
        if 已提取数 > 最大图像数:
            警告表.append(f"图像超过上限 {最大图像数} 张，后续截断")
            break
        名称 = 图像.get("name") or f"图像_第{页码}页_第{序号 + 1}张"
        附加 = {"宽度": int(图像.get("width") or 0), "高度": int(图像.get("height") or 0)}
        块项: dict[str, Any] = {
            "类型": "图像", "文本": 名称, "来源位置": {"页码": 页码},
            "资源引用": None, "附加": 附加,
        }
        if 序号 < len(渲染表):
            字节, 扩展名 = 渲染表[序号]
            资源引用 = len(资源列表)
            资源列表.append({
                "类型": "图像", "媒体类型": f"image/{扩展名}", "文件名": 名称,
                "描述": f"第{页码}页图像",
                "字节数据b64": __import__("base64").b64encode(字节).decode("ascii"),
            })
            块项["资源引用"] = 资源引用
        块列表.append(块项)
        序号 += 1
    return 块列表, 已提取数


def 解析PDF为字典(
    文件路径: str,
    最大页数: int = 默认最大页数,
    最大字节数: int = 0,
    禁用库表: set[str] | None = None,
) -> dict[str, Any]:
    """解析 PDF 为通用文档字典；失败时返回 {"错误码": ..., "错误说明": ...}。"""
    禁用库表 = 禁用库表 or set()
    状态 = _加载库(禁用库表)
    if 状态["pdfplumber"] is None:
        return {"错误码": "提供者不可用", "错误说明": "pdfplumber 不可用，无法解析 PDF", "可重试": True}
    路径 = Path(文件路径)
    if not 路径.is_file():
        return {"错误码": "文件不存在", "错误说明": f"文件不存在: {文件路径}"}
    大小 = 路径.stat().st_size
    if 最大字节数 > 0 and 大小 > 最大字节数:
        return {"错误码": "超出限制", "错误说明": f"文件 {大小} 字节超过上限 {最大字节数} 字节"}
    开始时刻 = time.monotonic()
    是否加密, 页数 = _检测加密与页数(状态["fitz"], 路径) if 状态["fitz"] else (False, None)
    if 是否加密:
        return {"错误码": "文件加密", "错误说明": "PDF 已加密，需要密码才能解析"}
    if 页数 is not None and 最大页数 > 0 and 页数 > 最大页数:
        return {"错误码": "超出限制", "错误说明": f"PDF 共 {页数} 页超过上限 {最大页数} 页"}
    fitz文档 = None
    if 状态["fitz"]:
        try:
            fitz文档 = 状态["fitz"].open(str(路径))
        except Exception:
            fitz文档 = None
    try:
        try:
            pdf = 状态["pdfplumber"].open(str(路径))
        except Exception as 错误:
            if _疑似加密(错误):
                return {"错误码": "文件加密", "错误说明": f"PDF 已加密：{错误}"}
            return {"错误码": "文件损坏", "错误说明": f"pdfplumber 打开失败: {错误}"}
        try:
            if 最大页数 > 0 and len(pdf.pages) > 最大页数:
                return {"错误码": "超出限制", "错误说明": f"PDF 共 {len(pdf.pages)} 页超过上限 {最大页数} 页"}
            块列表: list[dict] = []
            资源列表: list[dict] = []
            警告表: list[str] = []
            标题 = ""
            图像数 = 0
            for 页码, 页面 in enumerate(pdf.pages, start=1):
                位置 = {"页码": 页码}
                块列表.append({"类型": "页面", "文本": "", "来源位置": 位置, "资源引用": None, "附加": {}})
                文本 = 页面.extract_text() or ""
                if not 标题 and 文本.strip():
                    标题 = 文本.strip().splitlines()[0][:60]
                for 行 in [行.strip() for 行 in 文本.splitlines() if 行.strip()]:
                    块列表.append({"类型": "段落", "文本": 行, "来源位置": 位置, "资源引用": None, "附加": {}})
                for 表格 in (页面.extract_tables() or []):
                    行表 = [[(单元格 or "") for 单元格 in 行] for 行 in 表格]
                    块列表.append({"类型": "表格", "文本": "", "来源位置": 位置, "资源引用": None, "表格数据": 行表, "附加": {}})
                页图像, 图像数 = _提取页面图像(页面, fitz文档, 页码, 资源列表, 警告表, 图像数)
                块列表.extend(页图像)
                if 图像数 > 最大图像数:
                    警告表.append(f"图像超过上限 {最大图像数} 张，已截断")
                    break
            if 状态["fitz"] is None:
                警告表.append("fitz 不可用，图像仅记录坐标，未渲染字节")
            return {
                "文档类型": "PDF", "格式": "pdf", "标题": 标题,
                "块列表": 块列表, "资源列表": 资源列表,
                "保真级别": "高",
                "解析方式": "pdfplumber+fitz" if 状态["fitz"] else "pdfplumber",
                "警告": 警告表, "诊断": [], "耗时秒": round(time.monotonic() - 开始时刻, 3),
                "提供者版本": dict(状态["版本"]), "原始文件摘要": _文件摘要(路径), "附加": {},
            }
        finally:
            try:
                pdf.close()
            except Exception:
                pass
    except Exception as 错误:
        if _疑似加密(错误):
            return {"错误码": "文件加密", "错误说明": f"PDF 已加密：{错误}"}
        return {"错误码": "文件损坏", "错误说明": f"PDF 解析失败: {错误}"}
    finally:
        if fitz文档 is not None:
            try:
                fitz文档.close()
            except Exception:
                pass


def 校验PDF返回页数(字节: bytes, 禁用库表: set[str] | None = None) -> dict[str, Any]:
    """用 fitz 或 pdfplumber 重新打开 PDF 返回页数（签名校验用）。"""
    禁用库表 = 禁用库表 or set()
    状态 = _加载库(禁用库表)
    import io
    if 状态["fitz"]:
        try:
            with 状态["fitz"].open(stream=字节, filetype="pdf") as 文档:
                return {"页数": 文档.page_count, "提供者": "fitz"}
        except Exception:
            pass
    if 状态["pdfplumber"]:
        try:
            with 状态["pdfplumber"].open(io.BytesIO(字节)) as 文档:
                return {"页数": len(文档.pages), "提供者": "pdfplumber"}
        except Exception:
            pass
    return {"错误码": "文件损坏", "错误说明": "PDF 无法重新打开解析"}
