"""网关兼容性回归：新增字段不破坏旧调用，业务字典不被误判为契约违约。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parents[2]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

from 运行核心.统一网关.网关核心 import 网关核心, 网关请求, 网关响应
from 公共契约.基础类型.逻辑类型 import 真, 假


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
            响应, {"成功": 真, "错误码": "", "错误说明": ""})
        self.assertTrue(响应.成功)
        self.assertIsNone(响应.值)

    def test_错误字段类型仍然失败(self):
        响应 = 网关响应()
        self.网关._设置后端字典结果(
            响应, {"成功": "是", "值": None, "错误码": "", "错误说明": ""})
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "返回结果不符合契约")


class 假实现:
    """最小能力声明：一个必填文本参数。"""

    参数 = [{"名称": "输入文本", "类型": "文本型", "必填": 真}]


class 假注册表:
    def 获取(self, 能力id):
        return 假实现() if 能力id == "示例.包.示例能力" else None


class 假后端:
    """记录能力的真实入参，用于验证未知字段没有透给实现。"""

    def __init__(self):
        self.注册表 = 假注册表()
        self.收到参数 = None

    def 调用(self, 能力id, 参数, 上下文=None, 超时秒=None):
        from 公共契约.基础类型.结果类型 import 结果

        self.收到参数 = dict(参数)
        return 结果.成功结果({"收到": dict(参数)})


class 网关能力入参兼容(unittest.TestCase):
    """能力调用层同样只拦「必填缺失/类型不符」，未知字段在边界被剔除。"""

    def setUp(self):
        self.后端 = 假后端()
        self.网关 = 网关核心(self.后端)

    def _调用(self, 参数: dict):
        return self.网关.处理(网关请求(
            操作="调用能力", 能力id="示例.包.示例能力", 参数=参数,
            权限范围=["全部"],
        ))

    def test_未知参数被剔除而不是报错(self):
        响应 = self._调用({"输入文本": "真实值", "未来字段": "以后新增"})
        self.assertTrue(响应.成功, 响应.错误说明)
        self.assertEqual(self.后端.收到参数, {"输入文本": "真实值"})

    def test_必填缺失仍明确失败(self):
        响应 = self._调用({"未来字段": "以后新增"})
        self.assertFalse(响应.成功)
        self.assertIn("缺少必填参数", 响应.错误说明)

    def test_类型不符仍明确失败(self):
        响应 = self._调用({"输入文本": 123})
        self.assertFalse(响应.成功)
        self.assertIn("必须是", 响应.错误说明)


class 网关版本回报(unittest.TestCase):
    """哲学第 21 条：带旧版本号请求照常放行，并回报请求版本/当前版本/差异原因。"""

    def setUp(self):
        self.后端 = 假后端()
        self.网关 = 网关核心(self.后端)

    def _请求(self, 版本: str = ""):
        return self.网关.处理(网关请求(
            操作="调用能力", 能力id="示例.包.示例能力",
            参数={"输入文本": "值"}, 权限范围=["全部"], 请求版本=版本,
        ))

    def test_旧版本号不失败且回报三项信息(self):
        响应 = self._请求("1.0.0")
        self.assertTrue(响应.成功, 响应.错误说明)
        self.assertEqual(响应.请求版本, "1.0.0")
        self.assertTrue(响应.当前版本)
        self.assertIn("不一致", 响应.版本差异)

    def test_版本一致时差异为空(self):
        from 公共契约.版本规则.契约版本 import 契约版本

        响应 = self._请求(契约版本)
        self.assertTrue(响应.成功)
        self.assertEqual(响应.当前版本, 契约版本)
        self.assertEqual(响应.版本差异, "")

    def test_响应信封带版本三键(self):
        信封 = self._请求().转字典()
        for 键 in ("请求版本", "当前版本", "版本差异"):
            self.assertIn(键, 信封, f"信封必须包含 {键}（只增不改不删）")


if __name__ == "__main__":
    unittest.main()
