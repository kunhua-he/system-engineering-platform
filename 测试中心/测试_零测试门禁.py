"""零测试门禁测试：证明"零测试不能返回成功"。

覆盖：判断零测试、主函数零套件返回非零、导入失败门禁、跳过门禁。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

import 测试中心
import 测试中心.运行测试 as 运行测试


class Test零测试门禁(unittest.TestCase):
    def test_空套件判定为零测试(self):
        套件 = unittest.TestSuite()
        self.assertTrue(运行测试.判断零测试(套件))

    def test_非空套件判定非零测试(self):
        套件 = unittest.TestSuite()
        套件.addTest(Test零测试门禁("test_空套件判定为零测试"))
        self.assertFalse(运行测试.判断零测试(套件))

    def test_主函数零套件返回非零(self):
        退出码 = 运行测试.主函数(unittest.TestSuite())
        self.assertNotEqual(退出码, 0)

    def test_主函数真实套件返回零(self):
        # 使用小型独立套件（避免运行完整套件导致递归）
        class 小测试(unittest.TestCase):
            def test_通过(self):
                self.assertTrue(True)

        小套件 = unittest.TestSuite()
        小套件.addTest(小测试("test_通过"))
        退出码 = 运行测试.主函数(小套件)
        self.assertEqual(退出码, 0)

    def test_导入失败门禁检测(self):
        结果 = unittest.TestResult()
        失败用例 = unittest.FunctionTestCase(lambda: None)
        结果.startTest(失败用例)
        try:
            raise AssertionError("导入失败")
        except AssertionError:
            结果.addFailure(失败用例, sys.exc_info())
        结果.stopTest(失败用例)
        self.assertTrue(运行测试.判断导入失败(结果))

    def test_无失败时导入门禁通过(self):
        结果 = unittest.TestResult()
        用例 = Test零测试门禁("test_空套件判定为零测试")
        结果.startTest(用例)
        用例.run(结果)
        结果.stopTest(用例)
        self.assertFalse(运行测试.判断导入失败(结果))

    def test_跳过门禁检测(self):
        结果 = unittest.TestResult()
        用例 = Test零测试门禁("test_空套件判定为零测试")
        结果.startTest(用例)
        结果.addSkip(用例, "反向验证")
        结果.stopTest(用例)
        self.assertTrue(运行测试.判断存在跳过(结果))

    def test_主函数遇到跳过返回非零(self):
        class 跳过测试(unittest.TestCase):
            @unittest.skip("反向验证")
            def test_不得伪装成功(self):
                self.fail("本场景不应执行")

        套件 = unittest.TestSuite([跳过测试("test_不得伪装成功")])
        self.assertNotEqual(运行测试.主函数(套件), 0)

    def test_工程缓存正式实现引用门禁在引用清零后通过(self):
        """生产化完成后：测试不得引用工程缓存候选实现，门禁必须通过。"""
        违规文件 = 运行测试.审计工程缓存正式实现引用()
        self.assertEqual(违规文件, [],
                         f"正式测试不得引用工程缓存候选实现: {违规文件[:5]}")


if __name__ == "__main__":
    unittest.main()
