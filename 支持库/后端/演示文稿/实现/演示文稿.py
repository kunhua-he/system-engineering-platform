"""演示文稿解析原子能力：经受管提供者能力解析 ppt/pptx。

- pptx 原生解析经受管提供者能力 `演示文稿.解析演示文稿`
  （python_pptx提供者）执行，本模块（主进程）绝不 import pptx；
- 旧格式 ppt 先经受管提供者能力 `LibreOffice转换.转换办公文件`
  转 pptx 再解析；
- OOXML 不可信 ZIP 安全校验（成员数/单项大小/总量/压缩比/路径逃逸/
  宏/外部引用）保留在本模块（纯标准库 zipfile）；
- 能力经 公共契约.能力契约.调用器.获取能力调用器 注入的唯一能力
  调用服务调用；调用器未装配时如实返回 提供者不可用。

安全约束：损坏/伪装→文件损坏；超限→超出限制；缺提供者→提供者不可用。
"""

from __future__ import annotations

import shutil
import tempfile
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from 公共契约.基础类型.文档结构 import 通用文档, 归一化格式
from 公共契约.基础类型.结果类型 import 结果

来源 = "演示文稿"
解析演示文稿能力id = "演示文稿.解析演示文稿"
转换办公能力id = "LibreOffice转换.转换办公文件"
默认最大幻灯片数 = 200
默认最大字节数 = 200 * 1024 * 1024
默认超时秒 = 60
最大压缩包条目数 = 5000
最大压缩比 = 1000


def _调用(能力id: str, 请求参数: dict) -> 结果:
    """经唯一能力调用服务调用受管提供者能力；调用器未装配时如实失败。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器

    try:
        return 获取能力调用器().调用能力(能力id, 请求参数, 调用方=来源)
    except RuntimeError as 错误:
        return 结果.失败("提供者不可用", str(错误), 来源=来源, 可重试=True)


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试)


def _检查压缩包(路径: Path, 最大字节数: int) -> str | None:
    """OOXML 不可信 ZIP 检查：文件数/单项/总量/压缩比/路径逃逸/宏/外部文件引用。"""
    try:
        压缩包 = zipfile.ZipFile(路径)
    except (zipfile.BadZipFile, OSError, ValueError):
        return "文件损坏"
    try:
        条目表 = 压缩包.infolist()
        if len(条目表) > 最大压缩包条目数:
            return "超出限制"
        总量 = 0
        for 条目 in 条目表:
            名称 = 条目.filename.replace("\\", "/")
            if 条目.file_size > 最大字节数 or 条目.file_size > 最大压缩比 * max(条目.compress_size, 1):
                return "超出限制"
            总量 += 条目.file_size
            if 总量 > 最大字节数:
                return "超出限制"
            if 名称.startswith("/") or ".." in 名称.split("/") or 名称.lower() == "vbaproject.bin":
                return "文件损坏"
            if 名称.endswith(".rels"):
                try:
                    关系 = 压缩包.read(名称).decode("utf-8", "replace")
                except (KeyError, OSError, zipfile.BadZipFile, RuntimeError):
                    关系 = ""
                if 'TargetMode="External"' in 关系 and "file:" in 关系:
                    return "文件损坏"
        return None
    finally:
        压缩包.close()


def 解析演示文稿(
    文件路径: str,
    格式: str = "",
    最大幻灯片数: int = 默认最大幻灯片数,
    最大字节数: int = 默认最大字节数,
    超时秒: float = 默认超时秒,
) -> 结果:
    """解析 ppt/pptx 演示文稿为 结果[通用文档]。"""
    开始时间 = time.monotonic()
    来源 = Path(文件路径)
    if not 来源.is_file():
        return _失败("文件不存在", f"文件不存在: {来源}")
    try:
        格式 = 归一化格式(格式 or 来源.suffix.lstrip("."))
    except ValueError:
        return _失败("参数不合法", f"不支持的格式: {格式 or 来源.suffix}")
    if 格式 not in ("ppt", "pptx"):
        return _失败("参数不合法", f"仅支持 ppt/pptx，收到: {格式}")
    if 来源.stat().st_size > 最大字节数:
        return _失败("超出限制", f"文件大小超过上限 {最大字节数} 字节")
    if 格式 == "pptx":
        错误码 = _检查压缩包(来源, 最大字节数)
        if 错误码:
            return _失败(错误码, "OOXML 不可信 ZIP 检查未通过" if 错误码 == "文件损坏" else "演示文稿资源超过上限")

    临时目录: Path | None = None
    解析路径 = 来源
    解析方式 = "原生"
    附加警告: list[str] = []
    try:
        if 格式 == "ppt":
            临时目录 = Path(tempfile.mkdtemp(prefix="平台演示文稿_"))
            转换结果 = _转换ppt为pptx(来源, 临时目录, 超时秒)
            if not 转换结果.成功:
                return 转换结果
            解析路径 = Path(转换结果.值)
            解析方式 = "转换"
            附加警告 = ["converted_from_ppt"]

        调用结果 = _调用(解析演示文稿能力id, {
            "文件路径": str(解析路径),
            "格式": "pptx",
            "最大幻灯片数": 最大幻灯片数,
            "最大字节数": 最大字节数,
            "超时秒": 超时秒,
        })
        if not 调用结果.成功:
            return 调用结果
        文档 = 调用结果.值
        if not isinstance(文档, 通用文档):
            return _失败("文件损坏", "演示文稿提供者返回了无效结果")
        return 结果.成功结果(replace(
            文档,
            格式=格式,
            解析方式=解析方式,
            警告=list(文档.警告) + 附加警告,
            耗时秒=round(time.monotonic() - 开始时间, 4),
        ))
    finally:
        临时目录 and shutil.rmtree(临时目录, ignore_errors=True)


def _转换ppt为pptx(源路径: Path, 临时目录: Path, 超时秒: float) -> 结果:
    """经受管提供者能力把旧格式 PPT 转为 PPTX，返回目标文件路径。"""
    转换结果 = _调用(转换办公能力id, {
        "输入路径": str(源路径),
        "目标格式": "pptx",
        "输出目录": str(临时目录),
        "超时秒": 超时秒,
    })
    if not 转换结果.成功:
        return 转换结果
    值 = 转换结果.值
    if not isinstance(值, dict) or not 值.get("输出路径"):
        return _失败("转换失败", "LibreOffice 未产出转换文件")
    目标 = Path(值["输出路径"])
    if not 目标.is_file():
        return _失败("转换失败", f"LibreOffice 未产出文件: {目标.name}")
    return 结果.成功结果(str(目标))
