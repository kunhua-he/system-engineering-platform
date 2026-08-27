"""MLX Whisper 转写独立提供者：配置驱动 + 受管子进程执行。
未配置模型 → 如实返回 未配置模型；模型目录缺失 → 模型缺失；绝不伪装可用、
绝不模拟转写成功。mlx_whisper 只在隔离子进程加载；转写覆盖 超时/取消/进程组回收/输出上限。"""

from __future__ import annotations

import json, os, select, signal, subprocess, sys, time
from pathlib import Path
from typing import Any, Callable

from 公共契约.基础类型.结果类型 import 结果

包目录 = Path(__file__).resolve().parent.parent
子进程入口路径 = 包目录 / "实现" / "子进程入口.py"
默认超时秒 = 300.0
默认最大输出字节 = 16 * 1024 * 1024
环境变量模型路径 = "MLXWhisper提供者_模型路径"
环境变量模型名 = "MLXWhisper提供者_模型名"


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="MLXWhisper提供者", 可重试=可重试)


def 读取模型配置(配置: dict | None = None) -> dict[str, str]:
    """读取模型配置：优先配置对象，其次环境变量（非字典一律视为空配置）。"""
    配置 = 配置 if isinstance(配置, dict) else {}
    return {"模型路径": str(配置.get("模型路径") or os.environ.get(环境变量模型路径) or "").strip(),
            "模型名": str(配置.get("模型名") or os.environ.get(环境变量模型名) or "").strip()}


def _校验配置类型(配置: Any) -> 结果 | None:
    """配置必须是 字典 或 None（跨宿主只允许可序列化数据）。"""
    if 配置 is not None and not isinstance(配置, dict):
        return _失败("参数不合法", f"配置必须是字典或 None，收到 {type(配置).__name__}")
    return None


def _检查配置(配置: dict | None) -> tuple[结果 | None, str, str]:
    """主进程判定 未配置模型/模型缺失；其余交给子进程。"""
    模型路径, 模型名 = 读取模型配置(配置).values()
    if not 模型路径 and not 模型名:
        return _失败("未配置模型", "未配置 MLX Whisper 模型（模型路径与模型名均为空）"), "", ""
    if 模型路径 and not Path(模型路径).is_dir():
        return _失败("模型缺失", f"模型目录不存在: {模型路径}"), 模型路径, 模型名
    return None, 模型路径, 模型名


def _启动子进程() -> subprocess.Popen:
    """启动一次性隔离子进程（独立进程组，cwd=平台根）。"""
    return subprocess.Popen([sys.executable, str(子进程入口路径)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(包目录.parents[3]), start_new_session=True, env=dict(os.environ))


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
    """进程组 SIGTERM→SIGKILL 强杀回收。"""
    for 终止信号 in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(进程.pid), 终止信号)
        except (OSError, ProcessLookupError):
            pass
        try:
            进程.wait(timeout=宽限秒)
            return
        except subprocess.TimeoutExpired:
            continue


def _关闭流(进程: subprocess.Popen) -> None:
    for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
        try:
            if 流 is not None:
                流.close()
        except (OSError, ValueError):
            pass


def 执行任务(请求: dict[str, Any], 超时秒: float = 默认超时秒,
            取消判断: Callable[[], bool] | None = None,
            最大输出字节: int = 默认最大输出字节) -> 结果:
    """受管子进程执行：超时/取消/输出上限/进程组回收/崩溃映射稳定错误码。"""
    try:
        进程 = _启动子进程()
    except OSError as 错误:
        return _失败("提供者不可用", f"无法启动 MLX Whisper 隔离子进程: {错误}", 可重试=True)
    流表 = {进程.stdout: b"", 进程.stderr: b""}
    结束表 = {id(进程.stdout): False, id(进程.stderr): False}
    try:
        try:
            进程.stdin.write((json.dumps(请求, ensure_ascii=False) + "\n").encode("utf-8"))
            进程.stdin.close()
        except (OSError, ValueError):
            pass
        开始 = time.monotonic()
        while True:
            if 取消判断 is not None and 取消判断():
                _终止进程组(进程)
                return _失败("取消", "转写已被调用方取消")
            if time.monotonic() - 开始 >= 超时秒:
                _终止进程组(进程)
                return _失败("超时", f"MLX Whisper 隔离子进程执行超过 {超时秒} 秒", 可重试=True)
            try:
                可读表, _, _ = select.select([流 for 流 in (进程.stdout, 进程.stderr) if 流 is not None and not 结束表[id(流)]], [], [], 0.2)
            except (OSError, ValueError):
                break
            for 流 in 可读表:
                try:
                    片段 = 流.read(65536)
                except (OSError, ValueError):
                    片段 = b""
                if not 片段:
                    结束表[id(流)] = True
                    continue
                流表[流] += 片段
                if len(流表[流]) > 最大输出字节:
                    _终止进程组(进程)
                    return _失败("超出限制", f"MLX Whisper 隔离子进程输出超过上限 {最大输出字节} 字节")
            if 进程.poll() is not None and 结束表[id(进程.stdout)] and 结束表[id(进程.stderr)]:
                break
    finally:
        if 进程.poll() is None:
            _终止进程组(进程)
        _关闭流(进程)
    if 进程.returncode:
        return _失败("进程崩溃", f"MLX Whisper 隔离子进程异常退出（退出码 {进程.returncode}）", 可重试=True)
    try:
        响应 = json.loads(流表[进程.stdout].decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _失败("进程崩溃", "MLX Whisper 隔离子进程返回了无效响应", 可重试=True)
    if not 响应.get("成功"):
        return 结果.失败(str(响应.get("错误码") or "进程崩溃"),
                          str(响应.get("错误说明") or "子进程执行失败"), 来源="MLXWhisper提供者",
                          可重试=str(响应.get("错误码")) in ("提供者不可用", "超时", "进程崩溃", "模型缺失"),
                          详情={"值": 响应.get("值")})
    return 结果.成功结果(响应.get("值"))


def 检查转写可用性(超时秒: float = 默认超时秒, 配置: dict | None = None) -> 结果:
    """检查转写可用性：未配置模型 → 未配置模型；模型缺失 → 模型缺失。"""
    类型错误 = _校验配置类型(配置)
    if 类型错误:
        return 类型错误
    错误, 模型路径, 模型名 = _检查配置(配置)
    return 错误 or 执行任务({"操作": "检查可用性", "模型路径": 模型路径, "模型名": 模型名}, 超时秒=超时秒)


def 获取模型版本(超时秒: float = 默认超时秒, 配置: dict | None = None) -> 结果:
    """获取模型与库版本：未配置模型 → 未配置模型。"""
    类型错误 = _校验配置类型(配置)
    if 类型错误:
        return 类型错误
    错误, 模型路径, 模型名 = _检查配置(配置)
    return 错误 or 执行任务({"操作": "获取模型版本", "模型路径": 模型路径, "模型名": 模型名}, 超时秒=超时秒)


def 转写音频文件(文件路径: str, 超时秒: float = 默认超时秒,
                取消判断: Callable[[], bool] | None = None,
                配置: dict | None = None) -> 结果:
    """转写音频文件：受管子进程；超时/取消/进程组回收/输出上限。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return _失败("参数不合法", "文件路径必须为非空文本")
    类型错误 = _校验配置类型(配置)
    if 类型错误:
        return 类型错误
    错误, 模型路径, 模型名 = _检查配置(配置)
    if 错误 or not Path(文件路径).is_file():
        return 错误 or _失败("文件不存在", f"音频文件不存在: {文件路径}")
    return 执行任务({"操作": "转写音频", "文件路径": 文件路径, "模型路径": 模型路径, "模型名": 模型名},
                    超时秒=超时秒, 取消判断=取消判断)


def 等待并收集(进程列表: list[subprocess.Popen], 超时秒: float = 10.0) -> None:
    for 进程 in 进程列表:
        if 进程.poll() is None:
            _终止进程组(进程, 宽限秒=超时秒)
