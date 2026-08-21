"""本地大模型对话提供者（主进程宿主侧）。

模型路径/模型名来自配置（环境变量或配置对象），MLX/Ollama 只在隔离子进程加载。
未配置模型如实返回 未配置模型，绝不伪装可用或模拟生成成功。
生成受管子进程（超时/取消/进程组回收/输出上限）。
"""

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果

包目录 = Path(__file__).resolve().parent.parent
子进程入口路径 = 包目录 / "实现" / "子进程入口.py"
默认超时秒 = 600.0
默认最大输出字节 = 16 * 1024 * 1024
环境变量模型路径 = "本地LLM提供者_模型路径"
环境变量模型名 = "本地LLM提供者_模型名"


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源="本地LLM提供者", 可重试=可重试)


def 读取模型配置(配置: dict | None = None) -> dict[str, str]:
    配置 = 配置 if isinstance(配置, dict) else {}
    return {
        "模型路径": str(配置.get("模型路径") or os.environ.get(环境变量模型路径) or "").strip(),
        "模型名": str(配置.get("模型名") or os.environ.get(环境变量模型名) or "").strip(),
    }


def _校验配置类型(配置) -> 结果 | None:
    if 配置 is not None and not isinstance(配置, dict):
        return _失败("参数不合法", "配置必须是字典或 None")
    return None


def _检查配置(配置: dict | None):
    配置 = 读取模型配置(配置)
    模型路径 = 配置["模型路径"]
    模型名 = 配置["模型名"]
    if not 模型路径 and not 模型名:
        return _失败("未配置模型", "未配置模型路径或模型名", 可重试=False), "", ""
    模型路径对象 = Path(模型路径) if 模型路径 else None
    if 模型路径对象 is not None and not 模型路径对象.is_dir():
        return _失败("模型缺失", f"模型路径不是目录: {模型路径}"), 模型路径, 模型名
    return None, 模型路径, 模型名


def _启动子进程() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(子进程入口路径)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(包目录.parents[2]),
        start_new_session=True,
        env=dict(os.environ),
    )


def _终止进程组(进程: subprocess.Popen, 宽限秒: float = 1.0) -> None:
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


def 执行任务(
    请求: dict,
    超时秒: float = 默认超时秒,
    取消判断=None,
    最大输出字节: int = 默认最大输出字节,
) -> 结果:
    try:
        进程 = _启动子进程()
    except OSError as 错误对象:
        return _失败("提供者不可用", f"无法启动子进程: {错误对象}", 可重试=True)
    流表 = {进程.stdout: b"", 进程.stderr: b""}
    try:
        进程.stdin.write((json.dumps(请求, ensure_ascii=False) + "\n").encode("utf-8"))
        进程.stdin.close()
        开始 = time.monotonic()
        while True:
            if 取消判断 is not None and 取消判断():
                _终止进程组(进程)
                return _失败("取消", "调用被取消")
            if time.monotonic() - 开始 >= 超时秒:
                _终止进程组(进程)
                return _失败("超时", f"子进程超过 {超时秒} 秒未完成", 可重试=True)
            存活流 = [流 for 流 in 流表 if 流 is not None and 进程.poll() is None]
            if not 存活流:
                if 进程.poll() is not None:
                    break
            else:
                try:
                    可读, _, _ = select.select(存活流, [], [], 0.2)
                except (OSError, ValueError):
                    可读 = []
                for 流 in 可读:
                    try:
                        块 = os.read(流.fileno(), 65536)
                    except (OSError, ValueError):
                        块 = b""
                    流表[流] += 块
                    if len(流表[流]) > 最大输出字节:
                        _终止进程组(进程)
                        return _失败("超出限制", "子进程输出超过上限")
            if 进程.poll() is not None and (进程.stdout is None or 流表[进程.stdout] is not None):
                break
    finally:
        if 进程.poll() is None:
            _终止进程组(进程)
        _关闭流(进程)
    if 进程.returncode:
        return _失败("进程崩溃", f"子进程退出码 {进程.returncode}", 可重试=True)
    try:
        响应 = json.loads(流表[进程.stdout].decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, KeyError):
        return _失败("进程崩溃", "子进程返回无效 JSON", 可重试=True)
    if not 响应.get("成功"):
        return 结果.失败(
            响应.get("错误码") or "进程崩溃",
            响应.get("错误说明") or "子进程返回失败",
            来源="本地LLM提供者",
            可重试=响应.get("错误码") in ("提供者不可用", "超时", "进程崩溃", "模型缺失"),
            详情={"值": 响应.get("值")},
        )
    return 结果.成功结果(响应.get("值"))


def 检查可用性(超时秒: float = 默认超时秒, 配置=None) -> 结果:
    校验 = _校验配置类型(配置)
    if 校验 is not None:
        return 校验
    检查, 模型路径, 模型名 = _检查配置(配置)
    if 检查 is not None:
        return 检查
    return 执行任务({"操作": "检查可用性", "模型路径": 模型路径, "模型名": 模型名}, 超时秒=超时秒)


def 获取模型信息(超时秒: float = 默认超时秒, 配置=None) -> 结果:
    校验 = _校验配置类型(配置)
    if 校验 is not None:
        return 校验
    检查, 模型路径, 模型名 = _检查配置(配置)
    if 检查 is not None:
        return 检查
    return 执行任务({"操作": "获取模型信息", "模型路径": 模型路径, "模型名": 模型名}, 超时秒=超时秒)


def 生成(
    提示: str,
    系统提示: str = "",
    最大生成token: int = 2048,
    温度: float = 0.7,
    超时秒: float = 默认超时秒,
    配置=None,
    取消判断=None,
) -> 结果:
    if not isinstance(提示, str) or not 提示.strip():
        return _失败("参数不合法", "提示不能为空")
    校验 = _校验配置类型(配置)
    if 校验 is not None:
        return 校验
    检查, 模型路径, 模型名 = _检查配置(配置)
    if 检查 is not None:
        return 检查
    if not isinstance(最大生成token, int) or 最大生成token <= 0:
        return _失败("参数不合法", "最大生成token 必须为正整数")
    if not isinstance(温度, (int, float)) or not (0 <= 温度 <= 2):
        return _失败("参数不合法", "温度 必须在 0~2 之间")
    return 执行任务(
        {
            "操作": "生成",
            "提示": 提示,
            "系统提示": 系统提示,
            "最大生成token": int(最大生成token),
            "温度": float(温度),
            "模型路径": 模型路径,
            "模型名": 模型名,
        },
        超时秒=超时秒,
        取消判断=取消判断,
    )