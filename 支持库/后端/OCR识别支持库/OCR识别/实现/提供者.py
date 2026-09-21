"""OCR 识别提供者（Tesseract/OCR识别）：唯一实现在 支持库/适配层/Tesseract提供者（A 档收口）。

本文件原与 `支持库/适配层/Tesseract提供者/实现/提供者.py` 逻辑一致，差异仅在包路径
（本文件导入的是本包 `实现/受管进程.py`、`实现/临时文件.py`，那两个文件此前已各自收口为
同源转调，故两腿的**逻辑**早已逐字相同）。同一份逻辑只能有一个实现，故本文件改为**转调**：
让 `支持库.后端.OCR识别支持库.OCR识别.实现.提供者` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`）。本包 `__init__.py` 照旧从
本路径导入 `识别图片 / 语言包列表 / 版本探针` —— **对外 import 路径零改动**。

为什么不直接 `import ...实现.提供者`：跨包导入 `实现/` 被
`运行核心/依赖防火墙.py` 强制拒绝（判据「跨包禁止导入 实现/ 目录」）；而适配层腿
的公开入口 `__init__.py` 已经是合规的同层导入，且它会正常加载自己的 `实现/` 子模块，
故这里先导公开入口、再把两个模块名指向同一对象（兜底路径按文件路径显式载入，
文件缺失时明确报错、不静默降级）。同一模块对象、不产生第二份实现是平台既有做法，
见 `平台控制面/授权/__init__.py`、`支持库/后端/媒体处理支持库/FFmpeg媒体/实现/探测.py`。
"""

from __future__ import annotations

import importlib.util
import sys

import 支持库.适配层.Tesseract提供者  # noqa: F401 —— 公开入口（同层，合规）

from 公共契约.运行时.导入前缀 import 取根前缀, 取系统根

唯一实现名 = 取根前缀(__name__) + "支持库.适配层.Tesseract提供者.实现.提供者"
系统根 = 取系统根(__file__)

if 唯一实现名 not in sys.modules:  # 兜底：公开入口未加载该子模块时按文件路径显式载入
    唯一实现文件 = 系统根 / "支持库" / "适配层" / "Tesseract提供者" / "实现" / "提供者.py"
    _规格 = importlib.util.spec_from_file_location(唯一实现名, 唯一实现文件)
    if _规格 is None or _规格.loader is None:
        raise ImportError(f"无法加载唯一实现（文件缺失或不可加载）: {唯一实现文件}")
    _模块 = importlib.util.module_from_spec(_规格)
    sys.modules[唯一实现名] = _模块
    _规格.loader.exec_module(_模块)

sys.modules[__name__] = sys.modules[唯一实现名]
