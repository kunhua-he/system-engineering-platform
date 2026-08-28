"""Tesseract 提供者包级中文入口（外部命令 tesseract 受管执行）。

调用者只从此入口导入，禁止深入 实现/ 目录。
公开能力（分组 OCR识别）：
- 识别图片 → {文本} 或 {词列表}（词级数据，路径/字节二选一）
- 语言包列表 → {语言列表, 数据目录, 数量}
- 版本探针 → {tesseract, 版本, 满足最低版本}
命令路径配置覆盖体系：函数参数 命令路径 > 环境变量 Tesseract提供者_命令路径
> 默认 PATH 探测；显式路径不存在 → 工具缺失，不可执行 → 命令失败，
版本低于最低版本 → 版本不兼容。
所有 tesseract 调用一律走 受管进程（独立进程组 + 超时/取消/上限/零残留）。
"""

from __future__ import annotations

from 支持库.适配层.Tesseract提供者.实现.提供者 import 识别图片
from 支持库.适配层.Tesseract提供者.实现.提供者 import 语言包列表
from 支持库.适配层.Tesseract提供者.实现.提供者 import 版本探针

__all__ = [
    "识别图片",
    "语言包列表",
    "版本探针",
    "注册能力",
]


def 注册能力(注册表) -> None:
    """由支持库加载器调用，向能力注册表注册本库全部能力。"""
    from 公共契约.能力契约.契约 import 能力实现
    import json
    from pathlib import Path
    定义路径 = Path(__file__).resolve().parent / "能力定义.json"
    定义 = json.loads(定义路径.read_text(encoding="utf-8"))
    for 能力 in 定义.get("能力列表", []):
        注册表.注册(能力实现(
            能力id=能力["能力id"],
            包id=定义["包id"],
            实现函数=globals()[能力["能力id"].split(".")[-1]],
            参数=能力.get("参数", []),
            返回="结果型",
            说明=能力.get("说明", ""),
        ))

