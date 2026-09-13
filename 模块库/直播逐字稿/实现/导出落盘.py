"""导出落盘：原子写文本/JSON，保证导出路径不落半成品。

写入统一交底座 `资源管理.原子写入`（临时文件 + 落盘 + 改名由底座承担），
本文件只做入参校验与字节数复核；任何失败返回稳定中文错误码。
"""

from __future__ import annotations

from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

来源 = "直播逐字稿"


def _底座(能力id: str, 参数: dict):
    """经唯一能力调用服务调用底座原子能力；未装配或异常时返回 None。"""
    from 公共契约.能力契约.调用器 import 获取能力调用器
    try:
        return 获取能力调用器().调用能力(能力id, 参数, 调用方=来源)
    except Exception:
        return None


def _成功(结果对象) -> bool:
    return bool(结果对象 is not None and getattr(结果对象, "成功", False))


def _失败说明(结果对象, 兜底: str) -> str:
    return str(getattr(结果对象, "错误说明", "") or getattr(结果对象, "错误码", "") or 兜底)


def 原子写文本(目标路径: str, 内容: str) -> 结果:
    """原子写文本文件；成功返回 值={导出路径, 字节数, 字符数}。"""
    if not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "导出路径 必须为非空文本", 来源=来源)
    if not isinstance(内容, str) or not 内容.strip():
        return 结果.失败("写入失败", "待写内容为空，拒绝生成空稿", 来源=来源)
    目标 = Path(目标路径).expanduser()
    期望字节数 = len(内容.encode("utf-8"))
    写入 = _底座("系统核心支持库.资源管理.原子写入",
              {"目标路径": str(目标), "内容": 内容})
    if not _成功(写入):
        return 结果.失败("写入失败", f"导出失败: {_失败说明(写入, '原子写入未成功')}", 来源=来源)
    大小 = _底座("文件系统支持库.文件操作.获取大小", {"文件路径": str(目标)})
    if not _成功(大小):
        # 取不到落盘大小就必须失败：拿期望字节数顶替会让下面的比对恒等，
        # 写残/写空也就静默通过了。
        return 结果.失败("写入失败",
                      f"导出后无法读取文件大小: {_失败说明(大小, '获取大小未成功')}", 来源=来源)
    字节数 = int(getattr(大小, "值", 0) or 0)
    if 字节数 != 期望字节数:
        return 结果.失败("写入失败", f"导出字节数不符: 期望 {期望字节数}，实际 {字节数}", 来源=来源)
    return 结果.成功结果({"导出路径": str(目标.resolve()), "字节数": 字节数, "字符数": len(内容)})


def 原子写JSON(目标路径: str, 数据: dict) -> 结果:
    """原子写 JSON 文件（utf-8、缩进 2）。"""
    序列化 = _底座("数据操作支持库.数据交换.序列化JSON", {"数据": 数据})
    if not _成功(序列化):
        return 结果.失败("写入失败", f"数据无法序列化为 JSON: {_失败说明(序列化, '序列化失败')}", 来源=来源)
    文本 = getattr(序列化, "值", None)
    if not isinstance(文本, str):
        return 结果.失败("写入失败", "数据无法序列化为 JSON: 序列化结果非文本", 来源=来源)
    return 原子写文本(目标路径, 文本 + "\n")


def 清理临时残留(目录: str) -> int:
    """清理目录内本模块产生的临时文件（.xxx.临时-*），返回清理条数。"""
    列出 = _底座("文件系统支持库.文件操作.列出目录",
              {"目录路径": str(Path(目录).expanduser())})
    if not _成功(列出):
        return 0
    条目 = getattr(列出, "值", None) or []
    目录路径 = Path(目录).expanduser()
    条数 = 0
    for 名称 in 条目:
        名称 = str(名称)
        if 名称.startswith(".") and ".临时-" in 名称:
            删除 = _底座("文件系统支持库.文件操作.删除文件",
                      {"文件路径": str(目录路径 / 名称)})
            if _成功(删除):
                条数 += 1
    return 条数
