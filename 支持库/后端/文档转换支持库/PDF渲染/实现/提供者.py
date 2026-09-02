"""PyMuPDF 提供者主进程管理器：把 fitz（原生 SWIG 扩展）隔离到独立子进程执行。

设计目标（PyMuPDF SWIG 崩溃隔离）：
- 平台主进程绝不 import fitz；fitz 只在 子进程入口.py 内加载。
- 每次调用启动一次性子进程（干净环境，无残留）；子进程用 os._exit
  退出，跳过解释器关闭阶段的 SWIG 模块销毁，从根上消除段错误。
- 覆盖：启动失败→提供者不可用；执行超时→killpg 强杀→超时；
  子进程崩溃/非零退出→提供者崩溃；无残留进程/文件。
- 提供者不可用由子进程按环境变量判定（PyMuPDF提供者_禁用库=fitz），
  主进程不操作 sys.modules，测试通过依赖注入环境变量模拟。
"""
from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时.有界IO import 受限通信

包目录 = Path(__file__).resolve().parent.parent
子进程入口路径 = 包目录 / "实现" / "子进程入口.py"
默认超时秒 = 60.0
默认最大输出字节 = 64 * 1024 * 1024  # 整页渲染图像可能较大
def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="PyMuPDF提供者", 可重试=可重试)
def _启动子进程() -> subprocess.Popen:
    """启动一次性隔离子进程（独立进程组，cwd=平台根）。"""
    系统根 = 包目录.parents[3]
    return subprocess.Popen(
        [sys.executable, str(子进程入口路径)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(系统根), start_new_session=True, env=dict(os.environ),
    )
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
def 执行任务(请求: dict[str, Any], 超时秒: float = 默认超时秒) -> 结果:
    """执行一次子进程任务；崩溃/超时/启动失败分别映射稳定错误码。"""
    try:
        进程 = _启动子进程()
    except OSError as 错误:
        return _失败("提供者不可用", f"无法启动 PyMuPDF 隔离子进程: {错误}", 可重试=True)
    try:
        标准输出, 标准错误, 已超时, 已超限 = 受限通信(
            进程, 输入=(json.dumps(请求, ensure_ascii=False) + "\n").encode("utf-8"),
            超时秒=超时秒, 输出上限字节=默认最大输出字节,
            终止回调=lambda: _终止进程组(进程),
        )
        if 已超时:
            return _失败("超时", f"PyMuPDF 隔离子进程执行超过 {超时秒} 秒", 可重试=True)
    finally:
        try:
            if 进程.poll() is None:
                _终止进程组(进程)
        except (OSError, ValueError):
            pass
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            try:
                if 流 is not None:
                    流.close()
            except (OSError, ValueError):
                pass
    退出码 = 进程.returncode or 0
    if 已超限 or len(标准输出) > 默认最大输出字节:
        return _失败("超出限制", f"PyMuPDF 隔离子进程输出超过上限 {默认最大输出字节} 字节")
    if 退出码 != 0:
        return _失败("提供者崩溃", f"PyMuPDF 隔离子进程异常退出（退出码 {退出码}）", 可重试=True)
    try:
        响应 = json.loads(标准输出.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _失败("提供者崩溃", "PyMuPDF 隔离子进程返回了无效响应", 可重试=True)
    if not 响应.get("成功"):
        错误码 = str(响应.get("错误码") or "提供者崩溃")
        return 结果.失败(
            错误码,
            str(响应.get("错误说明") or "PyMuPDF 隔离子进程执行失败"),
            来源="PyMuPDF提供者",
            可重试=错误码 in ("提供者不可用", "超时", "提供者崩溃"),
            详情={"值": 响应.get("值")},
        )
    return 结果.成功结果(响应.get("值"))
def _校验文件路径(文件路径: Any) -> 结果 | None:
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return _失败("参数不合法", "文件路径必须为非空文本")
    if not Path(文件路径).is_file():
        return _失败("文件不存在", f"文件不存在: {文件路径}")
    return None
def _校验页序号(页序号: Any) -> 结果 | None:
    if not isinstance(页序号, int) or isinstance(页序号, bool) or 页序号 < 1:
        return _失败("参数不合法", "页序号必须为正整数（1 起始）")
    return None
def 检测加密页数(文件路径: str, 超时秒: float = 默认超时秒) -> 结果:
    """隔离检测 PDF 是否加密并返回页数（成功值 {已加密, 页数}）。"""
    错误 = _校验文件路径(文件路径)
    if 错误:
        return 错误
    return 执行任务({"操作": "检测加密页数", "文件路径": 文件路径}, 超时秒=超时秒)
def 渲染整页(文件路径: str, 页序号: int, 超时秒: float = 默认超时秒) -> 结果:
    """隔离整页渲染为 PNG 图像字节（成功值 = base64 文本）。"""
    错误 = _校验文件路径(文件路径) or _校验页序号(页序号)
    if 错误:
        return 错误
    return 执行任务({"操作": "渲染整页", "文件路径": 文件路径, "页序号": 页序号}, 超时秒=超时秒)
def 提取图像(文件路径: str, 页序号: int, 超时秒: float = 默认超时秒) -> 结果:
    """隔离提取页内嵌入图像（成功值 = [{xref, 字节b64, 尺寸}]）。"""
    错误 = _校验文件路径(文件路径) or _校验页序号(页序号)
    if 错误:
        return 错误
    return 执行任务({"操作": "提取图像", "文件路径": 文件路径, "页序号": 页序号}, 超时秒=超时秒)
def 校验PDF(字节, 超时秒: float = 30.0) -> 结果:
    """隔离重新打开 PDF 返回页数（成功值 {页数}，签名校验用）。"""
    if isinstance(字节, bytes) and 字节:
        字节b64 = base64.b64encode(字节).decode("ascii")
    elif isinstance(字节, str) and 字节:
        字节b64 = 字节
    elif isinstance(字节, dict) and isinstance(字节.get("base64"), str):
        字节b64 = 字节["base64"]
    else:
        return _失败("参数不合法", "字节必须为非空字节集或Base64文本")
    return 执行任务({
        "操作": "校验PDF",
        "字节b64": 字节b64,
    }, 超时秒=超时秒)
def 等待并收集(进程列表: list[subprocess.Popen], 超时秒: float = 10.0) -> None:
    """批量等待并强制清理子进程（测试与收口用）。"""
    for 进程 in 进程列表:
        try:
            if 进程.poll() is None:
                _终止进程组(进程, 宽限秒=超时秒)
        except (OSError, ValueError):
            pass
def 睡眠探测(秒数: float) -> None:
    """测试辅助：短等待（避免测试内裸 time.sleep 语义混淆）。"""
    time.sleep(秒数)
