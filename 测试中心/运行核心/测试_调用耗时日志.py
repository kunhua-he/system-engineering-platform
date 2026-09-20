"""调用耗时日志定向测试：只记录、不裁决；热路径零开销；有界。

华哥 2026-09-21 裁决「html 需要加上一个调用时间的日志，超过 10 秒的需要优化，
超过 3 秒的可以考虑优化」。本文件锁住三条不变式：
  ① **未达阈值不落任何痕迹**（亚秒级调用零开销，否则热路径被日志拖死）；
  ② 达阈值必留痕且分级正确；
  ③ 有界（内存环形 + 文件行数上限），不无界增长。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.统一网关.运行态 import 调用耗时日志 as 日志


class 阈值测试(unittest.TestCase):
    def test_默认阈值是华哥口径(self):
        考虑秒, 必须秒 = 日志.阈值秒()
        self.assertEqual(3.0, 考虑秒)
        self.assertEqual(10.0, 必须秒)

    def test_环境变量可覆盖(self):
        原 = os.environ.get(日志.环境变量_考虑优化秒)
        os.environ[日志.环境变量_考虑优化秒] = "1.5"
        try:
            self.assertEqual(1.5, 日志.阈值秒()[0])
        finally:
            if 原 is None:
                os.environ.pop(日志.环境变量_考虑优化秒, None)
            else:
                os.environ[日志.环境变量_考虑优化秒] = 原

    def test_阈值写反时自动纠正(self):
        原1 = os.environ.get(日志.环境变量_考虑优化秒)
        原2 = os.environ.get(日志.环境变量_必须优化秒)
        os.environ[日志.环境变量_考虑优化秒] = "20"
        os.environ[日志.环境变量_必须优化秒] = "5"
        try:
            考虑秒, 必须秒 = 日志.阈值秒()
            self.assertGreaterEqual(必须秒, 考虑秒, "必须优化阈值不得低于考虑优化阈值")
        finally:
            for 键, 原 in ((日志.环境变量_考虑优化秒, 原1), (日志.环境变量_必须优化秒, 原2)):
                if 原 is None:
                    os.environ.pop(键, None)
                else:
                    os.environ[键] = 原


class 记录测试(unittest.TestCase):
    def setUp(self):
        self.临时 = tempfile.TemporaryDirectory()
        self.路径 = Path(self.临时.name) / "耗时.jsonl"
        self.账 = 日志.调用耗时日志(self.路径)

    def tearDown(self):
        self.临时.cleanup()

    def test_亚秒调用零开销不落痕(self):
        结果 = self.账.记录(能力id="某能力", 耗时毫秒=62.0)
        self.assertIsNone(结果, "未达阈值必须返回 None（热路径零开销）")
        self.assertFalse(self.路径.exists(), "未达阈值不得创建日志文件")
        self.assertEqual([], self.账.快照())

    def test_三秒记考虑优化(self):
        结果 = self.账.记录(能力id="某能力", 耗时毫秒=3200.0)
        self.assertIsNotNone(结果)
        self.assertEqual("考虑优化", 结果["等级"])

    def test_十秒记必须优化(self):
        结果 = self.账.记录(能力id="某能力", 耗时毫秒=12000.0)
        self.assertEqual("必须优化", 结果["等级"])

    def test_边界值归属(self):
        # 恰好等于阈值 → 归入该级（口径：>= 阈值）
        self.assertEqual("考虑优化", self.账.记录(能力id="x", 耗时毫秒=3000.0)["等级"])
        self.assertEqual("必须优化", self.账.记录(能力id="x", 耗时毫秒=10000.0)["等级"])

    def test_落盘可读且是JSONL(self):
        self.账.记录(能力id="慢能力", 操作="调用能力", 耗时毫秒=4000.0)
        行表 = [行 for 行 in self.路径.read_text(encoding="utf-8").splitlines() if 行.strip()]
        self.assertEqual(1, len(行表))
        条目 = json.loads(行表[0])
        self.assertEqual("慢能力", 条目["能力id"])
        self.assertEqual("考虑优化", 条目["等级"])

    def test_快照按最慢优先(self):
        self.账.记录(能力id="中", 耗时毫秒=4000.0)
        self.账.记录(能力id="最慢", 耗时毫秒=15000.0)
        self.账.记录(能力id="较快", 耗时毫秒=3100.0)
        快照 = self.账.快照()
        self.assertEqual(["最慢", "中", "较快"], [项["能力id"] for 项 in 快照])

    def test_汇总分级计数(self):
        self.账.记录(能力id="a", 耗时毫秒=4000.0)
        self.账.记录(能力id="b", 耗时毫秒=4000.0)
        self.账.记录(能力id="c", 耗时毫秒=11000.0)
        汇总 = self.账.汇总()
        self.assertEqual(2, 汇总["分级计数"]["考虑优化"])
        self.assertEqual(1, 汇总["分级计数"]["必须优化"])
        self.assertIn("判定耗时超标", 汇总["说明"], "汇总须指向唯一裁决能力，不自己拍板")

    def test_内存有界(self):
        原 = 日志.内存上限
        日志.内存上限 = 5
        try:
            for i in range(20):
                self.账.记录(能力id=f"c{i}", 耗时毫秒=4000.0)
            self.assertLessEqual(len(self.账.快照(上限=999)), 5, "内存环形必须有界")
        finally:
            日志.内存上限 = 原

    def test_文件行数有界(self):
        原内存, 原文件 = 日志.内存上限, 日志.文件行数上限
        日志.内存上限, 日志.文件行数上限 = 1000, 10
        try:
            for i in range(30):
                self.账.记录(能力id=f"c{i}", 耗时毫秒=4000.0)
            行数 = len([行 for 行 in self.路径.read_text(encoding="utf-8").splitlines() if 行.strip()])
            self.assertLessEqual(行数, 10, "文件行数必须有界（留新弃旧）")
        finally:
            日志.内存上限, 日志.文件行数上限 = 原内存, 原文件

    def test_写盘失败不抛异常(self):
        # 路径指向一个不可写的位置（用文件当父目录，mkdir 必失败）
        拦路 = Path(self.临时.name) / "这是个文件"
        拦路.write_text("x", encoding="utf-8")
        账 = 日志.调用耗时日志(拦路 / "子目录" / "耗时.jsonl")
        结果 = 账.记录(能力id="x", 耗时毫秒=4000.0)  # 不得抛异常
        self.assertIsNotNone(结果, "写盘失败也要在内存留痕，且不得把调用搞失败")


class 未装配测试(unittest.TestCase):
    def test_未装配时记录耗时是空操作(self):
        原 = 日志.取实例()
        try:
            日志._实例 = None
            self.assertIsNone(日志.记录耗时(能力id="x", 耗时毫秒=99999.0))
        finally:
            日志._实例 = 原


if __name__ == "__main__":
    unittest.main(verbosity=1)
