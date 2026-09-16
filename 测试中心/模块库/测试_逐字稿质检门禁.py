"""模块库.直播逐字稿.实现.质检门禁 纯计算测试：底稿有效性、长度比、数字保留率、异常残句、待确认与模式附加。

全部用内联字符串数据，不依赖模型、网络、文件；只断言真实返回字典的字段与失败原因。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.直播逐字稿.实现.质检门禁 import 质检, 统计异常残句, 统计待确认

模式一 = {"模式": 1, "名称": "直播逐字稿",
          "质检规则": {"最小长度比": 0.7, "最小数字保留率": 0.85, "关键数字全保留": False, "禁止删减": False}}
模式二 = {"模式": 2, "名称": "方案逐字稿",
          "质检规则": {"最小长度比": 0.55, "最小数字保留率": 0.9, "关键数字全保留": True, "禁止删减": False}}
模式七 = {"模式": 7, "名称": "1:1 还原稿",
          "质检规则": {"最小长度比": 0.9, "最小数字保留率": 0.98, "关键数字全保留": True, "禁止删减": True}}

长句 = "门店今天成交了二十五单，总金额是一万二千元。"
短句 = "门店今天成交二十五单，总金额一万二千元。"


class Test质检判定(unittest.TestCase):
    def test_正常通过(self):
        底稿 = "今天讲三个重点，第一个是价格1288元，第二个是交付周期，第三个是售后承诺。"
        报告 = 质检(底稿, 底稿, 模式一)
        self.assertTrue(报告["通过"])
        self.assertEqual(报告["失败原因"], [])
        self.assertEqual(报告["长度比"], 1.0)
        self.assertEqual(报告["数字保留率"], 1.0)
        self.assertEqual(报告["模式"], "1 直播逐字稿")

    def test_返回结构键齐全(self):
        报告 = 质检("内容。", "内容。", 模式一)
        self.assertEqual(set(报告), {"通过", "长度比", "数字保留率", "异常残句",
                                     "待确认数", "模式", "模式附加", "失败原因"})

    def test_长度比不足不通过(self):
        报告 = 质检(长句, "门店今天成交。", 模式一)
        self.assertFalse(报告["通过"])
        self.assertLess(报告["长度比"], 0.7)
        self.assertTrue(any("长度比" in 原因 and "0.7" in 原因 for 原因 in 报告["失败原因"]))

    def test_数字丢失不通过(self):
        报告 = 质检("门店价格是1288元，库存300件，活动到月底结束，请大家抓紧下单。",
                  "门店价格很实惠，库存也很充足，活动快结束了，请大家抓紧下单。", 模式一)
        self.assertFalse(报告["通过"])
        self.assertEqual(报告["数字保留率"], 0.0)
        全部原因 = "".join(报告["失败原因"])
        self.assertIn("数字保留率", 全部原因)
        self.assertIn("1288", 全部原因)

    def test_关键数字全保留触发不通过(self):
        报告 = 质检("门店已经开到3000家，单店价格1288元，覆盖全国大部分城市。",
                  "门店已经开到了很多家，单店价格1288元，覆盖全国大部分城市。", 模式二)
        self.assertFalse(报告["通过"])
        self.assertEqual(报告["数字保留率"], 0.5)
        self.assertTrue(any("关键数字未全部保留" in 原因 and "3000" in 原因 for 原因 in 报告["失败原因"]))

    def test_禁止删减触发不通过(self):
        报告 = 质检(长句, 短句, 模式七)
        self.assertFalse(报告["通过"])
        self.assertGreaterEqual(报告["长度比"], 0.9)
        self.assertTrue(any("禁止删减" in 原因 for 原因 in 报告["失败原因"]))
        self.assertEqual(len(报告["失败原因"]), 1)

    def test_异常残句计数(self):
        文本 = "\n".join(["正常内容在这里。", "…", "啊", "免费敷面膜" * 15])
        self.assertEqual(统计异常残句(文本), 3)
        报告 = 质检(文本, 文本, 模式一)
        self.assertEqual(报告["异常残句"], 3)
        self.assertFalse(报告["通过"])
        self.assertTrue(any("异常残句" in 原因 for 原因 in 报告["失败原因"]))

    def test_待确认计数不阻断通过(self):
        文本 = "客户说【听不清】，另一处【听不清】，这里【待确认】。"
        self.assertEqual(统计待确认(文本), 3)
        报告 = 质检(文本, 文本, 模式一)
        self.assertEqual(报告["待确认数"], 3)
        self.assertTrue(报告["通过"])

    def test_原始为空不通过(self):
        """空底稿是「无法判定」不是「满分」：必须判不通过并写明原因（旧行为恒过，已修）。"""
        报告 = 质检("", "没有原始文本时按 1.0 计。", 模式一)
        self.assertFalse(报告["通过"])
        self.assertEqual(报告["长度比"], 0.0)
        self.assertEqual(报告["数字保留率"], 0.0)
        self.assertTrue(any("有效底稿为空/过短" in 原因 for 原因 in 报告["失败原因"]))

    def test_超短底稿不通过(self):
        """底稿只有 1 字、成稿长 18 倍：旧行为算出 长度比=18.0 照样通过，现在必须判不通过。"""
        报告 = 质检("短", "完全不同的很长很长的成稿内容xxxx", 模式一)
        self.assertFalse(报告["通过"])
        self.assertEqual(报告["长度比"], 0.0)
        self.assertTrue(any("有效底稿为空/过短" in 原因 for 原因 in 报告["失败原因"]))

    def test_模式非字典如实写明原因(self):
        报告 = 质检("内容。", "内容。", None)
        self.assertFalse(报告["通过"])
        self.assertEqual(报告["模式"], "未指定")
        self.assertTrue(any("模式数据不合法" in 原因 for 原因 in 报告["失败原因"]))

    def test_模式附加回填阈值(self):
        报告 = 质检("内容。", "内容。", 模式七)
        self.assertEqual(报告["模式附加"], {"模式名称": "1:1 还原稿", "最小长度比": 0.9,
                                            "最小数字保留率": 0.98, "关键数字全保留": True, "禁止删减": True})

    def test_缺省阈值生效(self):
        报告 = 质检(长句, "门店今天成交。", {"模式": 1, "名称": "直播逐字稿"})
        self.assertFalse(报告["通过"])
        self.assertEqual(报告["模式附加"]["最小长度比"], 0.7)
        self.assertEqual(报告["模式附加"]["最小数字保留率"], 0.85)

    def test_非文本输入按空串处理(self):
        """非文本输入按空串处理，等同空底稿：判不通过，且不抛裸异常。"""
        报告 = 质检(None, None, 模式一)
        self.assertFalse(报告["通过"])
        self.assertEqual(报告["长度比"], 0.0)
        self.assertEqual(报告["待确认数"], 0)
        self.assertTrue(any("有效底稿为空/过短" in 原因 for 原因 in 报告["失败原因"]))


if __name__ == "__main__":
    unittest.main()
