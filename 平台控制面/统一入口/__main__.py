"""`python3.14 -m 平台控制面.统一入口` 的入口：转调 12 稳定操作 CLI 适配器。

与同包 `__init__.py` 的分工：`__init__.py` 是能力面（装配期注册 + 公开名再导出），
本文件只做「命令行入口」这一件事，且**不复制任何参数解析逻辑**——逐字转调
`核心.命令行入口()`（唯一实现点，用法见其 docstring）。
"""
from __future__ import annotations

from 平台控制面.统一入口.核心 import 命令行入口

if __name__ == "__main__":
    raise SystemExit(命令行入口())
