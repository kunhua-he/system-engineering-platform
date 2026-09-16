"""兼容垫片：同名平铺模块 `启动监督器/健康监督.py` 的惰性回退装载。

为什么需要：包目录 `启动监督器/健康监督/` 与平铺文件 `启动监督器/健康监督.py`
同名，Python 里**包优先于同名模块**，既有调用方（测试中心 3 处：测试_健康监督/
测试_健康配置/测试_提供者生命周期）的 `from 启动监督器.健康监督 import
系统提供者健康监督` 会因此失效。

本模块只按文件路径把那个平铺文件加载回来，**不复制它的任何逻辑**——它仍是
「系统提供者周期探针 + 读取健康监督配置」的唯一语义实现，本包一个字不改它。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

平铺模块路径 = Path(__file__).resolve().parents[2] / "健康监督.py"
_平铺模块 = None


def 取平铺模块():
    """取同名平铺模块（惰性单例；缺失或加载失败抛 AttributeError）。"""
    global _平铺模块
    if _平铺模块 is None:
        _平铺模块 = _加载平铺模块()
    return _平铺模块


def _加载平铺模块():
    if not 平铺模块路径.is_file():
        raise AttributeError(f"同名平铺模块不存在: {平铺模块路径}")
    模块名 = "启动监督器.健康监督.平铺实现"
    规格 = importlib.util.spec_from_file_location(模块名, 平铺模块路径)
    if 规格 is None or 规格.loader is None:
        raise AttributeError(f"无法加载同名平铺模块: {平铺模块路径}")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules[模块名] = 模块
    规格.loader.exec_module(模块)
    return 模块
