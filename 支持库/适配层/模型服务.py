#!/usr/bin/env python3
"""模型服务对外入口（根下平铺件：自举 + 等价再导出腿）。

**#96 包化后**：真实实现已搬到 `支持库/适配层/模型服务提供者/实现/模型服务.py`，
该提供者有 `包声明.json` / `依赖锁.json` / `生命周期契约.json`，进依赖生命周期审计。

本件**保留**，因为它是**按路径被拉起**的脚本 ——
`大语言模型支持库/模型连接器/实现/本地启动准备与守卫.py`：

   服务脚本 = 取系统根(__file__) / "支持库" / "适配层" / "模型服务.py"
   return [sys.executable, str(服务脚本), "--model-path", …, "--model-type", …, "--port", …]

路径与命令行参数**逐字不变**；本件只做自举 + 转发，**不复制第二套实现**
（哲学：不保留旧腿、结果唯一即收口）。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _自举系统根() -> Path:
    """向上找同时含 `支持库` 与 `公共契约` 的祖先（源码树与制品同口径）。"""
    for 祖先 in Path(__file__).resolve().parents:
        if (祖先 / "支持库").is_dir() and (祖先 / "公共契约").is_dir():
            return 祖先
    return Path(__file__).resolve().parents[2]


_系统根 = _自举系统根()
if str(_系统根) not in sys.path:
    sys.path.insert(0, str(_系统根))

from 支持库.适配层.模型服务提供者 import (  # noqa: E402  （自举后导入）
    创建应用,
    停止服务,
    模型服务,
    主程序,
)

__all__ = [
    "模型服务",
    "创建应用",
    "停止服务",
    "主程序",
]


if __name__ == "__main__":
    主程序()
