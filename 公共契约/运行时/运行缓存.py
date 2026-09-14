"""运行缓存根唯一解析器。

源码开发默认保持 ``<工程根>/工程缓存``；生成制品必须声明 ``制品运行=True``，
默认使用平台级稳定缓存目录。环境变量 ``系统底座_工程缓存根`` 始终显式覆盖。
本模块只解析路径，不创建目录。
"""
from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path

运行缓存环境变量 = "系统底座_工程缓存根"


def _平台稳定缓存根(环境: Mapping[str, str]) -> Path:
    """返回不依赖制品安装路径的平台级稳定受管缓存根。"""
    系统 = platform.system()
    if 系统 == "Windows":
        基础 = 环境.get("LOCALAPPDATA") or 环境.get("TEMP")
        if not 基础:
            基础 = str(Path.home() / "AppData" / "Local")
        return Path(基础) / "系统工程平台" / "运行缓存"
    if 系统 == "Darwin":
        用户目录 = 环境.get("HOME") or str(Path.home())
        return Path(用户目录) / "Library" / "Caches" / "系统工程平台" / "运行缓存"
    基础 = 环境.get("XDG_CACHE_HOME")
    if 基础:
        return Path(基础) / "系统工程平台" / "运行缓存"
    用户目录 = 环境.get("HOME") or str(Path.home())
    return Path(用户目录) / ".cache" / "系统工程平台" / "运行缓存"


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
