"""开工编排 模块定向测试骨架（模块模板生成器产出，按需补充真实场景）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.开工编排 import 开工准备, 注册能力

class Test开工编排模块(unittest.TestCase):
    """装配冒烟：公开入口可导入、注册能力齐全、调用返回统一结果。"""

    def test_公开入口可导入(self):
        for 能力名 in ['开工准备']:
            self.assertTrue(callable(globals()[能力名]), f"{能力名} 未从公开入口导出")

    def test_注册能力齐全(self):
        from 公共契约.能力契约.契约 import 能力注册表
        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in ['开工编排.开工准备']:
            self.assertIn(能力id, 注册表.能力id列表)

    def test_开工准备_返回统一结果(self):
        返回值 = 开工准备("", "", [], 0, "")
        self.assertIsInstance(返回值, 结果)


if __name__ == "__main__":
    unittest.main()
