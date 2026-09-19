"""FFmpeg 媒体提供者·拼接侧：把多个同源分片按顺序无损拼成一个文件。

为什么用 concat demuxer + `-c copy`：直播录制分片本身是完整 mp4 且编码参数一致
（同一录制档位、同一分辨率/帧率），流复制不重编码 → 秒级完成、零画质损失、
不吃 GPU，也不会影响 ASR/精校依赖的音频。分片编码参数不一致时 concat 会直接
失败（统一回报 进程崩溃），不会产出看似成功的坏文件。

清单文件用 `-safe 0` 允许绝对路径；路径里的单引号按 ffmpeg concat 语法转义
（`'` → `'\\''`），否则含引号的文件名会让清单被解析错位。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.运行时 import 平台适配
from 支持库.后端.媒体处理支持库.FFmpeg媒体.实现 import 探测
from 支持库.后端.媒体处理支持库.FFmpeg媒体.实现.处理 import (
    视频格式表,
    默认最大输出字节,
    _处理任务,
)

最少分片数 = 2


def _清单行(路径: str) -> str:
    """按 ffmpeg concat demuxer 语法写一行（单引号转义为 '\\'' ）。"""
    return "file '" + 路径.replace("'", "'\\''") + "'\n"


def 拼接媒体(文件列表: list, 输出格式: str = "mp4", 输出路径: str | None = None,
           超时秒: float = 120.0, 最大输出字节: int = 默认最大输出字节,
           返回字节: bool = False) -> 结果:
    """按顺序无损拼接多个分片（返回 {格式, 字节数, 输出路径, 可选 字节b64}）。

    校验口径：文件列表至少 2 项、每项为非空文本且真实存在；格式限视频容器白名单。
    失败语义：参数不合法 / 文件不存在 / 超时 / 取消 / 进程崩溃 / 超出限制 —— 与
    本库其它能力同一套公开错误码，调用方无需区分提供者。
    """
    输出格式 = str(输出格式 or "").lower().lstrip(".")
    if not isinstance(文件列表, (list, tuple)) or len(文件列表) < 最少分片数:
        return 探测._失败("参数不合法", f"文件列表 必须是至少 {最少分片数} 个文件路径的列表")
    路径列表 = []
    for 项 in 文件列表:
        if not isinstance(项, str) or not 项.strip():
            return 探测._失败("参数不合法", "文件列表 每一项都必须是非空文本路径")
        路径 = Path(项).expanduser()
        if not 路径.is_file():
            return 探测._失败("文件不存在", f"待拼接分片不存在: {项}")
        路径列表.append(str(路径))
    if isinstance(超时秒, bool) or not isinstance(超时秒, (int, float)) or 超时秒 <= 0:
        return 探测._失败("参数不合法", "超时秒 必须是正数")
    if 输出格式 not in 视频格式表:
        return 探测._失败("参数不合法", f"不支持的拼接格式: {输出格式}（支持 {sorted(视频格式表)}）")
    if Path(路径列表[0]).resolve() in {Path(p).resolve() for p in 路径列表[1:]}:
        return 探测._失败("参数不合法", "文件列表 存在重复分片，拼接顺序无法确定")
    清单目录 = tempfile.mkdtemp(prefix="FFmpeg拼接清单_")
    清单 = Path(清单目录) / "清单.txt"
    try:
        清单.write_text("".join(_清单行(p) for p in 路径列表), encoding="utf-8")
        return _处理任务(
            路径列表[0], 输出路径, "FFmpeg拼接_", 输出格式,
            lambda 输出文件: ["-f", "concat", "-safe", "0", "-i", str(清单),
                            "-c", "copy", str(输出文件)],
            超时秒, 最大输出字节, 返回字节=返回字节)
    finally:
        平台适配.清只读后删除树(Path(清单目录), 忽略失败=真)
