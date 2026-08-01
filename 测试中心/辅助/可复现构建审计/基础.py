"""工作包17 反向审计共享基础：环境常量与真实执行辅助。

全部辅助均为真实执行（真实临时工作区、真实写盘、真实 sha256），
导入正式生产实现 平台控制面.包仓库.可复现构建器。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.包仓库.可复现构建器 import 可复现构建器

冻结时刻甲 = "2024-06-01 08:00:00"
冻结时刻乙 = "2025-01-01 00:00:00"
主机甲 = "构建机-华南-甲"
主机乙 = "构建机-华北-乙"
基本文件表 = {
    "清单/物料.txt": "版本={时间戳}\n主机={主机名}\n位置={工作区路径}\n",
    "说明.md": "说明文本\n",
}


def 新实例() -> 可复现构建器:
    return 可复现构建器()


def 临时工作区(前缀: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=前缀))


def 构建摘要表(输入: dict, 工作区: Path) -> dict:
    _, 摘要表 = 新实例().构建(输入, 工作区)
    return 摘要表


def 清理(*目录表: Path) -> None:
    for 目录 in 目录表:
        shutil.rmtree(目录, ignore_errors=True)
