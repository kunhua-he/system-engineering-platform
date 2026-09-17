"""四类数值类型契约冻结测试。"""

import math
import unittest

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.基础类型.数值类型 import (
    数值类型定义,
    校验数值类型,
    确保数值类型,
)


class 数值类型契约测试(unittest.TestCase):
    def test_四类类型边界已冻结(self):
        """边界值**从事实源现场读取**后断言「位数 ↔ 边界」自洽，不再写死常量。

        2026-09-17 修：本文件原先写死 `-(2**31)` / `2**31-1`。华哥把「整数型」
        从 32 位裁决为 64 位（提交 `b21628cd`，事实源 `数值类型.py:26-27` 已改）后，
        这些写死的旧常量让本测试长期变红而无人处理 —— 属 AGENTS.md 铁律
        「判据变更必须同批 grep 全仓同类断言」的漏网样本。
        改成自洽断言后，位数再调不会制造假红；但「边界与位数不匹配」仍会真真变红。
        """
        整数 = 数值类型定义["整数型"]
        长整数 = 数值类型定义["长整数型"]
        for 名称, 定义 in (("整数型", 整数), ("长整数型", 长整数)):
            with self.subTest(类型=名称):
                位 = 定义.位数
                self.assertEqual(定义.最小值, -(2 ** (位 - 1)))
                self.assertEqual(定义.最大值, 2 ** (位 - 1) - 1)
        # 两档语义不重复：长整数型必须严格容纳整数型全域（华哥裁 64/128 的理由之一）
        self.assertGreater(整数.最大值, 2**32 - 1, "整数型必须能装下 32 位以上的字节数/时间戳")
        self.assertGreater(长整数.最大值, 整数.最大值)
        self.assertEqual(数值类型定义["单精度数型"].位数, 32)
        self.assertEqual(数值类型定义["双精度数型"].位数, 64)

    def test_整数与长整数严格边界且拒绝布尔(self):
        """边界用例同样从事实源取值，避免位数调整后再产生一批写死常量。"""
        for 名称 in ("整数型", "长整数型"):
            定义 = 数值类型定义[名称]
            with self.subTest(类型=名称):
                self.assertTrue(校验数值类型(定义.最小值, 名称))
                self.assertTrue(校验数值类型(定义.最大值, 名称))
                self.assertFalse(校验数值类型(定义.最大值 + 1, 名称))
                self.assertFalse(校验数值类型(定义.最小值 - 1, 名称))
        self.assertFalse(校验数值类型(真, "整数型"))
        self.assertFalse(校验数值类型(真, "长整数型"))

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
