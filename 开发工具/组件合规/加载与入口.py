"""加载与入口：按公开入口约定把任意 .py 文件/组件入口加载为模块（组件合规测试包拆分件）。

**公开入口约定（跨文件共享判据，勿在本模块另立）**：`_加载入口` 会清掉 `实现` /
`实现.*` 的 `sys.modules` 缓存、把组件目录插进 `sys.path` 再 `_加载模块`，收尾时全部还原。
这正是 `开发工具/组件合规/模块合规.py::_分类导入` 与 `运行核心/依赖防火墙.py::同包实现导入`
放行 `from 实现.X import Y` 短名入口所依据的加载约定。

本模块**只做代码搬家**，成员名/签名/默认值/缓存清理与 sys.path 还原顺序与拆分前逐字一致
（拆分前 blob 冻结于 `/tmp/拆分基线/合规测试包.py`，sha256 前16=`daa8fd30a0565f33`）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _加载模块(文件路径: Path):
    """加载任意 Python 文件为模块（用于真实实现调用）。"""
    import importlib.util as _工具
    标识 = hashlib.sha1(str(文件路径.resolve()).encode("utf-8")).hexdigest()[:12]
    模块名 = f"合规_{文件路径.stem}_{标识}"
    规格 = _工具.spec_from_file_location(模块名, 文件路径)
    if 规格 is None or 规格.loader is None:
        raise ImportError(f"无法加载: {文件路径}")
    模块 = _工具.module_from_spec(规格)
    规格.loader.exec_module(模块)
    return 模块

def _加载入口(组件目录: Path, 入口路径: Path):
    """按公开入口加载入口模块，隔离临时组件的固定包名缓存。"""
    import sys as _系统
    原有模块 = {
        名称: 模块 for 名称, 模块 in _系统.modules.items()
        if 名称 == "实现" or 名称.startswith("实现.")
    }
    for 名称 in list(原有模块):
        del _系统.modules[名称]
    _系统.path.insert(0, str(组件目录))
    try:
        return _加载模块(入口路径)
    finally:
        _系统.path.remove(str(组件目录))
        for 名称 in list(_系统.modules):
            if 名称 == "实现" or 名称.startswith("实现."):
                del _系统.modules[名称]
        _系统.modules.update(原有模块)

def _值类型(值: Any) -> str:
    """按配置值推断类型（用于生产配置校验器声明表）。"""
    if isinstance(值, bool):
        return "布尔"
    if isinstance(值, int):
        return "整数"
    if isinstance(值, float):
        return "浮点数"
    if isinstance(值, str):
        return "文本"
    if isinstance(值, list):
        return "列表"
    if isinstance(值, dict):
        return "字典"
    return "空"
