"""四类数值类型契约冻结测试。"""

import math
import unittest

from 公共契约.基础类型.数值类型 import (
    数值类型定义,
    校验数值类型,
    确保数值类型,
)


class 数值类型契约测试(unittest.TestCase):
    def test_四类类型边界已冻结(self):
        self.assertEqual(数值类型定义["整数型"].最小值, -(2**31))
        self.assertEqual(数值类型定义["整数型"].最大值, 2**31 - 1)
        self.assertEqual(数值类型定义["长整数型"].最小值, -(2**63))
        self.assertEqual(数值类型定义["长整数型"].最大值, 2**63 - 1)
        self.assertEqual(数值类型定义["单精度数型"].位数, 32)
        self.assertEqual(数值类型定义["双精度数型"].位数, 64)

    def test_整数与长整数严格边界且拒绝布尔(self):
        self.assertTrue(校验数值类型(-(2**31), "整数型"))
        self.assertTrue(校验数值类型(2**31 - 1, "整数型"))
        self.assertFalse(校验数值类型(2**31, "整数型"))
        self.assertTrue(校验数值类型(2**63 - 1, "长整数型"))
        self.assertFalse(校验数值类型(2**63, "长整数型"))
        self.assertFalse(校验数值类型(True, "整数型"))

    def test_浮点只接受有限数值并区分精度(self):
        self.assertTrue(校验数值类型(1.25, "单精度数型"))
        self.assertFalse(校验数值类型(2**128, "单精度数型"))
        self.assertTrue(校验数值类型(1.25, "双精度数型"))
        self.assertFalse(校验数值类型(math.inf, "双精度数型"))
        self.assertFalse(校验数值类型(1, "双精度数型"))

    def test_非法类型名与值抛出稳定异常(self):
        with self.assertRaises(ValueError):
            校验数值类型(1, "数字型")
        with self.assertRaises(TypeError):
            确保数值类型("1", "整数型")


if __name__ == "__main__":
    unittest.main()
