"""运行缓存根唯一解析器。

源码开发默认保持 ``<工程根>/工程缓存``；生成制品必须声明 ``制品运行=True``，
默认使用平台级稳定缓存目录。环境变量 ``系统底座_工程缓存根`` 始终显式覆盖。
本模块只解析路径，不创建目录。

**跨平台收口**：平台级稳定缓存目录的**平台口径判断**（Windows ``%LOCALAPPDATA%`` /
macOS ``~/Library/Caches`` / 其余 Linux 的 ``$XDG_CACHE_HOME`` 或 ``~/.cache``）
唯一实现在 `公共契约/运行时/平台适配.平台稳定缓存根()`；**本文件不做任何平台判断**
（第一轮《审计_平台判断越界_20260919》§二 B2-1 前：本文件用 ``platform.system()``
硬判三平台，是全仓**第三处平台判定落点**，并造出「``当前平台()`` 给 ``macOS``、
``platform.system()`` 给 ``Darwin``」两套平台名口径 —— 现已删除 ``import platform``）。
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from 公共契约.运行时.平台适配 import 平台稳定缓存根

运行缓存环境变量 = "系统底座_工程缓存根"


def _平台稳定缓存根(环境: Mapping[str, str]) -> Path:
    """平台级稳定受管缓存根：**直接转调收口层唯一实现**，本文件不复制平台分支。

    保留本函数名只为「本模块内部唯一取用点」的可读性 —— 平台口径（Windows / macOS /
    其余 Linux 三分支、各自的环境变量优先级）**一个字都不在本文件**，
    全部在 `公共契约/运行时/平台适配.平台稳定缓存根()`。
    """
    return 平台稳定缓存根(环境=环境)


def 解析运行缓存根(
    系统根目录: Path,
    *,
    制品运行: bool = False,
    环境: Mapping[str, str] | None = None,
) -> Path:
    """按“环境显式覆盖 → 制品稳定根 → 源码工程缓存”解析唯一运行缓存根。

    制品运行时拒绝把显式覆盖指回不可变制品内部；源码开发未覆盖时继续使用
    原有 ``工程缓存`` 语义。返回绝对规范路径，但不产生任何目录或文件。
    """
    系统根 = Path(系统根目录).expanduser().resolve()
    平台客户端制品 = 系统根.name == "平台客户端"
    环境表 = os.environ if 环境 is None else 环境
    显式值 = str(环境表.get(运行缓存环境变量, "") or "").strip()
    if 显式值:
        候选 = Path(显式值).expanduser()
        if not 候选.is_absolute():
            raise ValueError(f"{运行缓存环境变量} 必须是绝对路径: {显式值}")
        缓存根 = 候选.resolve()
    elif 制品运行 or 平台客户端制品:
        缓存根 = _平台稳定缓存根(环境表).expanduser().resolve()
    else:
        缓存根 = (系统根 / "工程缓存").resolve()
    if (制品运行 or 平台客户端制品) and (
            缓存根 == 系统根 or 缓存根.is_relative_to(系统根)):
        raise ValueError(f"制品运行缓存不得位于不可变制品内: {缓存根}")
    return 缓存根


def 解析运行数据根(
    系统根目录: Path,
    *,
    制品运行: bool = False,
    环境: Mapping[str, str] | None = None,
) -> Path:
    """运行数据库目录（唯一事实源）：`<运行缓存根>/运行数据`。

    华哥 2026-09-15 定盘：**运行态一律入库**，库文件统一放在本目录下；支持库确需隔离时
    可有自己的库文件，但位置同样在这里，且一律经唯一 SQLite 支持库访问。
    本函数只解析路径，不创建目录。
    """
    return 解析运行缓存根(系统根目录, 制品运行=制品运行, 环境=环境) / "运行数据"


__all__ = ["运行缓存环境变量", "解析运行缓存根", "解析运行数据根"]
