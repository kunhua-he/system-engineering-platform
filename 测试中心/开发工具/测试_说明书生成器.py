"""说明书生成器测试：真实包生成结构完整/重复生成拒绝覆盖/路径逃逸拒绝。

覆盖：能力id/参数表/返回结构/错误码表/调用示例/验证状态六要素齐全、
骨架示例如实标注、输出根目录不存在拒绝、符号链接逃逸拒绝。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.组件规范支持库 import (
    生成说明书, 生成说明书文本, 校验输出目标,
)

系统根 = Path(__file__).resolve().parents[2]
Pillow包 = 系统根 / "支持库" / "适配层" / "Pillow提供者"


class Test说明书生成器(unittest.TestCase):
    """说明书生成器闭环测试。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp())
        self.输出根 = self.临时 / "输出"
        self.输出根.mkdir()

    def test_真实Pillow包生成结构完整(self):
        """对真实提供者生成说明书，六要素齐全。"""
        目标 = 生成说明书(Pillow包, self.输出根)
        self.assertTrue(目标.is_file())
        文本 = 目标.read_text(encoding="utf-8")
        for 片段 in [
            "# Pillow提供者 使用说明",
            "## 能力清单",
            "图像解码.解码图像",
            "图像解码.像素统计",
            "图像解码.生成占位图",
            "**参数表**",
            "| 参数 | 类型 | 必填 | 默认值 | 说明 |",
            "**返回结构**",
            "**错误码表**",
            "**调用示例**",
            "```python",
            "**验证状态**",
            "已纳入验证场景：Pillow提供者.真实最小图像处理链（资产（测试中心/支持库/测试_Pillow提供者.py））",
        ]:
            self.assertIn(片段, 文本)

    def test_参数表含必填与默认值(self):
        文本 = 生成说明书文本(Pillow包)
        self.assertIn("| 字节 | 字节集型 | 是 | None | 图像字节内容", 文本)
        self.assertIn("| 超时秒 | 双精度数型 | 否 | 60 | 子进程超时", 文本)

    def test_骨架示例如实标注(self):
        """能力搜索数据无现成示例时按参数生成骨架并标注需验证。"""
        文本 = 生成说明书文本(Pillow包)
        self.assertIn("图像解码.解码图像(字节=值, 超时秒=值)", 文本)
        self.assertIn("示例为骨架需验证：能力搜索数据无现成示例，按参数自动生成。", 文本)

    def test_重复生成拒绝覆盖(self):
        生成说明书(Pillow包, self.输出根)
        with self.assertRaises(FileExistsError):
            生成说明书(Pillow包, self.输出根)
        with self.assertRaises(FileExistsError):
            校验输出目标(Pillow包, self.输出根)

    def test_路径逃逸拒绝(self):
        """输出根目录下说明目录为符号链接指向外部 → 拒绝。"""
        外部 = self.临时 / "外部"
        外部.mkdir()
        说明目录 = self.输出根 / "说明"
        try:
            说明目录.symlink_to(外部, target_is_directory=True)
        except OSError:
            self.skipTest("当前环境不支持符号链接")
        with self.assertRaises(ValueError):
            生成说明书(Pillow包, self.输出根)

    def test_输出根目录不存在拒绝(self):
        with self.assertRaises(ValueError):
            生成说明书(Pillow包, self.临时 / "不存在")


if __name__ == "__main__":
    unittest.main()
