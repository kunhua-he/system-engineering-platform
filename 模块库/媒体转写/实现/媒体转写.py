"""媒体转写模块：组合 FFmpeg 与 MLX Whisper 支持库公开入口。

只经 支持库.适配层.FFmpeg提供者 / MLXWhisper提供者 包级入口组合：
- FFmpeg媒体.提取音频：视频提取音频段
- 转写.*：MLX Whisper 转写段（检查可用性/转写音频文件/获取模型版本）
禁止导入支持库实现目录与第三方库；错误码与支持库一致透传。
未配置模型如实返回 未配置模型，绝不伪造转写成功。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.FFmpeg提供者 import 提取音频 as _提取音频
from 支持库.适配层.MLXWhisper提供者 import (
    检查转写可用性 as _检查转写可用性,
    获取模型版本 as _获取模型版本,
    转写音频文件 as _转写音频文件,
)

默认提取超时秒 = 60.0
默认转写超时秒 = 300.0


def 转写音频文件(文件路径: str, 超时秒: float = 默认转写超时秒,
                 取消判断=None, 配置: dict | None = None) -> 结果:
    """转写音频文件：未配置模型如实返回 未配置模型。"""
    return _转写音频文件(文件路径, 超时秒=超时秒, 取消判断=取消判断, 配置=配置)


def 检查转写可用性(超时秒: float = 默认转写超时秒,
                  配置: dict | None = None) -> 结果:
    """检查 MLX Whisper 转写可用性：模型未配置如实返回 未配置模型。"""
    return _检查转写可用性(超时秒=超时秒, 配置=配置)


def 获取模型版本(超时秒: float = 默认转写超时秒,
                配置: dict | None = None) -> 结果:
    """获取 MLX Whisper 模型与库版本；未配置 → 未配置模型。"""
    return _获取模型版本(超时秒=超时秒, 配置=配置)


def 转写视频文件(文件路径: str, 输出格式: str = "wav",
                提取超时秒: float = 默认提取超时秒,
                转写超时秒: float = 默认转写超时秒,
                取消判断=None, 配置: dict | None = None) -> 结果:
    """视频转写：自动提取音频后转写；任一段失败按支持库错误码透传。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return 结果.失败("参数不合法", "文件路径必须为非空文本", 来源="媒体转写模块")
    临时目录 = Path(tempfile.mkdtemp(prefix="媒体转写_"))
    try:
        音频路径 = str(临时目录 / ("音频." + str(输出格式 or "wav").lstrip(".")))
        音频结果 = _提取音频(文件路径, 输出格式=输出格式,
                            输出路径=音频路径, 超时秒=提取超时秒)
        if not 音频结果.成功:
            return 音频结果
        return _转写音频文件(音频路径, 超时秒=转写超时秒,
                             取消判断=取消判断, 配置=配置)
    finally:
        for 文件 in 临时目录.iterdir():
            try:
                文件.unlink()
            except OSError:
                pass
        try:
            临时目录.rmdir()
        except OSError:
            pass
