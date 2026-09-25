"""支持库加载器：发现、安装与装配支持库。

支持库目录约定：每个子目录是一份支持库，包含 包声明.json 与 入口.py；
入口.py 必须导出 注册能力(注册表) 函数，加载器只经此注册能力实现，
不直接 import 支持库内部实现。
"""

from __future__ import annotations

from pathlib import Path

from 公共契约.包声明 import 包声明, 加载声明文件
from 公共契约.能力契约 import 能力注册表
# 入口「定位 → 加载」的唯一实现：定位走 入口路径.解析入口路径，加载见 入口加载.py。
from 运行核心.加载器.包安装.入口加载 import 加载入口模块
from 公共契约.基础类型.逻辑类型 import 真, 假

声明文件名 = "包声明.json"
入口文件名 = "入口.py"


def 发现支持库(支持库根目录: Path) -> list[包声明]:
    """递归扫描目录发现全部支持库声明（按包id排序）。"""
    from 运行核心.加载器.包发现.发现器 import 扫描目录

    return sorted(扫描目录(支持库根目录, "支持库"), key=lambda 声明: 声明.包id)


def 安装支持库(声明: 包声明, 注册表: 能力注册表) -> list[str]:
    """装配一份支持库：加载入口并注册能力实现，返回已注册能力 id。"""
    模块 = 加载入口模块(声明, "支持库")
    注册函数 = getattr(模块, "注册能力", None)
    if not callable(注册函数):
        raise RuntimeError(f"支持库 {声明.包id} 的入口缺少 注册能力(注册表) 函数")
    注册函数(注册表)
    return 注册表.能力id列表


def 安装全部支持库(支持库根目录: Path, 注册表: 能力注册表) -> list[str]:
    """发现并安装全部支持库（跳过已废弃回滚版本），返回已注册能力 id 列表。"""
    已注册: list[str] = []
    for 声明 in 发现支持库(支持库根目录):
        if getattr(声明, "已废弃", 假):
            continue  # 已废弃包保留文件，不参与装配/注册
        安装支持库(声明, 注册表)
        已注册.extend(能力.能力id for 能力 in 声明.能力)
    return 已注册
