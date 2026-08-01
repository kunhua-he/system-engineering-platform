"""文档转换原子能力实现：受控调用 textutil / LibreOffice。

安全约束：
- 结构化参数列表，禁止 shell=True。
- 独立进程组，启动/执行超时，强制终止兜底。
- 输出文件大小上限与输出目录隔离。
- 临时目录、子进程、句柄在成功/失败/取消/超时路径全部释放。
- 缺少外部程序返回 提供者不可用，不伪装成功。
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

提供者_文本转换 = "textutil"
提供者_办公转换 = "libreoffice"

默认超时秒 = 60
默认最大输出字节 = 200 * 1024 * 1024
支持目标格式集合 = {
    "txt", "html", "rtf", "pdf", "docx", "pptx", "xlsx",
    "odt", "ods", "odp", "csv", "png", "jpg",
}

_提供者缓存: dict[str, str | None] = {}


def _失败(错误码: str, 消息: str, *, 可重试: bool = False, 详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源="文档转换", 可重试=可重试, 详情=详情 or {})


def _成功(值: Any = None) -> 结果:
    return 结果.成功结果(值)


def 查找提供者(提供者名: str) -> str | None:
    """查找外部程序路径（缓存）。"""
    if 提供者名 in _提供者缓存:
        return _提供者缓存[提供者名]
    候选列表: list[str | None] = []
    if 提供者名 == 提供者_文本转换:
        候选列表 = ["textutil", "/usr/bin/textutil"]
    elif 提供者名 == 提供者_办公转换:
        候选列表 = [
            os.getenv("LIBREOFFICE_BIN") or os.getenv("SOFFICE_BIN"),
            "soffice",
            "libreoffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    路径 = next((c for c in 候选列表 if c and shutil.which(c)), None)
    _提供者缓存[提供者名] = 路径
    return 路径


def 检查提供者(提供者名: str = "全部") -> 结果:
    """检查 textutil / LibreOffice 是否可用，返回版本或缺失说明。"""
    结果字典: dict[str, Any] = {}
    if 提供者名 in ("全部", 提供者_文本转换):
        textutil路径 = 查找提供者(提供者_文本转换)
        结果字典[提供者_文本转换] = "可用" if textutil路径 else "不可用"
    if 提供者名 in ("全部", 提供者_办公转换):
        office路径 = 查找提供者(提供者_办公转换)
        结果字典[提供者_办公转换] = "可用" if office路径 else "不可用"
    return _成功(结果字典)


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    """先 SIGTERM 进程组，宽限后 SIGKILL 兜底。"""
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
        return f"(输出超过上限 {最大字节数} 字节，已截断)"
    return 文件路径.read_text(encoding="utf-8", errors="replace")


def _运行进程(
    命令列表: list[str],
    *,
    超时秒: float,
    最大输出字节: int,
    工作目录: Path,
) -> tuple[int, bytes, bytes]:
    """运行子进程：独立进程组、超时、输出上限、强制终止。"""
    进程 = subprocess.Popen(
        命令列表,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(工作目录),
        start_new_session=True,
    )
    try:
        标准输出, 标准错误 = 进程.communicate(timeout=超时秒)
        if len(标准输出) > 最大输出字节:
            _终止进程组(进程)
            raise RuntimeError(f"输出超过上限 {最大输出字节} 字节")
        return 进程.returncode or 0, 标准输出, 标准错误
    except subprocess.TimeoutExpired as 错误:
        _终止进程组(进程)
        raise TimeoutError(f"进程执行超时（{超时秒} 秒）：{' '.join(命令列表)}") from 错误
    finally:
        try:
            if 进程.poll() is None:
                _终止进程组(进程)
        except (OSError, ValueError):
            pass


def 转换文本文件(
    源路径: str | Path,
    目标格式: str = "txt",
    输出目录: str | Path | None = None,
    超时秒: float = 默认超时秒,
    最大输出字节: int = 默认最大输出字节,
) -> 结果:
    """用 textutil 转换文档（doc/rtf/html 等）为文本或 HTML。"""
    来源 = Path(源路径)
    if not 来源.is_file():
        return _失败("文件不存在", f"文件不存在: {来源}")
    目标格式 = 目标格式.lower().lstrip(".")
    if 目标格式 not in {"txt", "html", "rtf"}:
        return _失败("参数不合法", f"textutil 不支持目标格式 '{目标格式}'")
    程序路径 = 查找提供者(提供者_文本转换)
    if not 程序路径:
        return _失败("提供者不可用", "macOS textutil 不可用，无法执行文本转换", 可重试=True)
    if 最大输出字节 <= 0:
        return _失败("参数不合法", "最大输出字节必须为正数")
    try:
        临时目录 = Path(tempfile.mkdtemp(prefix="平台文本转换_"))
        输出路径 = 临时目录 / f"{来源.stem}.{目标格式}"
        命令列表 = [程序路径, "-convert", 目标格式, "-output", str(输出路径), str(来源)]
        退出码, _标准输出, 标准错误 = _运行进程(
            命令列表, 超时秒=超时秒, 最大输出字节=最大输出字节, 工作目录=临时目录
        )
        if 退出码 != 0 or not 输出路径.is_file():
            return _失败(
                "转换失败",
                f"textutil 转换失败: {(标准错误 or b'').decode('utf-8', 'replace')[:300] or '输出为空'}",
            )
        文本 = _读取受限文本(输出路径, 最大输出字节)
        return _成功({"文本": 文本, "格式": 目标格式, "提供者": 提供者_文本转换})
    except TimeoutError as 错误:
        return _失败("超时", str(错误), 可重试=True)
    except OSError as 错误:
        return _失败("转换失败", f"textutil 执行异常: {错误}")
    finally:
        shutil.rmtree(临时目录, ignore_errors=True)


def 转换办公文件(
    源路径: str | Path,
    目标格式: str,
    输出目录: str | Path | None = None,
    超时秒: float = 默认超时秒,
    最大输出字节: int = 默认最大输出字节,
) -> 结果:
    """用 LibreOffice 转换 Office 文档（doc/xls/ppt 等）为目标格式。

    返回目标文件绝对路径（成功时 值=路径 文本）。
    """
    来源 = Path(源路径)
    if not 来源.is_file():
        return _失败("文件不存在", f"文件不存在: {来源}")
    目标格式 = 目标格式.lower().lstrip(".")
    if 目标格式 not in 支持目标格式集合:
        return _失败("参数不合法", f"LibreOffice 不支持目标格式 '{目标格式}'")
    程序路径 = 查找提供者(提供者_办公转换)
    if not 程序路径:
        return _失败(
            "提供者不可用",
            "LibreOffice 不可用，无法执行 Office 转换（macOS: brew install --cask libreoffice）",
            可重试=True,
        )
    if 最大输出字节 <= 0:
        return _失败("参数不合法", "最大输出字节必须为正数")
    输出目录路径 = Path(输出目录) if 输出目录 else 来源.parent
    输出目录路径.mkdir(parents=True, exist_ok=True)
    用户配置目录 = Path(tempfile.mkdtemp(prefix="平台办公配置_"))
    try:
        命令列表 = [
            程序路径,
            "--headless",
            "--norestore",
            f"-env:UserInstallation=file://{用户配置目录}",
            "--convert-to", 目标格式,
            "--outdir", str(输出目录路径),
            str(来源),
        ]
        退出码, _标准输出, 标准错误 = _运行进程(
            命令列表, 超时秒=超时秒, 最大输出字节=最大输出字节, 工作目录=输出目录路径
        )
        if 退出码 != 0:
            return _失败(
                "转换失败",
                f"LibreOffice 转换失败: {(标准错误 or b'').decode('utf-8', 'replace')[:300] or '未知错误'}",
            )
        候选文件 = list(输出目录路径.glob(f"{来源.stem}.{目标格式}"))
        if not 候选文件:
            return _失败("转换失败", f"LibreOffice 未生成目标文件 {来源.stem}.{目标格式}")
        return _成功({"路径": str(候选文件[0]), "格式": 目标格式, "提供者": 提供者_办公转换})
    except TimeoutError as 错误:
        return _失败("超时", str(错误), 可重试=True)
    except OSError as 错误:
        return _失败("转换失败", f"LibreOffice 执行异常: {错误}")
    finally:
        shutil.rmtree(用户配置目录, ignore_errors=True)
