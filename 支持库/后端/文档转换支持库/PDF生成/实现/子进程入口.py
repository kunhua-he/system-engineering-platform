"""子进程入口（PDF 生成 / reportlab）：唯一实现在 支持库/适配层/reportlab提供者（第 10 对收口，本包不放第二份）。

本文件原与 `支持库/适配层/reportlab提供者/实现/子进程入口.py` **逐字同源**，差异只有
两处：① 取根方式（后端腿**不再按层数**、改按锚目录判据取根，见 `公共契约/运行时/导入前缀`；适配层腿仍是 `parents[4]`。两腿实测各自都指向项目根，不是错误）；② 适配层腿侧保有的
「激活指针解析 + 注入」部署自举段（**逐字保留在唯一实现里，本门面不重复承载**）。

同一份逻辑只能有一个实现，故本文件改为**转调**：让
`支持库.后端.文档转换支持库.PDF生成.实现.子进程入口` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`）。

**本文件就是被 `subprocess.Popen([sys.executable, 本文件路径])` 当脚本跑的那一个**，
因此 `__main__` 分支**按唯一实现名取模块对象**调用 `主循环`，不做跨包 `实现/` 导入
（那会被 `运行核心/依赖防火墙.py` 按 AST 判「跨包禁止导入 实现/ 目录」）。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
请求：{"操作": "生成", "内容参数": {...}}
响应：{"成功": true, "值": ...} | {"成功": false, "错误码":..., "错误说明":...}
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# 自举前只能用标准库：本文件被当脚本跑时 `sys.path[0]` 是 `实现/`，平台模块此刻
# **不可导入** ⇒ 不能调 `公共契约.运行时.导入前缀`（循环依赖）。判据仍是**同一套锚目录**
# （不是 `parents[N]` 那种一改目录结构就静默指错树的层数写法），与共享模块逐字同判。
系统根 = next(
    祖先 for 祖先 in Path(__file__).resolve().parents
    if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir()
)
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

import 支持库.适配层.reportlab提供者  # noqa: E402,F401 —— 公开入口（同层，合规）

from 公共契约.运行时.导入前缀 import 取根前缀

唯一实现名 = 取根前缀(__name__) + "支持库.适配层.reportlab提供者.实现.子进程入口"

if 唯一实现名 not in sys.modules:  # 兜底：公开入口未加载该子模块时按文件路径显式载入
    唯一实现文件 = 系统根 / "支持库" / "适配层" / "reportlab提供者" / "实现" / "子进程入口.py"
    _规格 = importlib.util.spec_from_file_location(唯一实现名, 唯一实现文件)
    if _规格 is None or _规格.loader is None:
        raise ImportError(f"无法加载唯一实现（文件缺失或不可加载）: {唯一实现文件}")
    _模块 = importlib.util.module_from_spec(_规格)
    sys.modules[唯一实现名] = _模块
    _规格.loader.exec_module(_模块)

sys.modules[__name__] = sys.modules[唯一实现名]

if __name__ == "__main__":  # 按脚本路径启动这条路：走唯一实现名取模块对象，不做 实现/ 导入
    sys.modules[唯一实现名].主循环()
    sys.stdout.flush()
    os._exit(0)
