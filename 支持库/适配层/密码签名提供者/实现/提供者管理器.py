"""密码签名提供者主进程管理器：cryptography 隔离到独立子进程执行。

设计目标（Rust 原生扩展隔离）：
- 本模块绝不 import cryptography；第三方库只在 子进程入口.py 内加载
  （子进程完全自包含，不经过 适配层 包链）。
- 每次调用启动一次性子进程（独立进程组，干净环境，cwd=平台根）；
  子进程用 os._exit 退出，跳过解释器关闭阶段的原生模块销毁。
- 生命周期覆盖：启动失败→提供者不可用；执行超时→killpg 强杀→超时；
  子进程崩溃/非零退出→提供者崩溃；无有效响应→提供者崩溃；
  每次调用结束确保进程组终止、管道全部关闭，无残留进程/文件。
- 提供者不可用（cryptography 缺失/被禁用）由子进程按环境变量判定，
  本模块不操作 sys.modules，测试通过依赖注入环境变量模拟。
"""

from __future__ import annotations

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

默认超时秒 = 30.0
默认最大输出字节 = 1024 * 1024


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="密码签名提供者", 可重试=可重试)


def _启动子进程() -> subprocess.Popen:
    """启动一次性隔离子进程（独立进程组，cwd=平台根）。"""
    系统根 = 包目录.parents[2]
    return subprocess.Popen(
        [sys.executable, str(子进程入口路径)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(系统根),
        start_new_session=True,
        env=dict(os.environ),
    )


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    """SIGTERM→宽限→SIGKILL 强杀整个进程组，确保无残留。"""
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
    """执行一次子进程任务，返回统一结果。

    崩溃/超时/启动失败分别返回 提供者崩溃/超时/提供者不可用；
    调用结束后确保进程组终止、管道全部关闭，无残留。
    """
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return _失败("参数不合法", "超时秒必须是正数")
    进程 = None
    try:
        进程 = _启动子进程()
    except OSError as 错误:
        return _失败("提供者不可用", f"无法启动密码签名隔离子进程: {错误}", 可重试=True)
    请求行 = (json.dumps(请求, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        标准输出, _标准错误, 已超时, 输出超限 = 受限通信(
            进程, 输入=请求行, 超时秒=超时秒,
            输出上限字节=默认最大输出字节,
            终止回调=lambda: _终止进程组(进程),
        )
        if 已超时:
            return _失败("超时", f"密码签名隔离子进程执行超过 {超时秒} 秒", 可重试=True)
        if 输出超限:
            return _失败("超出限制", f"密码签名隔离子进程输出超过上限 {默认最大输出字节} 字节")
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
    if len(标准输出) > 默认最大输出字节:
        return _失败("超出限制", f"密码签名隔离子进程输出超过上限 {默认最大输出字节} 字节")
    if 退出码 != 0:
        return _失败("提供者崩溃", f"密码签名隔离子进程异常退出（退出码 {退出码}）", 可重试=True)
    try:
        响应 = json.loads(标准输出.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _失败("提供者崩溃", "密码签名隔离子进程返回了无效响应", 可重试=True)
    if not 响应.get("成功"):
        return _失败(
            str(响应.get("错误码") or "提供者崩溃"),
            str(响应.get("错误说明") or "密码签名隔离子进程执行失败"),
            可重试=str(响应.get("错误码")) in ("提供者不可用", "超时"),
        )
    return 结果.成功结果(响应.get("值"))


def 检查提供者版本(超时秒: float = 默认超时秒) -> 结果:
    """隔离探测 cryptography 版本（诊断/测试用，非注册能力）。"""
    return 执行任务({"操作": "版本"}, 超时秒=超时秒)


def 等待并收集(进程列表: list[subprocess.Popen], 超时秒: float = 10.0) -> None:
    """批量等待并强制清理子进程（测试与收口用）。"""
    for 进程 in 进程列表:
        try:
            if 进程.poll() is None:
                _终止进程组(进程, 宽限秒=超时秒)
        except (OSError, ValueError):
            pass
        finally:
            for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
                if 流 is not None:
                    try:
                        流.close()
                    except (OSError, ValueError):
                        pass


def 睡眠探测(秒数: float) -> None:
    """测试辅助：短等待（避免测试内裸 time.sleep 语义混淆）。"""
    time.sleep(秒数)
