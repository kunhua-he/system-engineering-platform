"""FFmpeg 媒体提供者·处理侧：提取音频、转码、抽帧；外部命令受管调用
（独立进程组/超时/取消/输出上限截断），临时文件 try/finally 清理零残留。"""

from __future__ import annotations

import base64
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.媒体处理支持库.FFmpeg媒体.实现 import 探测
from 支持库.后端.媒体处理支持库.FFmpeg媒体.实现.进程管理 import 执行受管命令

默认最大输出字节 = 200 * 1024 * 1024
默认最大时长秒 = 2 * 3600.0
命令输出上限 = 1024 * 1024  # 外部命令 stdout/stderr 受限读取上限
音频编码器表 = {"wav": "pcm_s16le", "mp3": "libmp3lame", "aac": "aac", "m4a": "aac", "ogg": "libvorbis", "flac": "flac"}
视频格式表 = {"mp4", "mkv", "webm", "mov", "avi"}
帧格式表 = {"jpg", "png"}
编码选项表 = {
    "分辨率": (["-vf", "scale={值}"], re.compile(r"^\d+[xX]\d+$")),
    "视频码率": (["-b:v", "{值}"], re.compile(r"^\d+[kKmM]$")),
    "音频码率": (["-b:a", "{值}"], re.compile(r"^\d+[kKmM]$")),
    "帧率": (["-r", "{值}"], re.compile(r"^\d+$")),
}


def _校验时长(时长秒: float, 最大时长秒: Any) -> 结果 | None:
    if 最大时长秒 is not None and 时长秒 > 最大时长秒:
        return 探测._失败("超长媒体", f"媒体时长 {时长秒:.1f} 秒超过上限 {最大时长秒:g} 秒")
    return None


def _校验编码选项(编码选项: Any) -> 结果 | None:
    if 编码选项 is None:
        return None
    if not isinstance(编码选项, dict):
        return 探测._失败("参数不合法", "编码选项必须是对象")
    for 键, 值 in 编码选项.items():
        if 键 not in 编码选项表:
            return 探测._失败("参数不合法", f"不支持的编码选项: {键}（支持 {sorted(编码选项表)}）")
        if not 编码选项表[键][1].match(str(值)):
            return 探测._失败("参数不合法", f"编码选项 {键} 值不合法: {值}")
    return None


def _执行处理(文件路径: str, 参数列表: list[str], 输出文件: Path,
            超时秒: float, 最大输出字节: int, 帧探测: bool = False) -> 结果:
    """ffmpeg 受管执行并读取输出文件；进程级失败 → 取消/超时/进程崩溃。

    帧探测：对输出文件经 ffprobe 受控探测链做真实尺寸探测，加入 宽度/高度。
    """
    ffmpeg = 探测.查找命令("ffmpeg")
    if not ffmpeg:
        return 探测._失败("提供者不可用", "ffmpeg 未安装（提供者不可用）")
    受管 = 执行受管命令([ffmpeg, "-y"] + 参数列表, 超时秒=超时秒,
                        最大输出字节=命令输出上限)
    if not 受管.成功:
        if 受管.错误码 in ("超时", "取消"):
            return 探测._失败(受管.错误码, f"ffmpeg {受管.错误码}: {受管.错误摘要}",
                               可重试=受管.错误码 != "取消")
        return 探测._失败("进程崩溃", f"ffmpeg 执行失败: {受管.错误摘要}", 可重试=True)
    if not 输出文件.is_file():
        return 探测._失败("进程崩溃", "ffmpeg 未产出目标文件", 可重试=True)
    大小 = 输出文件.stat().st_size
    if 大小 > 最大输出字节:
        return 探测._失败("超出限制", f"输出文件过大: {大小} 字节 > 上限 {最大输出字节} 字节")
    值 = {
        "字节b64": base64.b64encode(输出文件.read_bytes()).decode("ascii"),
        "格式": 输出文件.suffix.lstrip("."), "字节数": 大小,
        "输出路径": str(输出文件),
    }
    if 帧探测:
        尺寸 = 探测.探测帧尺寸(str(输出文件), 超时秒)
        if not 尺寸.成功:
            return 尺寸
        值["宽度"] = 尺寸.值["宽度"]
        值["高度"] = 尺寸.值["高度"]
    return 结果.成功结果(值)


def _预检媒体(预检: 结果, 最大时长秒: Any, 流检查: Any = None) -> 结果 | None:
    """探测预检：探测失败原样返回；超长 → 超长媒体；流检查失败返回其错误。"""
    if not 预检.成功:
        return 预检
    错误 = _校验时长(预检.值["时长秒"], 最大时长秒)
    return 错误 if 错误 else (流检查(预检.值) if 流检查 else None)


def _处理任务(文件路径: str, 输出路径: str | None, 前缀: str, 扩展名: str,
            构建参数: Any, 超时秒: float, 最大输出字节: int,
            帧探测: bool = False) -> 结果:
    """受管执行并读取输出文件；临时目录自建时 finally 强制清理（零残留）。"""
    输出文件 = Path(输出路径) if 输出路径 else Path(tempfile.mkdtemp(prefix=前缀)) / f"输出.{扩展名}"
    自建 = 输出路径 is None
    try:
        return _执行处理(文件路径, 构建参数(输出文件), 输出文件,
                         超时秒, 最大输出字节, 帧探测=帧探测)
    finally:
        if 自建:
            shutil.rmtree(输出文件.parent, ignore_errors=True)


def 提取音频(文件路径: str, 输出格式: str = "wav", 输出路径: str | None = None,
           超时秒: float = 60.0, 最大输出字节: int = 默认最大输出字节,
           最大时长秒: float | None = 默认最大时长秒) -> 结果:
    """提取首个音频轨到目标格式（默认临时文件自动清理）。"""
    输出格式 = str(输出格式 or "").lower().lstrip(".")
    错误 = 探测.校验基本参数(文件路径, 超时秒, 输出路径)
    if 错误:
        return 错误
    if 输出格式 not in 音频编码器表:
        return 探测._失败("参数不合法", f"不支持的音频格式: {输出格式}（支持 {sorted(音频编码器表)}）")
    预检 = _预检媒体(
        探测.探测元数据(文件路径, 超时秒), 最大时长秒,
        lambda 值: None if "audio" in {流["类型"] for 流 in 值["流"]} else 探测._失败("无音轨", "媒体不包含音频流"))
    if 预检:
        return 预检
    return _处理任务(
        文件路径, 输出路径, "FFmpeg音频_", 输出格式,
        lambda 输出文件: ["-i", 文件路径, "-vn", "-map", "0:a:0", "-c:a", 音频编码器表[输出格式], str(输出文件)],
        超时秒, 最大输出字节)


def 转码(文件路径: str, 输出格式: str = "mp4", 编码选项: dict | None = None,
       输出路径: str | None = None, 超时秒: float = 60.0,
       最大输出字节: int = 默认最大输出字节,
       最大时长秒: float | None = 默认最大时长秒) -> 结果:
    """ffmpeg 转码到目标容器（编码选项白名单，默认临时文件自动清理）。"""
    输出格式 = str(输出格式 or "").lower().lstrip(".")
    错误 = 探测.校验基本参数(文件路径, 超时秒, 输出路径) or _校验编码选项(编码选项)
    if 错误:
        return 错误
    if 输出格式 not in 视频格式表:
        return 探测._失败("参数不合法", f"不支持的转码格式: {输出格式}（支持 {sorted(视频格式表)}）")
    预检 = _预检媒体(探测.探测元数据(文件路径, 超时秒), 最大时长秒)
    if 预检:
        return 预检
    选项参数 = []
    for 键, 值 in (编码选项 or {}).items():
        选项参数.extend(项.format(值=值) for 项 in 编码选项表[键][0])
    return _处理任务(
        文件路径, 输出路径, "FFmpeg转码_", 输出格式,
        lambda 输出文件: ["-i", 文件路径] + 选项参数 + [str(输出文件)],
        超时秒, 最大输出字节)


def 抽取帧(文件路径: str, 时间点秒: float, 输出格式: str = "jpg",
         输出路径: str | None = None, 超时秒: float = 60.0,
         最大输出字节: int = 默认最大输出字节,
         最大时长秒: float | None = 默认最大时长秒) -> 结果:
    """ffmpeg 抽帧（jpg/png，时间点秒，默认临时文件自动清理）。

    返回 {字节b64, 格式, 宽度, 高度}；宽度/高度为输出帧经 ffprobe
    受控探测链探测得到的真实尺寸，禁止固定值。
    """
    输出格式 = str(输出格式 or "").lower().lstrip(".")
    错误 = 探测.校验基本参数(文件路径, 超时秒, 输出路径)
    if 错误:
        return 错误
    if (not isinstance(时间点秒, (int, float)) or isinstance(时间点秒, bool) or 时间点秒 < 0):
        return 探测._失败("参数不合法", "时间点秒必须是非负数字")
    if 输出格式 not in 帧格式表:
        return 探测._失败("参数不合法", f"不支持的帧格式: {输出格式}（支持 {sorted(帧格式表)}）")
    预检 = _预检媒体(探测.探测元数据(文件路径, 超时秒), 最大时长秒)
    if 预检:
        return 预检
    质量参数 = ["-q:v", "2"] if 输出格式 == "jpg" else []
    return _处理任务(
        文件路径, 输出路径, "FFmpeg抽帧_", 输出格式,
        lambda 输出文件: ["-ss", str(时间点秒), "-i", 文件路径, "-frames:v", "1", "-f", "image2"] + 质量参数 + [str(输出文件)],
        超时秒, 最大输出字节, 帧探测=True)


def 截取音频(文件路径: str, 开始秒: float, 结束秒: float, 输出格式: str = "wav",
           输出路径: str | None = None, 超时秒: float = 60.0,
           最大输出字节: int = 默认最大输出字节,
           最大时长秒: float | None = 默认最大时长秒) -> 结果:
    """ffmpeg 按时间区间截取音频（复核区间用：-ss 前置快速定位 + -t 限长）。

    返回 {字节b64, 格式, 字节数, 输出路径}；无音轨 → 无音轨；区间不合法 → 参数不合法。
    """
    输出格式 = str(输出格式 or "").lower().lstrip(".")
    错误 = 探测.校验基本参数(文件路径, 超时秒, 输出路径)
    if 错误:
        return 错误
    for 名称, 值 in (("开始秒", 开始秒), ("结束秒", 结束秒)):
        if isinstance(值, bool) or not isinstance(值, (int, float)) or 值 < 0:
            return 探测._失败("参数不合法", f"{名称} 必须是非负数字")
    if float(结束秒) <= float(开始秒):
        return 探测._失败("参数不合法", f"结束秒 必须大于 开始秒（当前 {开始秒} → {结束秒}）")
    if 输出格式 not in 音频编码器表:
        return 探测._失败("参数不合法", f"不支持的音频格式: {输出格式}（支持 {sorted(音频编码器表)}）")
    预检 = _预检媒体(
        探测.探测元数据(文件路径, 超时秒), 最大时长秒,
        lambda 值: None if "audio" in {流["类型"] for 流 in 值["流"]} else 探测._失败("无音轨", "媒体不包含音频流"))
    if 预检:
        return 预检
    截取时长 = round(float(结束秒) - float(开始秒), 3)
    return _处理任务(
        文件路径, 输出路径, "FFmpeg截取_", 输出格式,
        lambda 输出文件: ["-ss", str(开始秒), "-i", 文件路径, "-t", str(截取时长),
                        "-vn", "-map", "0:a:0", "-c:a", 音频编码器表[输出格式], str(输出文件)],
        超时秒, 最大输出字节)
