"""公共契约：能力注册表与契约一致性测试。"""

from __future__ import annotations
from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import unittest

from 公共契约.能力契约.契约 import 能力实现, 能力注册表


def _加(甲: int, 乙: int) -> int:
    return 甲 + 乙


class Test能力注册表(unittest.TestCase):
    def setUp(self):
        self.注册表 = 能力注册表()

    def test_注册与获取(self):
        实现 = 能力实现(能力id="测试.加", 包id="甲", 实现函数=_加, 参数=[{"名称": "甲"}, {"名称": "乙"}], 返回="整数")
        self.注册表.注册(实现)
        self.assertIsNotNone(self.注册表.获取("测试.加"))

    def test_重复注册拒绝(self):
        实现 = 能力实现(能力id="测试.加", 包id="甲", 实现函数=_加, 参数=[], 返回="整数")
        self.注册表.注册(实现)
        with self.assertRaises(ValueError):
            self.注册表.注册(能力实现(能力id="测试.加", 包id="乙", 实现函数=_加, 参数=[], 返回="整数"))

    def test_契约调用真实返回值(self):
        实现 = 能力实现(能力id="测试.加", 包id="甲", 实现函数=_加, 参数=[{"名称": "甲"}, {"名称": "乙"}], 返回="整数")
        self.注册表.注册(实现)
        结果 = self.注册表.获取("测试.加").调用(甲=1, 乙=2)
        self.assertEqual(结果, 3)

    def test_未知参数拒绝(self):
        实现 = 能力实现(能力id="测试.加", 包id="甲", 实现函数=_加, 参数=[{"名称": "甲"}], 返回="整数")
        self.注册表.注册(实现)
        with self.assertRaises(TypeError):
            self.注册表.获取("测试.加").调用(甲=1, 乙=2)

    def test_搜索按返回类型(self):
        self.注册表.注册(能力实现(能力id="测试.文本", 包id="甲", 实现函数=lambda: "x", 参数=[], 返回="文本"))
        self.注册表.注册(能力实现(能力id="测试.数字", 包id="甲", 实现函数=lambda: 1, 参数=[], 返回="整数"))
        self.assertEqual(len(self.注册表.搜索(返回类型="整数")), 1)


if __name__ == "__main__":
    unittest.main()
