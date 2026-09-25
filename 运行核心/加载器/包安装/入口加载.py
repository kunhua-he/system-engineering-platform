"""包入口加载（唯一实现）：定位入口路径 → 建规格 → 缓存进 sys.modules → 执行。

支持库与模块的**入口加载规则完全相同**，此前在 `支持库安装.py` / `模块安装.py`
各写一份（同一件事两套实现）；实测两处 diff **仅「支持库 / 模块」字面不同**
（`spec_from_file_location` + `sys.modules` 缓存 + `exec_module` 逐字相同）。
故按与 `入口路径.py` 同一判据收成唯一实现，由 `类型名` 一参同时决定三件事，
且三件都与历史逐字一致：

1. 入口路径解析口径（转 `入口路径.解析入口路径`，不自己推路径）；
2. 模块名前缀 —— 仍是 `支持库运行时_<包id>` / `模块运行时_<包id>`；
3. ImportError 文案 —— 仍是「无法加载支持库入口」/「无法加载模块入口」。

**落点裁决：新起本文件，不塞进 `入口路径.py`。** 理由：后者是**纯路径解析**
（不加载、不执行、不写 `sys.modules`），而装配前单包预检
（`生命周期管理/管理器.py` 的单包级隔离）只复用它做路径判定 —— 一旦把执行副作用
（`exec_module`）混进那个模块，「只解析不加载」的调用腿就会连带执行被检查包的代码，
正是本仓反复要堵的假绿来源；两者判据不同，故分层：入口路径（定位）→ 入口加载（加载）
→ 支持库安装 / 模块安装（装配注册）。
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

from 公共契约.包声明 import 包声明
from 运行核心.加载器.包安装.入口路径 import 解析入口路径


__all__ = ["加载入口模块"]


def 加载入口模块(声明: 包声明, 类型名: str) -> Any:
    """按 声明.入口 加载入口模块并返回模块对象（路径解析见 入口路径.解析入口路径）。

    命中 `sys.modules` 即复用（同一包重复装配只执行一次入口代码）；
    `类型名` 取「支持库」/「模块」，只用于路径解析口径、模块名前缀与失败文案。
    """
    入口路径 = 解析入口路径(声明, 类型名)
    模块名 = f"{类型名}运行时_{声明.包id.replace('.', '_')}"
    if 模块名 in sys.modules:
        return sys.modules[模块名]
    规格 = importlib.util.spec_from_file_location(模块名, 入口路径)
    if 规格 is None or 规格.loader is None:
        raise ImportError(f"无法加载{类型名}入口: {入口路径}")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules[模块名] = 模块
    规格.loader.exec_module(模块)
    return 模块
