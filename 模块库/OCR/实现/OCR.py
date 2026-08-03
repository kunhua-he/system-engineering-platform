"""OCR 模块：组合 Tesseract 提供者公开入口，统一中文契约与错误码透传。

只经 支持库.适配层.Tesseract提供者 公开入口组合，禁止 import 实现目录
与第三方。能力：
- 识别图片文字：图片路径/图片字节 二选一入口，输出 文本 或 词级数据；
- 识别图片文件：按图片文件路径识别文字，输出 文本 或 词级数据；
- 可用性检查：真实探测 tesseract 版本与语言包。
错误码原样透传：参数不合法/文件不存在/工具缺失/语言包缺失/识别失败/
进程崩溃/超时/取消/超出限制/提供者不可用。
"""

from __future__ import annotations

import threading

from 公共契约.基础类型.结果类型 import 结果
from 支持库.适配层.Tesseract提供者 import 识别图片
from 支持库.适配层.Tesseract提供者 import 语言包列表
from 支持库.适配层.Tesseract提供者 import 版本探针

来源 = "OCR"
默认语言 = "eng"


def 识别图片文字(
    图片路径: str | None = None,
    图片字节: bytes | None = None,
    语言: str = 默认语言,
    词级数据: bool = False,
    超时秒: float = 60.0,
    取消事件: threading.Event | None = None,
    输出上限字节: int | None = None,
) -> 结果:
    """识别图片文字：路径/字节二选一；返回 {文本} 或 词级数据 {词列表}。

    参数校验与错误码语义与 Tesseract 提供者一致（透传）。
    """
    if (图片路径 is None) == (图片字节 is None):
        return 结果.失败("参数不合法", "图片路径与图片字节必须且只能提供一个", 来源=来源)
    return 识别图片(
        图片路径=图片路径,
        图片字节=图片字节,
        语言=语言,
        词级数据=词级数据,
        超时秒=超时秒,
        取消事件=取消事件,
        输出上限字节=输出上限字节,
    )


def 识别图片文件(
    图片路径: str,
    语言: str = 默认语言,
    词级数据: bool = False,
    超时秒: float = 60.0,
    取消事件: threading.Event | None = None,
    输出上限字节: int | None = None,
) -> 结果:
    """按图片文件路径识别文字：返回 {文本} 或 词级数据 {词列表}。"""
    if not isinstance(图片路径, str) or not 图片路径.strip():
        return 结果.失败("参数不合法", "图片路径必须为非空文本", 来源=来源)
    return 识别图片(
        图片路径=图片路径,
        语言=语言,
        词级数据=词级数据,
        超时秒=超时秒,
        取消事件=取消事件,
        输出上限字节=输出上限字节,
    )


def 可用性检查(超时秒: float = 10.0, 命令路径: str = "") -> 结果:
    """可用性检查：真实探测 tesseract 版本与语言包。

    返回 {tesseract, 版本, 满足最低版本, 语言列表, 数据目录, 语言数量}；
    任一步失败如实透传（如 工具缺失）。
    """
    版本结果 = 版本探针(超时秒)
    if not 版本结果.成功:
        return 版本结果
    语言结果 = 语言包列表(超时秒)
    if not 语言结果.成功:
        return 语言结果
    return 结果.成功结果({
        "tesseract": 版本结果.值.get("tesseract"),
        "版本": 版本结果.值.get("版本"),
        "满足最低版本": 版本结果.值.get("满足最低版本"),
        "语言列表": 语言结果.值.get("语言列表"),
        "数据目录": 语言结果.值.get("数据目录"),
        "语言数量": 语言结果.值.get("数量"),
    })
