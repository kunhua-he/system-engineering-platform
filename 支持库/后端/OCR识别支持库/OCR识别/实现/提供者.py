"""Tesseract 提供者：OCR 识别 / 语言包列表 / 版本探针（外部命令受管执行）。

命令路径纳入平台配置覆盖体系：显式配置优先（函数参数 命令路径 >
环境变量 Tesseract提供者_命令路径 > 默认 PATH 探测 which tesseract）。
显式路径不存在 → 工具缺失；存在但不可执行 → 命令失败；版本低于最低
版本 → 版本不兼容。日志与错误消息不泄露配置路径细节（错误消息只描述
配置状态，不回显路径值）。工具缺失如实返回 工具缺失（可重试）。
Homebrew tesseract 无法读取绝对路径图片，一律以图片目录为 cwd + 相对
文件名启动；字节输入经临时文件.py 落盘后以相对名调用，finally 即时
清理，零残留；输出走 stdout（文本/TSV）。
错误码：语言包缺失/识别失败/进程崩溃/超时/取消/超出限制/工具缺失/
命令失败/版本不兼容/提供者不可用。"""
from __future__ import annotations

import base64
import csv
import io
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Union

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.OCR识别支持库.OCR识别.实现.受管进程 import 执行命令, 默认输出上限字节
from 支持库.后端.OCR识别支持库.OCR识别.实现.临时文件 import (
    清理临时目录, 创建临时目录, 落盘图片,
)

结果类型 = 结果  # 类型判断别名（规避函数内局部变量遮蔽）

工具名 = "tesseract"
最低版本 = "5.0.0"
默认语言 = "eng"
来源 = "Tesseract提供者"
命令路径环境变量 = "Tesseract提供者_命令路径"


def _失败(错误码: str, 消息: str, *, 可重试: bool = False,
          详情: dict[str, Any] | None = None) -> 结果:
    return 结果.失败(错误码, 消息, 来源=来源, 可重试=可重试, 详情=详情)


def _查找工具() -> str | None:
    """默认探测：PATH 中查找 tesseract 可执行。"""
    return shutil.which(工具名)


def _解析命令路径(显式命令路径: str | None) -> Union[str, 结果]:
    """命令路径解析：显式参数 > 环境变量 > 默认探测。

    显式配置的路径不存在 → 工具缺失；存在但不可执行 → 命令失败；
    均未配置 → PATH 探测，未找到 → 工具缺失。错误消息不包含配置
    路径细节（不回显路径值）。
    """
    if 显式命令路径 is not None and not isinstance(显式命令路径, str):
        return _失败("参数不合法", "命令路径必须是文本或 None")
    候选 = (显式命令路径 if 显式命令路径 is not None
            else os.environ.get(命令路径环境变量, "")).strip()
    if not 候选:
        默认路径 = _查找工具()
        if not 默认路径:
            return _失败("工具缺失", "未找到 tesseract，请先安装（如 brew install tesseract）",
                         可重试=True)
        return 默认路径
    路径 = Path(候选).expanduser().resolve()
    if not 路径.is_file():
        return _失败("工具缺失", "显式配置的 tesseract 命令路径不存在",
                     可重试=True)
    if not os.access(路径, os.X_OK):
        return _失败("命令失败", "显式配置的 tesseract 命令路径不可执行",
                     可重试=True)
    return str(路径)


def _执行工具命令(参数列表: list[str], 超时秒: float,
                  命令路径: str | None = None) -> 结果:
    """解析命令路径后受管执行；解析失败时原样返回失败结果。"""
    解析结果 = _解析命令路径(命令路径)
    if isinstance(解析结果, 结果类型):
        return 解析结果
    执行结果 = 执行命令([解析结果] + 参数列表, 超时秒=超时秒)
    if not 执行结果.成功:
        return 执行结果
    if 执行结果.值["退出码"]:
        return _失败("提供者不可用", f"tesseract 退出码 {执行结果.值['退出码']}",
                     可重试=True)
    return 执行结果


def 版本探针(超时秒: float = 10.0, 命令路径: str | None = None) -> 结果:
    """真实执行 tesseract --version；工具缺失如实返回 工具缺失。

    版本低于最低版本 → 版本不兼容（详情含当前/最低版本，不含路径）。
    """
    执行结果 = _执行工具命令(["--version"], 超时秒, 命令路径)
    if not 执行结果.成功:
        return 执行结果
    版本 = _提取版本(执行结果.值["标准输出"])
    if not _满足最低版本(版本, 最低版本):
        return _失败("版本不兼容",
                      f"tesseract 版本低于最低版本 {最低版本}",
                      可重试=True,
                      详情={"当前版本": 版本, "最低版本": 最低版本})
    return 结果.成功结果({"tesseract": "可用", "版本": 版本, "最低版本": 最低版本,
                          "满足最低版本": True, "退出码": 0})


def 语言包列表(超时秒: float = 10.0, 命令路径: str | None = None) -> 结果:
    """真实执行 --list-langs；返回 {语言列表, 数据目录, 数量}。"""
    执行结果 = _执行工具命令(["--list-langs"], 超时秒, 命令路径)
    if not 执行结果.成功:
        return 执行结果
    行列表 = [行.strip() for 行 in 执行结果.值["标准输出"].splitlines() if 行.strip()]
    匹配 = re.search(r'"([^"]+)"', 执行结果.值["标准输出"])
    语言列表 = 行列表[1:]
    return 结果.成功结果({"语言列表": 语言列表,
                          "数据目录": 匹配.group(1) if 匹配 else "",
                          "数量": len(语言列表)})


def _提取版本(输出: str) -> str:
    首行 = next((行.strip() for 行 in 输出.splitlines() if 行.strip()), "")
    匹配 = re.search(r"\d+(?:\.\d+)+", 首行)
    return (匹配.group(0) if 匹配 else 首行)[:200]


def _满足最低版本(版本: str, 最低: str) -> bool:
    """版本元组比较：当前版本是否不低于最低版本。"""

    def 元组(版本串: str) -> tuple[int, ...]:
        return tuple(int(段) for 段 in re.findall(r"\d+", 版本串)[:4] or [0])

    return 元组(版本) >= 元组(最低)


def _解析词表(输出: str) -> list[dict[str, Any]] | None:
    """解析 tesseract TSV 词级数据；无有效表头返回 None（无效响应）。"""
    行列表 = list(csv.reader(io.StringIO(输出), delimiter="\t"))
    if not 行列表 or 行列表[0][0] != "level" or "conf" not in 行列表[0]:
        return None

    def 取数(行: list[str], 转换, 缺省: Any, 序号: int) -> Any:
        try:
            return 转换(行[序号])
        except (ValueError, IndexError):
            return 缺省

    return [{
        "文本": 行[11] if len(行) > 11 else "",
        "置信度": 取数(行, float, -1.0, 10),
        "左": 取数(行, int, 0, 6), "上": 取数(行, int, 0, 7),
        "宽": 取数(行, int, 0, 8), "高": 取数(行, int, 0, 9),
    } for 行 in 行列表[1:] if 行 and 行[0].strip() == "5"]


def _分类识别失败(标准错误: str, 语言: str) -> 结果:
    """非零退出分类：语言包缺失 / 识别失败。"""
    if "Failed loading language" in 标准错误 or "traineddata" in 标准错误:
        return _失败("语言包缺失", f"语言包 '{语言}' 缺失，无法加载 traineddata",
                     详情={"语言": 语言})
    摘要 = " | ".join(行.strip() for 行 in 标准错误.splitlines() if 行.strip())[:300]
    return _失败("识别失败", f"tesseract 识别失败：{摘要 or '未知错误'}", 可重试=True)


def _归一化图片字节(图片字节: Any) -> tuple[bytes | None, 结果 | None]:
    """图片字节 参数归一化校验：二进制原样，base64 文本解码（跨宿主可序列化）。"""
    if isinstance(图片字节, str):
        try:
            图片字节 = base64.b64decode(图片字节)
        except ValueError:
            return None, _失败("参数不合法", "图片字节文本必须是合法 base64")
    if not isinstance(图片字节, bytes) or not 图片字节:
        return None, _失败("参数不合法", "图片字节必须为非空二进制")
    return 图片字节, None


def 识别图片(图片路径: str | None = None, 图片字节: bytes | None = None,
             语言: str = 默认语言, 词级数据: bool = False, 超时秒: float = 60.0,
             取消事件: threading.Event | None = None,
             输出上限字节: int | None = None,
             命令路径: str | None = None) -> 结果:
    """图片 OCR 识别：路径与字节二选一；返回 {文本} 或 {词列表}。

    命令路径：显式参数 > 环境变量 Tesseract提供者_命令路径 > PATH 探测。
    """
    if (图片路径 is None) == (图片字节 is None): return _失败("参数不合法", "图片路径与图片字节必须且只能提供一个")
    if not isinstance(语言, str) or not 语言.strip(): return _失败("参数不合法", "语言必须为非空文本（如 eng/chi_sim）")
    if not isinstance(词级数据, bool): return _失败("参数不合法", "词级数据必须是布尔值")
    if 输出上限字节 is not None and (not isinstance(输出上限字节, int) or 输出上限字节 <= 0): return _失败("参数不合法", "输出上限字节必须是正整数")
    解析结果 = _解析命令路径(命令路径)
    if isinstance(解析结果, 结果类型):
        return 解析结果
    工具路径 = 解析结果
    临时目录 = None
    if 图片字节 is not None:
        图片字节, 错误 = _归一化图片字节(图片字节)
        if 错误:
            return 错误
        临时目录 = 创建临时目录()
        工作目录, 图片相对名 = str(临时目录), 落盘图片(临时目录, 图片字节).name
    else:
        if not isinstance(图片路径, str) or not 图片路径.strip(): return _失败("参数不合法", "图片路径必须为非空文本")
        图片文件 = Path(图片路径)
        if not 图片文件.is_file(): return _失败("文件不存在", f"图片不存在: {图片路径}")
        工作目录, 图片相对名 = str(图片文件.parent), 图片文件.name
    try:
        命令 = [工具路径, 图片相对名, "stdout", "-l", 语言] + (["tsv"] if 词级数据 else [])
        结果 = 执行命令(命令, 超时秒=超时秒, 取消事件=取消事件, 工作目录=工作目录,
                       输出上限字节=输出上限字节 or 默认输出上限字节)
        if not 结果.成功:
            return 结果
        值 = 结果.值
        if 值["退出码"] != 0:
            if 值["退出码"] < 0: return _失败("进程崩溃", f"tesseract 进程被信号杀死（信号 {-值['退出码']}）", 可重试=True)
            return _分类识别失败(值["标准错误"], 语言)
        if 词级数据:
            词列表 = _解析词表(值["标准输出"])
            if 词列表 is None:
                return _失败("进程崩溃", "tesseract 返回了无效的词级数据", 可重试=True)
            return 结果.成功结果({"词列表": 词列表})
        return 结果.成功结果({"文本": 值["标准输出"].strip()})
    finally:
        清理临时目录(临时目录)
