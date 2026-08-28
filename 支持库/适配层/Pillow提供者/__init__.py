"""Pillow 提供者包级中文入口（PIL 独立子进程边界）。

调用者只从此入口导入，禁止深入 实现/ 目录。
公开能力（分组 图像解码）：
- 解码图像 → {格式, 宽度, 高度, 模式}
- 像素统计 → {宽度, 高度, 像素数, 平均颜色{红,绿,蓝}}
- 生成占位图 → {图像b64, 格式, 宽度, 高度}（纯色/渐变/文本）
- 生成缩略图 → {图像b64, 格式, 宽度, 高度}（等比例，只缩不放大）
- 图像EXIF转置 → {图像b64, 格式, 宽度, 高度}（EXIF orientation 转置）
- 透明背景合成 → {图像b64, 格式, 宽度, 高度}（RGBA/LA/P 透明合成背景色）
- 计算感知哈希 → {哈希, 哈希类型}（aHash/dHash/pHash）
- 缩放图像 → {图像b64, 格式, 宽度, 高度}（精确尺寸，宽高可空）
- 重编码图像 → {图像b64, 格式, 宽度, 高度}（JPEG/PNG/WebP）
主进程绝不 import PIL；PIL 只在 实现/子进程入口.py 的独立子进程中加载。
"""

from __future__ import annotations

from 支持库.适配层.Pillow提供者.实现.提供者 import 解码图像
from 支持库.适配层.Pillow提供者.实现.提供者 import 像素统计
from 支持库.适配层.Pillow提供者.实现.提供者 import 生成占位图
from 支持库.适配层.Pillow提供者.实现.提供者 import 生成缩略图
from 支持库.适配层.Pillow提供者.实现.提供者 import 图像EXIF转置
from 支持库.适配层.Pillow提供者.实现.提供者 import 透明背景合成
from 支持库.适配层.Pillow提供者.实现.提供者 import 计算感知哈希
from 支持库.适配层.Pillow提供者.实现.提供者 import 缩放图像
from 支持库.适配层.Pillow提供者.实现.提供者 import 重编码图像

__all__ = [
    "解码图像",
    "像素统计",
    "生成占位图",
    "生成缩略图",
    "图像EXIF转置",
    "透明背景合成",
    "计算感知哈希",
    "缩放图像",
    "重编码图像",
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

