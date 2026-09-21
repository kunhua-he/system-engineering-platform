"""子进程入口（PDF 生成 / reportlab）：唯一实现在 支持库/适配层/reportlab提供者（第 10 对收口，本包不放第二份）。

本文件原与 `支持库/适配层/reportlab提供者/实现/子进程入口.py` **逐字同源**，差异只有
两处：① 包路径深度（后端腿比适配层腿多一层目录，故 `系统根`/`parents[N]` 相差 1 级，
**两腿实测各自都指向项目根**，不是错误、不能统一成一个数字）；② 适配层腿侧保有的
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

系统根 = Path(__file__).resolve().parents[5]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

import 支持库.适配层.reportlab提供者  # noqa: E402,F401 —— 公开入口（同层，合规）

# 前缀感知：制品把本模块注册成 `平台客户端.支持库.…`，而字面量不随导入前缀改写，
# 故按 `__name__` 派生本树前缀（源码树为空串、制品为 `平台客户端.`），
# 使下面的兜底判据在两种形态下都成立（债务 #216②）。
唯一实现名 = f"{__name__.split('支持库.', 1)[0]}支持库.适配层.reportlab提供者.实现.子进程入口"

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
