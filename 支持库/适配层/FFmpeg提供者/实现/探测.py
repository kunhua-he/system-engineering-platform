"""FFmpeg 媒体提供者·探测侧：外部命令查找、ffprobe 探测媒体、检查提供者。

对外部命令 ffprobe 一律经 进程管理.执行受管命令 受管调用（独立进程组/
超时/取消/输出上限截断）。缺少 ffprobe 返回 提供者不可用（未配置语义），
不伪装可用；损坏媒体由 ffprobe 退出码非零 映射。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.FFmpeg提供者.实现.进程管理 import 执行受管命令

来源 = "FFmpeg提供者"
默认超时秒 = 60.0
命令输出上限 = 1024 * 1024  # 外部命令 stdout/stderr 受限读取上限（截断防阻塞）
_命令缓存: dict[str, str | None] = {}


def _失败(错误码: str, 消息: str, *, 可重试: bool = False) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试)


def 查找命令(命令名: str) -> str | None:
    """查找 ffmpeg/ffprobe 可执行（环境变量 FFMPEG_BIN/FFPROBE_BIN 优先，PATH 兜底，缓存）。"""
    if 命令名 in _命令缓存:
        return _命令缓存[命令名]
    候选 = [os.getenv(f"{命令名.upper()}_BIN"), 命令名]
    路径 = next((项 for 项 in 候选 if 项 and shutil.which(项)), None)
    _命令缓存[命令名] = 路径
    return 路径


def 校验基本参数(文件路径: Any, 超时秒: Any, 输出路径: Any = None) -> 结果 | None:
    """文件路径/超时秒/输出路径 统一校验；任一非法 → 参数不合法/文件不存在。"""
    if not isinstance(文件路径, str) or not 文件路径.strip():
        return _失败("参数不合法", "文件路径必须是非空文本")
    if not Path(文件路径).is_file():
        return _失败("文件不存在", f"文件不存在: {文件路径}")
    if (not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0):
        return _失败("参数不合法", "超时秒必须是正数")
    if 输出路径 is not None and (not isinstance(输出路径, str) or not 输出路径.strip()):
        return _失败("参数不合法", "输出路径必须是非空文本或 None")
    return None


def 检查提供者(超时秒: float = 30.0) -> 结果:
    """检查 ffmpeg/ffprobe 可用性（真实独立进程版本探针），缺失 → 提供者不可用。"""
    if not isinstance(超时秒, (int, float)) or isinstance(超时秒, bool) or 超时秒 <= 0:
        return _失败("参数不合法", "超时秒必须是正数")
    ffmpeg路径 = 查找命令("ffmpeg")
    ffprobe路径 = 查找命令("ffprobe")
    if not ffmpeg路径 or not ffprobe路径:
        return _失败("提供者不可用", "ffmpeg/ffprobe 未找到（未配置提供者）")
    版本信息 = {}
    不可用 = []
    for 名称, 路径 in (("ffmpeg", ffmpeg路径), ("ffprobe", ffprobe路径)):
        探针 = 执行受管命令([路径, "-version"], 超时秒=min(float(超时秒), 5.0), 最大输出字节=8192)
        if 探针.成功:
            首行 = (探针.标准输出.decode("utf-8", errors="replace").strip().splitlines() or [""])[0]
            版本信息[名称] = 首行[:120]
        else:
            版本信息[名称] = 探针.错误摘要[:120]
            不可用.append(f"{名称}: {探针.错误摘要[:80]}")
    if 不可用:
        # 探针失败必须报不可用：二进制在 PATH 里但跑不起来（缺动态库/被拦截/
        # 超时）时，无条件报「可用」会让调用方拿到假绿。
        return _失败("提供者不可用", "版本探针失败（" + "；".join(不可用) + "）")
    return 结果.成功结果({"ffmpeg": "可用", "ffprobe": "可用", "版本": 版本信息})


def _转浮点(值: Any) -> float:
    try:
        return float(值) if 值 not in (None, "N/A") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _转整数(值: Any) -> int:
    """字节数/比特率归一到整数型（契约声明：`大小字节`/`比特率` 为 整数型）。

    ffprobe 以文本给出这些量，旧实现一律 `_转浮点`，把 7599.0 这种浮点值当整数型字段
    返回——契约声明与实现两套口径（2026-09-16 HTML 黑盒开真比对后暴露）。
    """
    return int(_转浮点(值))


def 探测元数据(文件路径: str, 超时秒: float = 默认超时秒) -> 结果:
    """ffprobe 探测媒体 JSON：成功值 {时长秒, 格式, 大小字节, 比特率, 流}。

    失败映射：ffprobe 缺失 → 提供者不可用；退出码非零/输出不可解析 → 损坏媒体；
    超时/取消/进程崩溃 → 同错误码。
    """
    ffprobe = 查找命令("ffprobe")
    if not ffprobe:
        return _失败("提供者不可用", "ffprobe 未安装（提供者不可用）")
    受管 = 执行受管命令(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", 文件路径],
        超时秒=超时秒, 最大输出字节=命令输出上限)
    if not 受管.成功:
        if 受管.错误码 == "进程崩溃":
            return _失败("损坏媒体", f"ffprobe 无法解析媒体: {受管.错误摘要}")
        return _失败(受管.错误码, f"ffprobe 探测失败: {受管.错误摘要}",
                      可重试=受管.错误码 in ("超时", "提供者不可用"))
    try:
        数据 = json.loads(受管.标准输出.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _失败("损坏媒体", "ffprobe 返回了无法解析的输出")
    格式 = 数据.get("format", {}) or {}
    流列表 = []
    for 流 in 数据.get("streams", []) or []:
        流列表.append({
            "索引": 流.get("index"), "类型": 流.get("codec_type"),
            "编码": 流.get("codec_name"), "宽度": 流.get("width"),
            "高度": 流.get("height"), "采样率": 流.get("sample_rate"),
            "声道数": 流.get("channels"),
        })
    if not 流列表 and not 格式.get("format_name"):
        return _失败("损坏媒体", "ffprobe 返回空媒体元数据")
    return 结果.成功结果({
        "时长秒": _转浮点(格式.get("duration")),
        "格式": 格式.get("format_name", ""),
        "大小字节": _转整数(格式.get("size")),
        "比特率": _转整数(格式.get("bit_rate")),
        "流": 流列表,
    })


def 探测媒体(文件路径: str, 超时秒: float = 默认超时秒) -> 结果:
    """探测媒体：返回 {时长秒, 流, 格式, 大小字节, 比特率}（只读）。"""
    错误 = 校验基本参数(文件路径, 超时秒)
    if 错误:
        return 错误
    return 探测元数据(文件路径, 超时秒)


def 探测帧尺寸(文件路径: str, 超时秒: float = 默认超时秒) -> 结果:
    """探测单帧/图像文件真实尺寸：返回 {宽度, 高度}（同一受控 ffprobe 链）。

    用于抽帧后对输出帧文件做真实尺寸探测，失败映射与 探测元数据 一致
    （提供者不可用/损坏媒体/超时/取消/进程崩溃 原样透传）。
    """
    错误 = 校验基本参数(文件路径, 超时秒)
    if 错误:
        return 错误
    元数据 = 探测元数据(文件路径, 超时秒)
    if not 元数据.成功:
        return 元数据
    视频流 = next(
        (流 for 流 in 元数据.值["流"]
         if 流["类型"] in ("video", "image") and 流.get("宽度") and 流.get("高度")),
        None)
    if not 视频流:
        return _失败("损坏媒体", f"输出帧未含可解析的尺寸信息: {文件路径}")
    return 结果.成功结果({"宽度": 视频流["宽度"], "高度": 视频流["高度"]})
