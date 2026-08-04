"""textutil 文档转换独立提供者：macOS 系统能力受控调用。

只封装 textutil 文本格式转换：txt/html/rtf/doc/docx 之间互转、提取文本。
安全约束：结构化参数列表（禁 shell=True）；独立进程组；超时+强制终止；
输出大小上限与输出目录隔离；缺 textutil 返回 提供者不可用。
"""

from __future__ import annotations

import base64
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

默认超时秒 = 60
默认最大输出字节 = 200 * 1024 * 1024
来源 = "textutil提供者"

_提供者缓存: dict[str, str | None] = {}


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试)


def 查找textutil() -> str | None:
    """查找 textutil 可执行文件（缓存）。"""
    if "textutil" in _提供者缓存:
        return _提供者缓存["textutil"]
    候选列表 = ["textutil", "/usr/bin/textutil"]
    路径 = next((c for c in 候选列表 if shutil.which(c)), None)
    _提供者缓存["textutil"] = 路径
    return 路径


def 检查提供者(超时秒: float = 30) -> 结果:
    """检查 textutil 是否可用（真实独立进程探针：textutil -help + macOS 版本）。

    textutil 无独立版本号，版本取 macOS 系统版本；探针失败
    （工具缺失/超时/退出码非0）→ 外部提供者不可用。
    """
    import platform
    from 支持库.适配层.系统探针 import 检查系统工具
    路径 = 查找textutil()
    if not 路径:
        return _失败("外部提供者不可用", "textutil 未找到（macOS 系统能力缺失）")
    探针 = 检查系统工具("textutil", [路径], 超时秒=超时秒, 版本参数="-help")
    if not 探针.成功:
        return _失败("外部提供者不可用",
                      f"textutil 探针失败（{探针.错误码}）: {探针.诊断}")
    版本 = platform.mac_ver()[0] or platform.release()
    return 结果.成功结果({
        "textutil": "可用",
        "版本": 版本,
        "退出码": 探针.退出码,
        "标准错误摘要": 探针.标准错误摘要,
    })


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    try:
        import os
        os.killpg(os.getpgid(进程.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        进程.wait(timeout=宽限秒)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        import os
        os.killpg(os.getpgid(进程.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        进程.wait(timeout=宽限秒)
    except subprocess.TimeoutExpired:
        pass


def 转换文本文件(输入路径: str, 目标格式: str, *, 超时秒: float = 默认超时秒,
              最大输出字节: int = 默认最大输出字节, 输出目录: str | None = None) -> 结果:
    """textutil 转换：txt/html/rtf/doc/docx 互转；返回 文本内容。"""
    if not isinstance(输入路径, str) or not 输入路径.strip():
        return _失败("参数不合法", "输入路径必须是非空文本")
    if not isinstance(目标格式, str) or not 目标格式.strip():
        return _失败("参数不合法", "目标格式必须是非空文本")
    textutil = 查找textutil()
    if not textutil:
        return _失败("提供者不可用", "textutil 不可用（macOS 系统能力缺失）")
    输入文件 = Path(输入路径)
    if not 输入文件.is_file():
        return _失败("文件不存在", f"输入文件不存在: {输入路径}")
    目标格式_clean = 目标格式.lower().lstrip(".")
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return _失败("参数不合法", "超时秒必须是正数")
    自建目录 = 输出目录 is None
    输出根 = Path(输出目录) if 输出目录 else Path(tempfile.mkdtemp(prefix="textutil_out_"))
    try:
        进程 = subprocess.Popen(
            [textutil, "-convert", 目标格式_clean, "-output",
             str(输出根 / f"{输入文件.stem}.{目标格式_clean}"), str(输入文件)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            _, 错误输出 = 进程.communicate(timeout=超时秒)
        except subprocess.TimeoutExpired:
            _终止进程组(进程)
            return _失败("超时", f"textutil 转换超时（> {超时秒} 秒）", 可重试=True)
        if 进程.returncode != 0:
            错误文本 = 错误输出.decode("utf-8", errors="replace")[-300:] if 错误输出 else ""
            return _失败("转换失败", f"textutil 退出码 {进程.returncode}: {错误文本}")
        输出文件 = 输出根 / f"{输入文件.stem}.{目标格式_clean}"
        if not 输出文件.is_file():
            return _失败("转换失败", f"textutil 未产出文件: {输出文件.name}")
        大小 = 输出文件.stat().st_size
        if 大小 > 最大输出字节:
            return _失败("超出限制", f"输出文件过大: {大小} 字节 > {最大输出字节}")
        with open(输出文件, "rb") as 流:
            文本 = 流.read().decode("utf-8", errors="replace")
        return 结果.成功结果({"文本": 文本, "格式": 目标格式_clean,
                             "字节数": 大小, "输出路径": str(输出文件)})
    except OSError as 错误:
        return _失败("转换失败", f"textutil 调用失败: {错误}")
    finally:
        if 自建目录:
            import shutil as _shutil
            _shutil.rmtree(输出根, ignore_errors=True)
