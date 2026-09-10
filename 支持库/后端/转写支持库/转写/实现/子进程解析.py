"""子进程解析逻辑：在隔离子进程内执行 mlx-whisper 转写操作。

本模块只在子进程中导入；这里才允许加载 mlx_whisper，崩溃不影响主进程。
未配置模型/模型缺失如实返回对应错误码，绝不伪装可用或模拟转写成功。
成功 {"值": ...}；失败 {"错误码": ..., "错误说明": ..., "值": ...}。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

禁用库环境变量名 = "MLXWhisper提供者_禁用库"
_库模块 = None  # 子进程内惰性加载；主进程绝不加载


def _加载库(禁用库表: set[str]) -> Any:
    """加载 mlx_whisper；禁用或缺失返回 None（提供者不可用）。"""
    global _库模块
    if "mlx_whisper" in 禁用库表:
        _库模块 = None
        return None
    try:
        import mlx_whisper
        _库模块 = mlx_whisper
    except Exception:
        _库模块 = None
    return _库模块


def 初始化(禁用库表: set[str]) -> bool:
    return _加载库(禁用库表) is not None


def _不可用() -> dict[str, Any]:
    return {"错误码": "提供者不可用", "错误说明": "mlx_whisper 库不可用，无法执行转写", "可重试": True}


def _未配置() -> dict[str, Any]:
    return {"错误码": "未配置模型", "错误说明": "未配置 MLX Whisper 模型（模型路径与模型名均为空）"}


def _模型缺失(模型路径: str) -> dict[str, Any]:
    return {"错误码": "模型缺失", "错误说明": f"模型目录不存在: {模型路径}"}


def _检查模型(模型路径: str, 模型名: str) -> tuple[str, str, dict | None]:
    模型路径 = (模型路径 or "").strip()
    模型名 = (模型名 or "").strip()
    if not 模型路径 and not 模型名:
        return 模型路径, 模型名, _未配置()
    if 模型路径 and not Path(模型路径).is_dir():
        return 模型路径, 模型名, _模型缺失(模型路径)
    return 模型路径, 模型名, None


def 检查可用性(模型路径: str, 模型名: str) -> dict[str, Any]:
    """转写可用性探针：只查库版本与模型配置，不加载模型权重。"""
    if _库模块 is None:
        return _不可用()
    模型路径, 模型名, 错误 = _检查模型(模型路径, 模型名)
    if 错误:
        return 错误
    return {"值": {
        "可用": True,
        "模型名": 模型名 or 模型路径,
        "模型版本": str(getattr(_库模块, "__version__", "未知")),
    }}


def 获取模型版本(模型路径: str, 模型名: str) -> dict[str, Any]:
    """获取模型与库版本；未配置 → 未配置模型。"""
    if _库模块 is None:
        return _不可用()
    模型路径, 模型名, 错误 = _检查模型(模型路径, 模型名)
    if 错误:
        return 错误
    return {"值": {
        "模型名": 模型名 or 模型路径,
        "模型版本": str(getattr(_库模块, "__version__", "未知")),
    }}


def 转写音频(文件路径: str, 模型路径: str, 模型名: str, 附加术语: str = "") -> dict[str, Any]:
    """转写音频文件；失败逐类映射稳定错误码，不伪装成功。"""
    if _库模块 is None:
        return _不可用()
    文件 = Path(文件路径)
    if not 文件.is_file():
        return {"错误码": "文件不存在", "错误说明": f"音频文件不存在: {文件路径}"}
    模型路径, 模型名, 错误 = _检查模型(模型路径, 模型名)
    if 错误:
        return 错误
    目标 = 模型路径 or 模型名
    try:
        参数 = {"path_or_hf_repo": 目标}
        if 附加术语:
            参数["initial_prompt"] = 附加术语
        结果 = _库模块.transcribe(str(文件), **参数)
    except Exception as 错误对象:
        return {"错误码": "转写失败", "错误说明": f"转写失败: {错误对象}"}
    if not isinstance(结果, dict) or not str(结果.get("text") or "").strip():
        return {"错误码": "转写失败", "错误说明": "转写未返回文本"}
    语言 = str(结果.get("language") or "")
    return {"值": {
        "文本": str(结果["text"]).strip(),
        "语言": 语言,
        "模型名": 模型名 or 模型路径,
    }}
