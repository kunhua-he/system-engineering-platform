"""图像处理模块：只经 Pillow 提供者公开入口组合，不深入实现目录。"""

from __future__ import annotations

from pathlib import Path

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.Pillow提供者 import (
    解码图像 as _解码图像,
    像素统计 as _像素统计,
    生成占位图 as _生成占位图,
)


def _失败(错误码: str, 消息: str) -> 结果:
    return 结果.失败(错误码, 消息, 来源="图像处理")


def _读取字节(文件路径: str) -> tuple[bytes | None, 结果 | None]:
    """读取图像文件字节；文件路径非法/不存在/不可读返回稳定错误码。"""
    if not isinstance(文件路径, str) or not 文件路径:
        return None, _失败("参数不合法", "文件路径必须为非空文本")
    try:
        return Path(文件路径).read_bytes(), None
    except FileNotFoundError:
        return None, _失败("文件不存在", f"文件不存在: {文件路径}")
    except OSError as 错误:
        return None, _失败("文件读取失败", str(错误))


def 分析图像文件(文件路径: str) -> 结果:
    """分析图像文件：解码+尺寸+像素统计一次返回。

    成功值 {格式, 宽度, 高度, 模式, 像素数, 平均颜色{红,绿,蓝}}；
    解码/统计失败错误码原样透传 Pillow 提供者。
    """
    字节, 读取错误 = _读取字节(文件路径)
    if 读取错误:
        return 读取错误
    解码 = _解码图像(字节)
    if not 解码.成功:
        return 解码
    统计 = _像素统计(字节)
    if not 统计.成功:
        return 统计
    return 结果.成功结果({**解码.值, **统计.值})


def 生成占位图(宽度: int, 高度: int, 占位类型: str = "纯色",
               背景颜色: str = "#CCCCCC", 前景颜色: str = "#333333",
               文本: str = "") -> 结果:
    """生成占位图（纯色/渐变/文本），经 Pillow 提供者。"""
    return _生成占位图(宽度, 高度, 占位类型, 背景颜色, 前景颜色, 文本)


def 识别图像格式(字节: bytes) -> 结果:
    """按内容识别图像格式（伪装检测），经 Pillow 提供者解码判定。"""
    return _解码图像(字节)
