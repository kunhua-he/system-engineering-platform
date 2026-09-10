"""导出落盘：原子写文本/JSON，保证导出路径不落半成品。

先写同目录临时文件 → 校验字节数 → rename 覆盖目标；任何一步失败都清理临时文件并返回稳定错误码。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

来源 = "直播逐字稿"


def _写临时文件(目标: Path, 内容: str) -> Path:
    临时 = 目标.with_name(f".{目标.name}.临时-{os.getpid()}")
    临时.write_text(内容, encoding="utf-8")
    return 临时


def 原子写文本(目标路径: str, 内容: str) -> 结果:
    """原子写文本文件；成功返回 值={导出路径, 字节数, 字符数}。"""
    if not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "导出路径 必须为非空文本", 来源=来源)
    if not isinstance(内容, str) or not 内容.strip():
        return 结果.失败("写入失败", "待写内容为空，拒绝生成空稿", 来源=来源)
    目标 = Path(目标路径).expanduser()
    临时 = None
    try:
        目标.parent.mkdir(parents=True, exist_ok=True)
        临时 = _写临时文件(目标, 内容)
        字节数 = 临时.stat().st_size
        if 字节数 != len(内容.encode("utf-8")):
            raise OSError(f"临时文件字节数不符: {字节数}")
        临时.replace(目标)
    except OSError as 错误:
        if 临时 is not None:
            try:
                临时.unlink(missing_ok=True)
            except OSError:
                pass
        return 结果.失败("写入失败", f"导出失败: {错误}", 来源=来源)
    except UnicodeEncodeError as 错误:
        return 结果.失败("写入失败", f"内容编码失败: {错误}", 来源=来源)
    return 结果.成功结果({"导出路径": str(目标.resolve()), "字节数": 字节数, "字符数": len(内容)})


def 原子写JSON(目标路径: str, 数据: dict) -> 结果:
    """原子写 JSON 文件（utf-8、缩进 2）。"""
    try:
        内容 = json.dumps(数据, ensure_ascii=False, indent=2) + "\n"
    except (TypeError, ValueError) as 错误:
        return 结果.失败("写入失败", f"数据无法序列化为 JSON: {错误}", 来源=来源)
    return 原子写文本(目标路径, 内容)


def 清理临时残留(目录: str) -> int:
    """清理目录内本模块产生的临时文件（.xxx.临时-*），返回清理条数。"""
    条数 = 0
    try:
        目录路径 = Path(目录).expanduser()
        for 条目 in 目录路径.glob(".*.临时-*"):
            try:
                条目.unlink()
                条数 += 1
            except OSError:
                continue
    except OSError:
        return 条数
    return 条数
