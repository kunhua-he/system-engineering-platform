"""支持库加载器：发现、安装与装配支持库。

支持库目录约定：每个子目录是一份支持库，包含 包声明.json 与 入口.py；
入口.py 必须导出 注册能力(注册表) 函数，加载器只经此注册能力实现，
不直接 import 支持库内部实现。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from 公共契约.包声明 import 包声明, 加载声明文件
from 公共契约.能力契约 import 能力注册表
from 运行核心.加载器.包安装.入口路径 import 解析入口路径

声明文件名 = "包声明.json"
入口文件名 = "入口.py"


def 加载入口模块(声明: 包声明) -> Any:
    """按声明.入口 加载入口模块（路径解析见 入口路径.解析入口路径）。"""
    入口路径 = 解析入口路径(声明, "支持库")
    模块名 = f"支持库运行时_{声明.包id.replace('.', '_')}"
    if 模块名 in sys.modules:
        return sys.modules[模块名]
    规格 = importlib.util.spec_from_file_location(模块名, 入口路径)
    if 规格 is None or 规格.loader is None:
        raise ImportError(f"无法加载支持库入口: {入口路径}")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules[模块名] = 模块
    规格.loader.exec_module(模块)
    return 模块


def 发现支持库(支持库根目录: Path) -> list[包声明]:
    """递归扫描目录发现全部支持库声明（按包id排序）。"""
    from 运行核心.加载器.包发现.发现器 import 扫描目录

    return sorted(扫描目录(支持库根目录, "支持库"), key=lambda 声明: 声明.包id)


def 安装支持库(声明: 包声明, 注册表: 能力注册表) -> list[str]:
    """装配一份支持库：加载入口并注册能力实现，返回已注册能力 id。"""
    模块 = 加载入口模块(声明)
    注册函数 = getattr(模块, "注册能力", None)
    if not callable(注册函数):
        raise RuntimeError(f"支持库 {声明.包id} 的入口缺少 注册能力(注册表) 函数")
    注册函数(注册表)
    return 注册表.能力id列表


def 安装全部支持库(支持库根目录: Path, 注册表: 能力注册表) -> list[str]:
    """发现并安装全部支持库（跳过已废弃回滚版本），返回已注册能力 id 列表。"""
    已注册: list[str] = []
    for 声明 in 发现支持库(支持库根目录):
        if getattr(声明, "已废弃", False):
            continue  # 已废弃包保留文件，不参与装配/注册
        安装支持库(声明, 注册表)
        已注册.extend(能力.能力id for 能力 in 声明.能力)
    return 已注册
