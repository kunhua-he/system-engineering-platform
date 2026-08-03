"""系统级提供者健康探针：独立子进程检查外部应用/系统工具。

LibreOffice（soffice）与 textutil（macOS 系统工具）不是 pip 包，
没有独立 venv 可做 import 校验；健康检查必须真实启动独立子进程
执行版本/帮助参数，带回 退出码/版本信息/标准错误摘要/耗时。

探针四要素：超时、退出码、版本信息、标准错误摘要。
隔离性：探针在独立子进程（新会话）运行，超时 terminate→kill 强杀；
任何失败都收敛为 探针结果 返回，绝不向调用方抛异常拖垮主进程。
不可用语义：工具缺失/探针超时/退出码非0 → 成功=False + 明确错误码；
提供者入口统一映射为「外部提供者不可用」。
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

版本行最大长度 = 200
标准错误摘要最大长度 = 300
终止宽限秒 = 1.0


@dataclass(frozen=True)
class 探针结果:
    """系统工具独立进程探针结果（成功=False 时不抛异常，只返回结果）。"""

    成功: bool
    错误码: str = ""           # 参数不合法/工具缺失/探针超时/退出码非零
    退出码: int | None = None  # 子进程退出码（成功为 0；超时/缺失为 None）
    版本: str = ""             # 版本信息（成功时取输出首行的版本号）
    标准错误摘要: str = ""     # 标准错误截断摘要
    耗时秒: float = 0.0
    诊断: str = ""


def 检查系统工具(名称: str, 命令列表: list[str], *, 超时秒: float = 5.0,
               版本参数: str = "--version") -> 探针结果:
    """独立子进程健康探针：执行 命令列表+版本参数，返回 探针结果。

    参数：
        名称：工具显示名（用于诊断信息）。
        命令列表：可执行文件路径与前置参数（可执行文件缺省由 PATH 解析）。
        超时秒：探针最大耗时（正数，超时 terminate→kill）。
        版本参数：版本探测参数（默认 --version，可传 -help 等）。
    返回：探针结果（成功/退出码/版本/标准错误摘要/耗时秒/诊断）；
    失败不抛异常，主进程不受影响。
    """
    if not isinstance(名称, str) or not 名称.strip():
        return 探针结果(False, 错误码="参数不合法", 诊断="名称必须是非空文本")
    if (not isinstance(命令列表, list) or not 命令列表
            or not all(isinstance(项, str) and 项.strip() for 项 in 命令列表)):
        return 探针结果(False, 错误码="参数不合法", 诊断="命令列表必须是非空文本列表")
    if (not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0):
        return 探针结果(False, 错误码="参数不合法", 诊断="超时秒必须是正数")
    if not isinstance(版本参数, str) or not 版本参数.strip():
        return 探针结果(False, 错误码="参数不合法", 诊断="版本参数必须是非空文本")
    可执行 = 命令列表[0]
    可执行路径 = _解析可执行(可执行)
    if not 可执行路径:
        return 探针结果(False, 错误码="工具缺失",
                         诊断=f"未找到 {名称}（{可执行} 不在 PATH 或路径不存在）")
    开始 = time.monotonic()
    try:
        进程 = subprocess.Popen(
            list(命令列表) + [版本参数],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as 错误:
        return 探针结果(False, 错误码="工具缺失",
                         诊断=f"无法启动 {名称}: {错误}")
    try:
        try:
            标准输出, 标准错误 = 进程.communicate(timeout=超时秒)
        except subprocess.TimeoutExpired:
            _终止进程组(进程)
            return 探针结果(
                False, 错误码="探针超时", 耗时秒=time.monotonic() - 开始,
                诊断=f"{名称} 探针超时（> {超时秒} 秒），已强制终止",
            )
        退出码 = 进程.returncode
        耗时秒 = time.monotonic() - 开始
        错误摘要 = _标准错误摘要(标准错误)
        if 退出码 != 0:
            return 探针结果(
                False, 错误码="退出码非零", 退出码=退出码,
                标准错误摘要=错误摘要, 耗时秒=耗时秒,
                诊断=f"{名称} 退出码 {退出码}",
            )
        输出文本 = _解码(标准输出) or _解码(标准错误)
        return 探针结果(
            True, 退出码=0, 版本=_提取版本(输出文本),
            标准错误摘要=错误摘要, 耗时秒=耗时秒,
            诊断=f"{名称} 探针成功",
        )
    finally:
        # 成功/退出码非0 已由 communicate 回收；超时路径已强杀并 wait 回收
        if 进程.poll() is None:
            _终止进程组(进程)


def _解析可执行(可执行: str) -> str | None:
    """可执行路径解析：含路径分隔符按文件校验，否则按 PATH 查找。"""
    if os.path.sep in 可执行 or 可执行.startswith("~"):
        路径 = Path(可执行).expanduser()
        return str(路径) if 路径.is_file() else None
    return shutil.which(可执行)


def _解码(字节: bytes | None) -> str:
    """字节转文本（替换非法序列，去首尾空白）。"""
    if not 字节:
        return ""
    return 字节.decode("utf-8", errors="replace").strip()


def _提取版本(文本: str) -> str:
    """从输出首行提取版本信息：优先数字点序列（如 26.2.2.2），
    无版本号时返回首行清洗文本（textutil -help 类输出）。"""
    if not 文本:
        return ""
    首行 = next((行 for 行 in 文本.splitlines() if 行.strip()), "").strip()
    匹配 = re.search(r"\d+(?:\.\d+)+", 首行)
    return (匹配.group(0) if 匹配 else 首行)[:版本行最大长度]


def _标准错误摘要(标准错误: bytes | None) -> str:
    """标准错误截断摘要（单行化，超长截断）。"""
    if not 标准错误:
        return ""
    文本 = 标准错误.decode("utf-8", errors="replace").strip()
    return " | ".join(行.strip() for 行 in 文本.splitlines() if 行.strip())[
        :标准错误摘要最大长度
    ]


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 终止宽限秒) -> None:
    """超时强杀：先 SIGTERM 进程组，宽限后 SIGKILL。"""
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
