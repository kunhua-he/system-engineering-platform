"""模块加载器：发现、安装与装配模块。

模块与支持库同构：每个子目录一份模块（包声明.json + 入口.py）。
模块通过公共契约（能力注册表）调用支持库能力，禁止 import 支持库实现。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from 公共契约.包声明 import 包声明, 加载声明文件
from 公共契约.能力契约 import 能力注册表

声明文件名 = "包声明.json"
入口文件名 = "入口.py"


def 加载入口模块(声明: 包声明) -> Any:
    """按声明.入口 加载模块入口模块。"""
    系统根 = Path(__file__).resolve().parents[2]
    for _祖先 in 系统根.parents:
        if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
            系统根 = _祖先
            break
    入口路径 = Path(声明.来源路径).parent / 声明.入口
    if not 入口路径.is_file():
        入口路径 = 系统根 / 声明.入口
    if not 入口路径.is_file():
        raise FileNotFoundError(f"模块 {声明.包id} 缺少入口文件: {声明.入口}")
    模块名 = f"模块运行时_{声明.包id.replace('.', '_')}"
    if 模块名 in sys.modules:
        return sys.modules[模块名]
    规格 = importlib.util.spec_from_file_location(模块名, 入口路径)
    if 规格 is None or 规格.loader is None:
        raise ImportError(f"无法加载模块入口: {入口路径}")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules[模块名] = 模块
    规格.loader.exec_module(模块)
    return 模块


def 发现模块(模块根目录: Path) -> list[包声明]:
    """递归扫描目录发现全部模块声明（按包id排序）。"""
    from 运行核心.加载器.包发现.发现器 import 扫描目录

    return sorted(扫描目录(模块根目录, "模块"), key=lambda 声明: 声明.包id)


def 安装模块(声明: 包声明, 注册表: 能力注册表) -> list[str]:
    """装配一份模块：加载入口；若导出 注册能力 则一并注册。"""
    模块 = 加载入口模块(声明)
    注册函数 = getattr(模块, "注册能力", None)
    if callable(注册函数):
        注册函数(注册表)
    return 注册表.能力id列表


def 安装全部模块(模块根目录: Path, 注册表: 能力注册表) -> list[str]:
    """发现并安装全部模块，返回全部已注册能力 id 列表。"""
    已注册: list[str] = []
    for 声明 in 发现模块(模块根目录):
        安装模块(声明, 注册表)
        已注册.extend(能力.能力id for 能力 in 声明.能力)
    return 已注册
