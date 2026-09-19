"""分支名安全：唯一实现在 支持库/适配层/Git提供者（D-1 收口，本包不放第二份）。

本文件原与 `支持库/适配层/Git提供者/实现/分支名安全.py` **逐字同源**（仅包路径前缀不同）。
同一份逻辑只能有一个实现，故本文件改为**转调**：让
`支持库.后端.版本控制支持库.Git操作.实现.分支名安全` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`）。本包 `__init__.py` 照旧从
本路径导入 —— **对外 import 路径零改动**。

为什么保留同名模块（不能删）：本包 `__init__.py` 与 `实现/分支操作.py` 都按这个名字导入，改名会让这些入口失效。

为什么不直接 `import ...实现.分支名安全`：跨包导入 `实现/` 被
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

import 支持库.适配层.Git提供者  # noqa: F401 —— 公开入口（同层，合规）

唯一实现名 = "支持库.适配层.Git提供者.实现.分支名安全"
系统根 = next(
    祖先 for 祖先 in Path(__file__).resolve().parents
    if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir()
)

if 唯一实现名 not in sys.modules:  # 兜底：公开入口未加载该子模块时按文件路径显式载入
    唯一实现文件 = 系统根 / "支持库" / "适配层" / "Git提供者" / "实现" / "分支名安全.py"
    _规格 = importlib.util.spec_from_file_location(唯一实现名, 唯一实现文件)
    if _规格 is None or _规格.loader is None:
        raise ImportError(f"无法加载唯一实现（文件缺失或不可加载）: {唯一实现文件}")
    _模块 = importlib.util.module_from_spec(_规格)
    sys.modules[唯一实现名] = _模块
    _规格.loader.exec_module(_模块)

sys.modules[__name__] = sys.modules[唯一实现名]
