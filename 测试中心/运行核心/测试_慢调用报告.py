"""慢调用报告定向测试：从**权威审计账本**派生，不另存第二份记录。

华哥 2026-09-21 裁决「html 需要加上一个调用时间的日志，超过 10 秒的需要优化，
超过 3 秒的可以考虑优化」。此前实现是**另开一份** `调用耗时日志.jsonl`，
与审计账本落在**不同根**（缓存根 vs 运行数据根）、属同一事实的第二套实现，
已按哲学 1.2 删除；现在「哪里慢」一律从账本派生。本文件锁住四条不变式：

  ① 分级阈值是华哥口径（3 秒考虑优化 / 10 秒必须优化），边界值归入该级；
  ② 亚秒调用不进慢清单（报告只回答「哪里慢」，不搬全量流水）；
  ③ 聚合与排序正确（按能力聚合条数/最慢/平均，最慢明细降序）；
  ④ **不落第二份文件**（报告是只读派生，账本目录里除账本外不多出任何东西）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.运行诊断.安全审计.安全审计 import (
    安全审计, 默认必须优化秒, 默认考虑优化秒,
)


class 报告测试基类(unittest.TestCase):
    """每个用例一个独立临时账本目录 —— 绝不触碰真实审计账本。"""

    def setUp(self):
        self.临时 = tempfile.TemporaryDirectory()
        self.账本目录 = Path(self.临时.name) / "审计"
        self.审计 = 安全审计(存储目录=self.账本目录)

    def tearDown(self):
        self.临时.cleanup()

    def 记(self, 能力id: str, 耗时毫秒: float, 成功: bool = True):
        return self.审计.记录(操作="调用能力", 能力id=能力id,
                             耗时毫秒=耗时毫秒, 成功=成功)


class 阈值测试(unittest.TestCase):
    def test_默认阈值是华哥口径(self):
        self.assertEqual(3.0, 默认考虑优化秒)
        self.assertEqual(10.0, 默认必须优化秒)


class 分级测试(报告测试基类):
    def test_亚秒调用不进慢清单(self):
        self.记("快能力", 62.0)
        self.记("更快能力", 0.3)
        报告 = self.审计.慢调用报告()
        self.assertEqual(0, 报告["慢调用条数"], "亚秒调用不得进慢清单")
        self.assertEqual([], 报告["按能力聚合"])
        self.assertEqual({"必须优化": 0, "考虑优化": 0}, 报告["分级计数"])

    def test_三秒以上记考虑优化(self):
        self.记("某能力", 3200.0)
        报告 = self.审计.慢调用报告()
        self.assertEqual(1, 报告["分级计数"]["考虑优化"])
        self.assertEqual(0, 报告["分级计数"]["必须优化"])

    def test_十秒以上记必须优化(self):
        self.记("某能力", 12000.0)
        报告 = self.审计.慢调用报告()
        self.assertEqual(1, 报告["分级计数"]["必须优化"])

    def test_边界值归入该级(self):
        # 口径：>= 阈值即归入该级
        self.记("恰好三秒", 3000.0)
        self.记("恰好十秒", 10000.0)
        报告 = self.审计.慢调用报告()
        self.assertEqual(1, 报告["分级计数"]["考虑优化"], "3000ms 应归「考虑优化」")
        self.assertEqual(1, 报告["分级计数"]["必须优化"], "10000ms 应归「必须优化」")

    def test_恰好低于阈值不算慢(self):
        self.记("差一点", 2999.0)
        self.assertEqual(0, self.审计.慢调用报告()["慢调用条数"])

    def test_阈值可调(self):
        self.记("某能力", 2000.0)
        self.assertEqual(0, self.审计.慢调用报告()["慢调用条数"],
                         "默认 3 秒阈值下，2 秒调用不算慢")
        收紧 = self.审计.慢调用报告(考虑优化秒=1.0)
        self.assertEqual(1, 收紧["慢调用条数"], "阈值降到 1 秒后，2 秒调用应算慢")
        self.assertEqual(1, 收紧["分级计数"]["考虑优化"])

    def test_必须优化阈值写小于考虑优化时自动抬高(self):
        self.记("某能力", 2500.0)
        报告 = self.审计.慢调用报告(考虑优化秒=3.0, 必须优化秒=1.0)
        self.assertGreaterEqual(报告["阈值秒"]["必须优化秒"], 报告["阈值秒"]["考虑优化秒"],
                                "必须优化阈值不得低于考虑优化阈值")


class 聚合测试(报告测试基类):
    def test_按能力聚合条数与最慢(self):
        self.记("慢能力", 4000.0)
        self.记("慢能力", 6000.0)
        self.记("更慢能力", 15000.0)
        报告 = self.审计.慢调用报告()
        聚合 = {项["能力id"]: 项 for 项 in 报告["按能力聚合"]}
        self.assertEqual(2, 聚合["慢能力"]["条数"])
        self.assertEqual(6000.0, 聚合["慢能力"]["最慢毫秒"])
        self.assertEqual(5000.0, 聚合["慢能力"]["平均毫秒"])
        self.assertEqual(1, 聚合["更慢能力"]["条数"])

    def test_聚合按最慢降序(self):
        self.记("较快", 3100.0)
        self.记("最慢", 20000.0)
        self.记("居中", 5000.0)
        聚合 = self.审计.慢调用报告()["按能力聚合"]
        self.assertEqual(["最慢", "居中", "较快"], [项["能力id"] for 项 in 聚合])

    def test_最慢明细降序(self):
        self.记("甲", 3100.0)
        self.记("乙", 20000.0)
        self.记("丙", 4000.0)
        明细 = self.审计.慢调用报告()["最慢明细"]
        self.assertEqual(["乙", "丙", "甲"], [项["能力id"] for 项 in 明细])

    def test_聚合标注必须优化等级(self):
        self.记("含必须优化", 3100.0)
        self.记("含必须优化", 11000.0)
        聚合 = {项["能力id"]: 项 for 项 in self.审计.慢调用报告()["按能力聚合"]}
        self.assertEqual("必须优化", 聚合["含必须优化"]["等级"])
        self.assertEqual(1, 聚合["含必须优化"]["必须优化条数"])

    def test_上限截断返回体量(self):
        for i in range(30):
            self.记(f"能力{i:02d}", 4000.0 + i)
        报告 = self.审计.慢调用报告(上限=5)
        self.assertEqual(5, len(报告["按能力聚合"]), "聚合必须按上限截断")
        self.assertEqual(5, len(报告["最慢明细"]), "明细必须按上限截断")
        self.assertEqual(30, 报告["慢调用条数"], "截断只影响返回条数，不影响计数")


class 健壮性测试(报告测试基类):
    def test_空账本不崩且全零(self):
        报告 = self.审计.慢调用报告()
        self.assertEqual(0, 报告["慢调用条数"])
        self.assertEqual(0, 报告["读取记录数"])
        self.assertEqual([], 报告["按能力聚合"])
        self.assertEqual([], 报告["最慢明细"])

    def test_耗时字段坏值不崩(self):
        self.记("正常能力", 4000.0)
        # 直接往账本里塞一条耗时非数值的记录（模拟旧格式/手工写入）
        账本文件 = self.账本目录 / "安全审计.jsonl"
        with 账本文件.open("a", encoding="utf-8") as 文件:
            文件.write('{"操作":"调用能力","能力id":"坏值能力","耗时毫秒":"不是数字"}\n')
        报告 = self.审计.慢调用报告()  # 不得抛异常
        self.assertEqual(1, 报告["慢调用条数"], "坏值按 0 处理，不得冒充慢调用")

    def test_说明指向唯一裁决能力不自己拍板(self):
        报告 = self.审计.慢调用报告()
        self.assertIn("判定耗时超标", 报告["说明"],
                      "报告只做分级，裁决必须指向唯一实现")

    def test_报告不落第二份文件(self):
        self.记("某能力", 4000.0)
        self.审计.慢调用报告()
        现存 = sorted(路径.name for 路径 in self.账本目录.iterdir())
        self.assertEqual(["安全审计.jsonl"], 现存,
                         "报告是只读派生：账本目录里除账本外不得多出任何文件")


class 反向验证测试(报告测试基类):
    """反向验证：报告必须**真的读账本**，而不是恒返回空壳。"""

    def test_报告读的是账本不是空壳(self):
        前 = self.审计.慢调用报告()
        self.assertEqual(0, 前["慢调用条数"])
        self.记("新出现的慢能力", 4500.0)
        后 = self.审计.慢调用报告()
        self.assertEqual(1, 后["慢调用条数"], "写入账本后报告必须跟着变")
        self.assertEqual("新出现的慢能力", 后["按能力聚合"][0]["能力id"])

    def test_账本里的失败调用也计入(self):
        self.记("失败但很慢", 9000.0, 成功=False)
        报告 = self.审计.慢调用报告()
        self.assertEqual(1, 报告["慢调用条数"], "慢与成功与否无关，失败调用同样计入")
        self.assertFalse(报告["最慢明细"][0]["成功"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
