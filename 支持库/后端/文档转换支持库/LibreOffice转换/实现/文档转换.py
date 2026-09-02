"""LibreOffice 文档转换独立提供者：外部应用（soffice）受控调用。

只封装 LibreOffice 转换能力：doc/xls/ppt → 现代格式、任意格式 → pdf 等。
安全约束：结构化参数列表（禁 shell=True）；独立进程组；启动/执行超时+
强制终止兜底；输出文件大小上限与输出目录隔离；临时目录/子进程/句柄全路径释放；
缺少 LibreOffice 返回 提供者不可用，不伪装成功。
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.有界IO import 受限通信, 默认子进程输出上限字节

默认超时秒 = 60
默认最大输出字节 = 200 * 1024 * 1024
来源 = "LibreOffice提供者"

_提供者缓存: dict[str, str | None] = {}


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试)


def 查找LibreOffice() -> str | None:
    """查找 soffice 可执行文件（缓存）。"""
    if "soffice" in _提供者缓存:
        return _提供者缓存["soffice"]
    候选列表 = [
        os.getenv("LIBREOFFICE_BIN") or os.getenv("SOFFICE_BIN"),
        "soffice", "libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    路径 = next((c for c in 候选列表 if c and shutil.which(c)), None)
    _提供者缓存["soffice"] = 路径
    return 路径


def 检查提供者(超时秒: float = 30) -> 结果:
    """检查 LibreOffice 是否可用（真实独立进程探针：soffice --version）。

    探针失败（工具缺失/超时/退出码非0）→ 外部提供者不可用，
    不伪装成环境未构建。
    """
    from 支持库.适配层.系统探针 import 检查系统工具
    路径 = 查找LibreOffice()
    if not 路径:
        return _失败("外部提供者不可用", "LibreOffice 未找到（未安装或不在 PATH）")
    探针 = 检查系统工具("LibreOffice soffice", [路径], 超时秒=超时秒)
    if not 探针.成功:
        return _失败("外部提供者不可用",
                      f"LibreOffice 探针失败（{探针.错误码}）: {探针.诊断}")
    return 结果.成功结果({
        "LibreOffice": "可用",
        "版本": 探针.版本,
        "退出码": 探针.退出码,
        "标准错误摘要": 探针.标准错误摘要,
    })


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    try:
        os.killpg(os.getpgid(进程.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        进程.wait(timeout=宽限秒)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(进程.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        进程.wait(timeout=宽限秒)
    except subprocess.TimeoutExpired:
        pass


def _读取受限文本(文件路径: Path, 最大字节数: int) -> str:
    """读取文本文件但限制最大字节，超限截断并记录截断标记。"""
    大小 = 文件路径.stat().st_size
    if 大小 > 最大字节数:
        with open(文件路径, "rb") as 流:
            return 流.read(最大字节数).decode("utf-8", errors="replace") + "\n[已截断]"
    return 文件路径.read_text(encoding="utf-8", errors="replace")


def 转换办公文件(输入路径: str, 目标格式: str, *, 超时秒: float = 默认超时秒,
              最大输出字节: int = 默认最大输出字节, 输出目录: str | None = None) -> 结果:
    """LibreOffice 转换：doc/xls/ppt → 目标格式；返回 文本内容或字节b64。"""
    if not isinstance(输入路径, str) or not 输入路径.strip():
        return _失败("参数不合法", "输入路径必须是非空文本")
    if not isinstance(目标格式, str) or not 目标格式.strip():
        return _失败("参数不合法", "目标格式必须是非空文本")
    soffice = 查找LibreOffice()
    if not soffice:
        return _失败("提供者不可用", "LibreOffice 未安装（提供者不可用）")
    输入文件 = Path(输入路径)
    if not 输入文件.is_file():
        return _失败("文件不存在", f"输入文件不存在: {输入路径}")
    目标格式_clean = 目标格式.lower().lstrip(".")
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return _失败("参数不合法", "超时秒必须是正数")
    if not isinstance(最大输出字节, int) or 最大输出字节 <= 0:
        return _失败("参数不合法", "最大输出字节必须是正整数")
    # 临时输出目录（隔离）
    自建目录 = 输出目录 is None
    输出根 = Path(输出目录) if 输出目录 else Path(tempfile.mkdtemp(prefix="lo_out_"))
    try:
        进程 = subprocess.Popen(
            [soffice, "--headless", "--convert-to", 目标格式_clean,
             "--outdir", str(输出根), str(输入文件)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            标准输出, 错误输出, 已超时, 已超限 = 受限通信(
                进程, 超时秒=超时秒,
                输出上限字节=min(最大输出字节, 默认子进程输出上限字节),
                终止回调=lambda: _终止进程组(进程),
            )
            if 已超时:
                return _失败("超时", f"LibreOffice 转换超时（> {超时秒} 秒）", 可重试=True)
            if 已超限:
                return _失败("超出限制", "LibreOffice 子进程输出超过上限")
        except OSError as 错误:
            return _失败("转换失败", f"LibreOffice 调用失败: {错误}")
        退出码 = 进程.returncode
        if 退出码 != 0:
            错误文本 = 错误输出.decode("utf-8", errors="replace")[-300:] if 错误输出 else ""
            return _失败("转换失败", f"LibreOffice 退出码 {退出码}: {错误文本}")
        # 找输出文件：目标格式同名
        输出文件 = 输出根 / f"{输入文件.stem}.{目标格式_clean}"
        if not 输出文件.is_file():
            return _失败("转换失败", f"LibreOffice 未产出文件: {输出文件.name}")
        # 文本格式读文本，二进制格式回字节b64
        import base64
        大小 = 输出文件.stat().st_size
        if 大小 > 最大输出字节:
            return _失败("超出限制", f"输出文件过大: {大小} 字节 > {最大输出字节}")
        if 目标格式_clean in ("txt", "csv", "html", "rtf", "odt", "ods", "odp", "xml"):
            文本 = _读取受限文本(输出文件, 最大输出字节)
            return 结果.成功结果({"文本": 文本, "格式": 目标格式_clean,
                                  "字节数": 大小, "输出路径": str(输出文件)})
        字节 = 输出文件.read_bytes()
        return 结果.成功结果({"字节b64": base64.b64encode(字节).decode("ascii"),
                             "格式": 目标格式_clean, "字节数": 大小,
                             "输出路径": str(输出文件)})
    except OSError as 错误:
        return _失败("转换失败", f"LibreOffice 调用失败: {错误}")
    finally:
        if 自建目录:
            import shutil as _shutil
            _shutil.rmtree(输出根, ignore_errors=True)
