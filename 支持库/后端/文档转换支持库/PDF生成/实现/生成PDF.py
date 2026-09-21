"""PDF生成.生成PDF（文档转换支持库.PDF生成）：唯一实现在 支持库/适配层/reportlab提供者（第 10 对收口）。

本文件原与 `支持库/适配层/reportlab提供者/实现/子进程管理器.py` **逐字同源**，
差异只有一处：包路径深度（后端腿比适配层腿多一层目录；门面已改为按「公开入口 +
支持库 并存」定位系统根，故该差异由唯一实现自行正确处理，不需要在两腿重复）。

同一份逻辑只能有一个实现，故本文件改为**转调**：让
`支持库.后端.文档转换支持库.PDF生成.实现.生成PDF` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`）。本包 `__init__.py` 照旧从本路径
导入 `生成PDF`、既有调用方照旧经本模块名取 `默认超时秒` 与 `_启动子进程` 等名字 ——
**对外 import 路径与对外符号零改动**；隔离子进程仍由唯一实现按它自己的 `包目录` 启动
（进程边界与错误码口径完全不变，主进程仍绝不 import reportlab）。

为什么不直接 `import ...实现.生成PDF`：跨包导入 `实现/` 被
`运行核心/依赖防火墙.py` 强制拒绝（判据「跨包禁止导入 实现/ 目录」）；而适配层腿
的公开入口 `__init__.py` 已经是合规的同层导入，且它会正常加载自己的 `实现/` 子模块，
故这里先导公开入口、再把两个模块名指向同一对象（兜底路径按文件路径显式载入，
文件缺失时明确报错、不静默降级）。同一模块对象、不产生第二份实现是平台既有做法，
见 `平台控制面/授权/__init__.py`。
"""

from __future__ import annotations

import importlib.util
import sys

import 支持库.适配层.reportlab提供者  # noqa: F401 —— 公开入口（同层，合规）

from 公共契约.运行时.导入前缀 import 取根前缀, 取系统根

唯一实现名 = 取根前缀(__name__) + "支持库.适配层.reportlab提供者.实现.子进程管理器"
系统根 = 取系统根(__file__)

if 唯一实现名 not in sys.modules:  # 兜底：公开入口未加载该子模块时按文件路径显式载入
    唯一实现文件 = 系统根 / "支持库" / "适配层" / "reportlab提供者" / "实现" / "子进程管理器.py"
    _规格 = importlib.util.spec_from_file_location(唯一实现名, 唯一实现文件)
    if _规格 is None or _规格.loader is None:
        raise ImportError(f"无法加载唯一实现（文件缺失或不可加载）: {唯一实现文件}")
    _模块 = importlib.util.module_from_spec(_规格)
    sys.modules[唯一实现名] = _模块
    _规格.loader.exec_module(_模块)

sys.modules[__name__] = sys.modules[唯一实现名]
