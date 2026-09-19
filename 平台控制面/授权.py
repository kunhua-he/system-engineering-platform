"""五类角色统一授权（等价再导出腿）。

**本文件不是第二份实现**（2026-09-20 W 路 #7 唯一化，照 统一入口/健康监督 的做法）：

- 真实现唯一落在 `平台控制面/授权/核心.py`（包内），模块级公开名与签名逐字未改；
- 本文件按**点分包路径** `from 平台控制面.授权.核心 import *` 再导出同一批对象
  （同一模块对象，`is` 同一），并按名补上 `__all__` 未覆盖的公开名；
- 为什么还要留着这条平铺腿：包目录会**遮蔽**同名模块 `平台控制面/授权.py`，
  而平台里存在按**文件路径**加载该平铺文件的腿。本腿因此**必须保留**，并且
  **自己补齐 sys.path 自举**——按路径跑它时（`python3.14 平台控制面/授权.py`
  或经 spec_from_file_location 加载）系统根不在 sys.path 上，缺自举会 `ModuleNotFoundError`。

自举口径：本文件是 `<系统根>/平台控制面/授权.py`，故系统根 = parents[1]；
必须在 import 本项目顶层包**之前**执行。

五类角色语义的权威说明（授权不可自举、一次性引导令牌、兼容边界等）见
`平台控制面/授权/核心.py` 的模块 docstring——唯一实现点只有它一处。
"""
from __future__ import annotations

import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.授权.核心 import *  # noqa: F401,F403 —— 等价再导出（同一模块对象）
from 平台控制面.授权.核心 import __all__ as _核心公开名  # noqa: F401

# 按名补齐「核心未收进 __all__、但本平铺腿对外面本来就有」的公开名。
# 口径（逐项对着 拆前基线 20 个模块级名核过，一条没少）：
#   ① `核心.__all__` 收的是核心**自己定义/自己赋值**的 11 个公开名；
#   ② 下面 8 个名在旧平铺腿里就是可命名的（`dir(旧模块)` 含它们）——核心**从别处
#      import 进来**的 `Any/Path/os/secrets/time/uuid/真/假`。唯一化只允许「搬同一份
#      实现」，不允许顺手收窄公开名，故逐名补回（`annotations` 由本文件的
#      `from __future__ import annotations` 自带，与旧腿一致）。
from 平台控制面.授权.核心 import (  # noqa: F401 —— 按名补齐（核心 __all__ 未覆盖的公开名）
    Any,
    Path,
    os,
    secrets,
    time,
    uuid,
    假,
    真,
)

__all__ = list(_核心公开名) + [
    "Any",
    "Path",
    "os",
    "secrets",
    "time",
    "uuid",
    "假",
    "真",
]
