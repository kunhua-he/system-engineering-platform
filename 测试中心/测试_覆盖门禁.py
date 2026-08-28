"""测试覆盖门禁：所有测试文件必须唯一归属，不能静默漏测或重复计数。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 测试中心.运行测试 import (
    常规阶段顺序表,
    收集阶段文件,
    校验测试覆盖,
)


class 测试覆盖门禁(unittest.TestCase):
    """覆盖清单的纯逻辑门禁。"""

    def test_完整且唯一的覆盖通过(self) -> None:
        文件甲 = Path("测试中心/测试_甲.py")
        文件乙 = Path("测试中心/测试_乙.py")
        结果 = 校验测试覆盖(
            {"阶段甲": [文件甲], "阶段乙": [文件乙]},
            [文件甲, 文件乙],
        )
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["漏测"], [])
        self.assertEqual(结果["重复"], {})

    def test_漏测必须失败(self) -> None:
        文件甲 = Path("测试中心/测试_甲.py")
        文件乙 = Path("测试中心/测试_乙.py")
        结果 = 校验测试覆盖({"阶段甲": [文件甲]}, [文件甲, 文件乙])
        self.assertFalse(结果["成功"], 结果)
        self.assertEqual(结果["漏测"], [文件乙])

    def test_跨阶段重复必须失败(self) -> None:
        文件甲 = Path("测试中心/测试_甲.py")
        结果 = 校验测试覆盖(
            {"阶段甲": [文件甲], "阶段乙": [文件甲]},
            [文件甲],
        )
        self.assertFalse(结果["成功"], 结果)
        self.assertEqual(set(结果["重复"][文件甲]), {"阶段甲", "阶段乙"})

    def test_空阶段必须失败(self) -> None:
        结果 = 校验测试覆盖({"阶段甲": []}, [])
        self.assertFalse(结果["成功"], 结果)
        self.assertEqual(结果["阶段空缺"], ["阶段甲"])

    def test_当前阶段表不得跨阶段重复文件(self) -> None:
        阶段文件表 = {
            阶段名: 收集阶段文件(匹配表)
            for 阶段名, 匹配表 in 常规阶段顺序表
        }
        全部文件 = sorted(
            {文件 for 文件表 in 阶段文件表.values() for 文件 in 文件表},
            key=str,
        )
        结果 = 校验测试覆盖(阶段文件表, 全部文件)
        self.assertTrue(结果["成功"], 结果)


if __name__ == "__main__":
    unittest.main()
