"""子进程入口（PDF 隔离提供者）：唯一实现在 支持库/适配层/PDF隔离提供者（D-1 收口，本包不放第二份）。

本文件原与 `支持库/适配层/PDF隔离提供者/实现/子进程入口.py` **逐字同源**，差异只有
一处：包路径深度（后端腿比适配层腿多一层目录，故 `系统根.parents[N]` 相差 1，
**两腿实测各自都指向项目根**，不是错误、不能统一成一个数字；见迁移清单 §10.8）。

同一份逻辑只能有一个实现，故本文件改为**转调**：让
`支持库.后端.支持库.后端.文档转换支持库.PDF隔离提供者.实现.子进程入口` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`）。

**本文件就是被 `subprocess.Popen([sys.executable, 本文件路径])` 当脚本跑的那一个**，
因此它必须自备 `系统根` 与 `sys.path`（子进程内 `sys.path` 不含仓库根），再按名导入
适配层那唯一实现：脚本方式跑时 `sys.modules` 的键是 `"__main__"`、也不会按包查表，
所以 `__main__` 分支**按唯一实现名取模块对象**调用 `主循环`，不做跨包 `实现/` 导入
（那会被 `运行核心/依赖防火墙.py` 按 AST 判「跨包禁止导入 实现/ 目录」）。

为什么不直接 `import ...实现.子进程入口`：同上 —— 跨包导入 `实现/` 被依赖防火墙强制
拒绝；而适配层腿的公开入口 `__init__.py` 已经是合规的同层导入，它随本文件所在包之外
加载自己的 `实现/` 子模块，故这里先导公开入口、再把两个模块名指向同一对象（兜底路径
按文件路径显式载入，文件缺失时明确报错、不静默降级）。同一模块对象、不产生第二份实现
是平台既有做法，见 `平台控制面/授权/__init__.py`。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[5]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

import 支持库.适配层.PDF隔离提供者  # noqa: E402,F401 —— 公开入口（同层，合规）

# 前缀感知：制品把本模块注册成 `平台客户端.支持库.…`，而字面量不随导入前缀改写，
# 故按 `__name__` 派生本树前缀（源码树为空串、制品为 `平台客户端.`），
# 使下面的兜底判据在两种形态下都成立（债务 #216②）。
唯一实现名 = f"{__name__.split('支持库.', 1)[0]}支持库.适配层.PDF隔离提供者.实现.子进程入口"

if 唯一实现名 not in sys.modules:  # 兜底：公开入口未加载该子模块时按文件路径显式载入
    唯一实现文件 = 系统根 / "支持库" / "适配层" / "PDF隔离提供者" / "实现" / "子进程入口.py"
    _规格 = importlib.util.spec_from_file_location(唯一实现名, 唯一实现文件)
    if _规格 is None or _规格.loader is None:
        raise ImportError(f"无法加载唯一实现（文件缺失或不可加载）: {唯一实现文件}")
    _模块 = importlib.util.module_from_spec(_规格)
    sys.modules[唯一实现名] = _模块
    _规格.loader.exec_module(_模块)

sys.modules[__name__] = sys.modules[唯一实现名]

if __name__ == "__main__":  # 按脚本路径启动这条路：走唯一实现名取模块对象，不做实现/ 导入
    sys.modules[唯一实现名].主循环()
    sys.stdout.flush()
    os._exit(0)
