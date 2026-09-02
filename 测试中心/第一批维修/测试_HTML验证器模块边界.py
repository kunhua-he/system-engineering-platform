"""HTML 验证子系统职责模块边界回归。"""
from __future__ import annotations

import unittest


class 模型边界测试(unittest.TestCase):
    def test_模型从职责模块导出(self) -> None:
        from 开发工具.HTML验证.单步场景 import 验证场景, 验证步骤
        from 开发工具.HTML验证.多步场景 import 多步骤验证场景, 验证场景束
        from 开发工具.HTML验证.验证报告 import 验证结果, 验证报告

        self.assertEqual(验证场景.__module__, "开发工具.HTML验证.单步场景")
        self.assertEqual(验证步骤.__module__, "开发工具.HTML验证.单步场景")
        self.assertEqual(多步骤验证场景.__module__, "开发工具.HTML验证.多步场景")
        self.assertEqual(验证场景束.__module__, "开发工具.HTML验证.多步场景")
        self.assertEqual(验证结果.__module__, "开发工具.HTML验证.验证报告")
        self.assertEqual(验证报告.__module__, "开发工具.HTML验证.验证报告")

    def test_常量从唯一模块导出(self) -> None:
        from 开发工具.HTML验证 import 常量

        self.assertEqual(常量.固定端口, 45080)
        self.assertEqual(常量.固定端口池, "45080-45180")
        self.assertGreaterEqual(常量.默认并发, 8)


if __name__ == "__main__":
    unittest.main()
