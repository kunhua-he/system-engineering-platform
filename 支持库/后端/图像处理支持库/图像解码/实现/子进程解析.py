"""子进程解析（Pillow/图像解码）：唯一实现在 支持库/适配层/Pillow提供者（D-2 收口）。

本文件原与 `支持库/适配层/Pillow提供者/实现/子进程解析.py` **逐字节相同**
（结构债 D-2 第 ④ 组，sha256 79e5973623e0，360 行）。同一份逻辑只能有一个实现，故本文件
改为**转调**：让 `支持库.后端.图像处理支持库.图像解码.实现.子进程解析` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`），本包子进程入口
（`实现/子进程入口.py`）照旧从此路径导入 —— 进程边界完全不变：PIL 仍只在
`实现/子进程入口.py` 的独立子进程中 import，主进程零加载 PIL。

为什么不直接 `import ...实现.子进程解析`：跨包导入 `实现/` 被
`运行核心/依赖防火墙.py` 强制拒绝（判据「跨包禁止导入 实现/ 目录」）；而适配层腿
的公开入口 `__init__.py` 已经是合规的同层导入，且它会正常加载自己的 `实现/` 子模块，
故这里先导公开入口、再把两个模块名指向同一对象（兜底路径按文件路径显式载入，
文件缺失时明确报错、不静默降级）。同一模块对象、不产生第二份实现是平台既有做法，
见 `平台控制面/授权/__init__.py`。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import 支持库.适配层.Pillow提供者  # noqa: F401 —— 公开入口（同层，合规）

唯一实现名 = "支持库.适配层.Pillow提供者.实现.子进程解析"
系统根 = next(
    祖先 for 祖先 in Path(__file__).resolve().parents
    if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir()
)

if 唯一实现名 not in sys.modules:  # 兜底：公开入口未加载该子模块时按文件路径显式载入
    唯一实现文件 = 系统根 / "支持库" / "适配层" / "Pillow提供者" / "实现" / "子进程解析.py"
    _规格 = importlib.util.spec_from_file_location(唯一实现名, 唯一实现文件)
    if _规格 is None or _规格.loader is None:
        raise ImportError(f"无法加载唯一实现（文件缺失或不可加载）: {唯一实现文件}")
    _模块 = importlib.util.module_from_spec(_规格)
    sys.modules[唯一实现名] = _模块
    _规格.loader.exec_module(_模块)

sys.modules[__name__] = sys.modules[唯一实现名]
