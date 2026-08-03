"""Pillow 提供者主进程管理器：把 PIL（C 原生扩展）隔离到独立子进程执行。

平台主进程绝不 import PIL；每次调用启动一次性子进程（独立进程组），
os._exit 退出零残留；启动失败/超时/崩溃/输出超限逐类映射稳定错误码。
提供者不可用由子进程按环境变量判定（Pillow提供者_禁用库=PIL）。
"""
from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果

包目录 = Path(__file__).resolve().parent.parent
子进程入口路径 = 包目录 / "实现" / "子进程入口.py"
默认超时秒 = 60.0
默认最大输出字节 = 64 * 1024 * 1024
输入字节上限 = 64 * 1024 * 1024


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="Pillow提供者", 可重试=可重试)


def _启动子进程() -> subprocess.Popen:
    """启动一次性隔离子进程（独立进程组，cwd=平台根）。"""
    系统根 = 包目录.parents[2]
    return subprocess.Popen(
        [sys.executable, str(子进程入口路径)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(系统根), start_new_session=True, env=dict(os.environ),
    )


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    for 信号值 in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(进程.pid), 信号值)
        except (OSError, ProcessLookupError):
            pass
        try:
            进程.wait(timeout=宽限秒)
            return
        except subprocess.TimeoutExpired:
            pass


def _关闭流(进程: subprocess.Popen) -> None:
    for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
        try:
            if 流 is not None:
                流.close()
        except (OSError, ValueError):
            pass


def 执行任务(请求: dict[str, Any], 超时秒: float = 默认超时秒) -> 结果:
    """执行一次子进程任务；崩溃/超时/启动失败分别映射稳定错误码。"""
    try:
        进程 = _启动子进程()
    except OSError as 错误:
        return _失败("提供者不可用", f"无法启动 Pillow 隔离子进程: {错误}", 可重试=True)
    try:
        标准输出, _标准错误 = 进程.communicate(
            input=(json.dumps(请求, ensure_ascii=False) + "\n").encode("utf-8"),
            timeout=超时秒,
        )
    except subprocess.TimeoutExpired:
        _终止进程组(进程)
        return _失败("超时", f"Pillow 隔离子进程执行超过 {超时秒} 秒", 可重试=True)
    finally:
        if 进程.poll() is None:
            _终止进程组(进程)
        _关闭流(进程)
    退出码 = 进程.returncode or 0
    if len(标准输出) > 默认最大输出字节:
        return _失败("超大", f"Pillow 隔离子进程输出超过上限 {默认最大输出字节} 字节")
    if 退出码 != 0:
        return _失败("提供者崩溃", f"Pillow 隔离子进程异常退出（退出码 {退出码}）", 可重试=True)
    try:
        响应 = json.loads(标准输出.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _失败("提供者崩溃", "Pillow 隔离子进程返回了无效响应", 可重试=True)
    if not 响应.get("成功"):
        错误码 = str(响应.get("错误码") or "提供者崩溃")
        return 结果.失败(错误码, str(响应.get("错误说明") or "Pillow 隔离子进程执行失败"),
                          来源="Pillow提供者",
                          可重试=错误码 in ("提供者不可用", "超时", "提供者崩溃"),
                          详情={"值": 响应.get("值")})
    return 结果.成功结果(响应.get("值"))


def _校验字节(字节: Any) -> 结果 | None:
    if not isinstance(字节, bytes) or not 字节:
        return _失败("参数不合法", "字节必须为非空二进制")
    if len(字节) > 输入字节上限:
        return _失败("超大", f"图像字节超过上限 {输入字节上限} 字节")
    return None


def _校验宽高(宽度: Any, 高度: Any) -> 结果 | None:
    if not isinstance(宽度, int) or isinstance(宽度, bool) or 宽度 < 1:
        return _失败("参数不合法", "宽度必须为正整数")
    if not isinstance(高度, int) or isinstance(高度, bool) or 高度 < 1:
        return _失败("参数不合法", "高度必须为正整数")
    return None


def 解码图像(字节: bytes, 超时秒: float = 默认超时秒) -> 结果:
    """隔离解码图像字节：成功值 {格式, 宽度, 高度, 模式}。"""
    错误 = _校验字节(字节)
    if 错误:
        return 错误
    return 执行任务({"操作": "解码图像", "字节b64": base64.b64encode(字节).decode("ascii")},
                    超时秒=超时秒)


def 像素统计(字节: bytes, 超时秒: float = 默认超时秒) -> 结果:
    """隔离统计像素：成功值 {宽度, 高度, 像素数, 平均颜色}。"""
    错误 = _校验字节(字节)
    if 错误:
        return 错误
    return 执行任务({"操作": "像素统计", "字节b64": base64.b64encode(字节).decode("ascii")},
                    超时秒=超时秒)


def 生成占位图(宽度: int, 高度: int, 占位类型: str = "纯色",
               背景颜色: str = "#CCCCCC", 前景颜色: str = "#333333",
               文本: str = "", 超时秒: float = 默认超时秒) -> 结果:
    """隔离生成占位图：成功值 {图像b64, 格式, 宽度, 高度}。"""
    错误 = _校验宽高(宽度, 高度)
    if 错误:
        return 错误
    if not isinstance(占位类型, str) or 占位类型 not in ("纯色", "渐变", "文本"):
        return _失败("参数不合法", "占位类型必须是 纯色/渐变/文本")
    return 执行任务({
        "操作": "生成占位图", "宽度": 宽度, "高度": 高度, "占位类型": 占位类型,
        "背景颜色": 背景颜色, "前景颜色": 前景颜色, "文本": 文本,
    }, 超时秒=超时秒)


def 等待并收集(进程列表: list[subprocess.Popen], 超时秒: float = 10.0) -> None:
    """批量等待并强制清理子进程（测试与收口用）。"""
    for 进程 in 进程列表:
        try:
            if 进程.poll() is None:
                _终止进程组(进程, 宽限秒=超时秒)
        except (OSError, ValueError):
            pass
