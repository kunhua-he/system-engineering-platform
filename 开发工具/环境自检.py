"""环境自检（按路径入口）：内部转发到同目录包 `开发工具/环境自检/`。

为什么保留这个同级文件（2026-09-19 拆分）：本入口是**按路径调用**的脚本
（规范与文档里写 `python3.14 开发工具/环境自检.py`），拆成同名目录包后包会遮蔽同名模块，
故按路径这一条腿必须由本文件承担 —— 它只做「自举 + 转发」，判据一行都不在这里。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 工程根入 sys.path 必须**先于**任何仓库级 import：`python3.14 开发工具/环境自检.py`
# 直接执行时仓库根不在 path，第一个 `from 开发工具...` 就会 ModuleNotFoundError
# （开工-20260919-192224-1d69 实测）。此处只调标准库，不依赖仓库符号。
_自举根 = Path(__file__).resolve()
for _候选 in _自举根.parents:
    if (_候选 / "支持库").is_dir() and (_候选 / "开发工具").is_dir():
        _自举根 = _候选
        break
if str(_自举根) not in sys.path:
    sys.path.insert(0, str(_自举根))

from 开发工具.环境自检.入口 import 主

if __name__ == "__main__":
    raise SystemExit(主())
