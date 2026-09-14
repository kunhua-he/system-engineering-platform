"""网关兼容性回归：新增字段不破坏旧调用，业务字典不被误判为契约违约。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parents[2]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

from 运行核心.统一网关.网关核心 import 网关核心, 网关请求, 网关响应


class 网关兼容性回归(unittest.TestCase):
    """锁定第 21 条：非强制差异放行，强制参数仍明确失败。"""

    def setUp(self):
        self.网关 = 网关核心()

    def test_查询操作多传未知字段仍放行(self):
        请求 = 网关请求(操作="包详情", 参数={"包id": "示例包", "未来字段": "以后新增"})
        self.assertEqual(self.网关._操作参数错误(请求), "")

    def test_查询操作缺少必填字段仍明确失败(self):
        请求 = 网关请求(操作="包详情", 参数={"未来字段": "以后新增"})
        错误 = self.网关._操作参数错误(请求)
        self.assertIn("缺少必填字段", 错误)
        self.assertIn("包id", 错误)

    def test_裸业务字典不再被当成契约违约(self):
        响应 = 网关响应()
        self.网关._设置后端字典结果(响应, {"业务字段": "业务值"})
        self.assertTrue(响应.成功)
        self.assertEqual(响应.值, {"业务字段": "业务值"})
        self.assertEqual(响应.错误码, "")

    def test_缺少值键自动补空值(self):
        响应 = 网关响应()
        self.网关._设置后端字典结果(
            响应, {"成功": True, "错误码": "", "错误说明": ""})
        self.assertTrue(响应.成功)
        self.assertIsNone(响应.值)

    def test_错误字段类型仍然失败(self):
        响应 = 网关响应()
        self.网关._设置后端字典结果(
            响应, {"成功": "是", "值": None, "错误码": "", "错误说明": ""})
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "返回结果不符合契约")


if __name__ == "__main__":
    unittest.main()
