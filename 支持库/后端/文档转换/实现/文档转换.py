"""文档转换原子能力实现：经受管提供者能力调用 textutil / LibreOffice。

- textutil 转换经受管提供者能力 `textutil转换.转换文本文件` 执行；
- LibreOffice 转换经受管提供者能力 `LibreOffice转换.转换办公文件` 执行；
- 检查提供者经受管提供者能力 `textutil转换.检查提供者` /
  `LibreOffice转换.检查提供者` 组合；
- 本模块绝不直接 import 适配层/启动外部进程；调用器未装配时如实
  返回 提供者不可用，不伪装成功。

安全约束（受管提供者承担）：
- 结构化参数列表，禁止 shell=True；
- 独立进程组，启动/执行超时，强制终止兜底；
- 输出文件大小上限与输出目录隔离；
- 临时目录、子进程、句柄在成功/失败/取消/超时路径全部释放；
- 缺少外部程序返回 提供者不可用，不伪装成功。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

来源 = "文档转换"
文本转换能力id = "textutil转换.转换文本文件"
文本检查能力id = "textutil转换.检查提供者"
办公转换能力id = "LibreOffice转换.转换办公文件"
办公检查能力id = "LibreOffice转换.检查提供者"

提供者_文本转换 = "textutil"
提供者_办公转换 = "libreoffice"

默认超时秒 = 60
默认最大输出字节 = 200 * 1024 * 1024
支持目标格式集合 = {
    "txt", "html", "rtf", "pdf", "docx", "pptx", "xlsx",
    "odt", "ods", "odp", "csv", "png", "jpg",
}


def _调用(能力id: str, 请求参数: dict) -> 结果:
    """经唯一能力调用服务调用受管提供者能力；调用器未装配时如实失败。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器

    try:
        return 获取能力调用器().调用能力(能力id, 请求参数, 调用方=来源)
    except RuntimeError as 错误:
        return 结果.失败("提供者不可用", str(错误), 来源=来源, 可重试=True)


def _失败(错误码: str, 消息: str, *, 可重试: bool = False, 详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试, 详情=详情 or {})


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def 检查提供者(提供者名: str) -> 结果:
    """检查 textutil / LibreOffice 是否可用，返回可用性字典。"""
    if 提供者名 not in ("全部", 提供者_文本转换, 提供者_办公转换):
        return _失败("参数不合法", f"未知提供者名 '{提供者名}'（应为 全部/textutil/libreoffice）")
    结果字典: dict[str, Any] = {}
    if 提供者名 in ("全部", 提供者_文本转换):
        文本结果 = _调用(文本检查能力id, {})
        if 文本结果.成功 and isinstance(文本结果.值, dict) and 文本结果.值.get("textutil") == "可用":
            结果字典[提供者_文本转换] = "可用"
        else:
            结果字典[提供者_文本转换] = "不可用"
    if 提供者名 in ("全部", 提供者_办公转换):
        办公结果 = _调用(办公检查能力id, {})
        if 办公结果.成功 and isinstance(办公结果.值, dict) and 办公结果.值.get("LibreOffice") == "可用":
            结果字典[提供者_办公转换] = "可用"
        else:
            结果字典[提供者_办公转换] = "不可用"
    return _成功(结果字典)


def 转换文本文件(
    源路径: str,
    目标格式: str = "txt",
    输出目录: str | None = None,
    超时秒: float = 默认超时秒,
    最大输出字节: int = 默认最大输出字节,
) -> 结果:
    """用 textutil 转换文档（doc/rtf/html 等）为文本或 HTML。"""
    来源路径 = Path(源路径)
    if not 来源路径.is_file():
        return _失败("文件不存在", f"文件不存在: {来源路径}")
    目标格式 = (目标格式 or "").lower().lstrip(".")
    if 目标格式 not in {"txt", "html", "rtf"}:
        return _失败("参数不合法", f"textutil 不支持目标格式 '{目标格式}'")
    if 最大输出字节 <= 0:
        return _失败("参数不合法", "最大输出字节必须为正数")

    调用结果 = _调用(文本转换能力id, {
        "输入路径": str(来源路径),
        "目标格式": 目标格式,
        "输出目录": 输出目录,
        "超时秒": 超时秒,
        "最大输出字节": 最大输出字节,
    })
    if not 调用结果.成功:
        return 调用结果
    值 = 调用结果.值
    if not isinstance(值, dict):
        return _失败("转换失败", "textutil 转换返回了无效结果")
    return _成功({
        "文本": 值.get("文本", ""),
        "格式": 值.get("格式") or 目标格式,
        "提供者": 提供者_文本转换,
    })


def 转换办公文件(
    源路径: str,
    目标格式: str,
    输出目录: str | None = None,
    超时秒: float = 默认超时秒,
    最大输出字节: int = 默认最大输出字节,
) -> 结果:
    """用 LibreOffice 转换 Office 文档（doc/xls/ppt 等）为目标格式。

    返回目标文件绝对路径（成功时 值={"路径": ...}）。
    """
    来源路径 = Path(源路径)
    if not 来源路径.is_file():
        return _失败("文件不存在", f"文件不存在: {来源路径}")
    目标格式 = (目标格式 or "").lower().lstrip(".")
    if 目标格式 not in 支持目标格式集合:
        return _失败("参数不合法", f"LibreOffice 不支持目标格式 '{目标格式}'")
    if 最大输出字节 <= 0:
        return _失败("参数不合法", "最大输出字节必须为正数")
    输出目录路径 = 输出目录 or str(来源路径.parent)

    调用结果 = _调用(办公转换能力id, {
        "输入路径": str(来源路径),
        "目标格式": 目标格式,
        "输出目录": 输出目录路径,
        "超时秒": 超时秒,
        "最大输出字节": 最大输出字节,
    })
    if not 调用结果.成功:
        return 调用结果
    值 = 调用结果.值
    if not isinstance(值, dict) or not 值.get("输出路径"):
        return _失败("转换失败", "LibreOffice 未生成目标文件")
    return _成功({
        "路径": 值["输出路径"],
        "格式": 值.get("格式") or 目标格式,
        "提供者": 提供者_办公转换,
    })
