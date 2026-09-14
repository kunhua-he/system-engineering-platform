"""版本兼容「清理」的引用计数安全门回归测试（真实状态库，非替身）。

背景（真实缺陷，2026-09-14 复核）：`版本兼容_回退.清理` 原文按
`包id = 旧快照id` 查引用计数，但引用计数表是按「资源id@版本」记账的
（权威状态.增加引用，来自读取句柄生命周期），而快照id 是随机 16 位 hex
（核心快照.py），两者永不相等 → 这条「引用未归零禁止删除快照」的安全门
**恒空**，引用未归零也会照删旧快照目录。

本测试锁死修复后的真实行为：
1) 存在活跃引用（计数>0）→ 清理被拒、旧快照目录必须还在、证据留痕；
2) 引用归零后有引用行残留（计数=0）→ 不阻塞清理；
3) 无任何引用记录 → 清理成功且旧快照目录真实删除；
4) 阶段不允许时仍按原语义拒绝（不因本次改动放宽）。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.核心快照 import 核心快照管理
from 平台控制面.平台状态 import 平台状态
from 平台控制面.提供者.版本兼容 import 版本兼容
from 平台控制面.发布管理 import 发布管理

迁移id = "测试迁移1"
迁移键 = f"版本迁移:{迁移id}"


class 测试_清理引用门(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.TemporaryDirectory(prefix="版本兼容清理门_")
        self.状态 = 平台状态(self.临时目录.name, 项目id="平台控制面")
        self.快照 = 核心快照管理(self.状态)
        self.版本兼容 = 版本兼容(self.状态, self.快照, 发布管理(self.状态))

    def tearDown(self):
        self.临时目录.cleanup()

    def _播种迁移(self, *, 阶段: str = "切换") -> dict:
        旧快照id = self.快照.创建快照(
            运行核心版本="1.0.0", 前端核心版本="1.0.0", 后端核心版本="1.0.0")
        迁移 = {"迁移id": 迁移id, "阶段": 阶段, "旧快照id": 旧快照id,
                "新快照id": "新快照1", "目标版本": "1.1.0",
                "状态兼容范围": "1.0.0-1.3.0"}
        self.状态.写入记录("元信息",
                       {"键": 迁移键, "值": json.dumps(迁移, ensure_ascii=False)}, "键")
        return 迁移

    def _旧快照目录(self, 迁移: dict) -> Path:
        return self.快照.快照根目录 / 迁移["旧快照id"]

    def test_有活跃引用时拒绝删除(self):
        迁移 = self._播种迁移()
        旧目录 = self._旧快照目录(迁移)
        self.assertTrue(旧目录.is_dir(), "前置：旧快照目录应真实存在")
        self.状态.增加引用(包id="资源甲", 版本="1")
        结果 = self.版本兼容.清理(迁移id=迁移id)
        self.assertFalse(结果["成功"], "引用未归零时清理必须被拒")
        self.assertTrue(结果.get("禁止删除"))
        self.assertIn("引用未归零禁止删除", 结果["错误"])
        self.assertTrue(结果.get("证据id"), "拒绝路径必须写证据留痕")
        self.assertTrue(旧目录.is_dir(), "被拒后旧快照目录必须原样保留")

    def test_引用归零后残留行不阻塞清理(self):
        迁移 = self._播种迁移()
        self.状态.增加引用(包id="资源甲", 版本="1")
        self.assertEqual(self.状态.减少引用(包id="资源甲", 版本="1"), 0)
        self.assertTrue(self.状态.查询记录("引用计数", "", ()),
                        "前置：计数=0 的引用行仍留在表里（权威状态不删行）")
        结果 = self.版本兼容.清理(迁移id=迁移id)
        self.assertTrue(结果["成功"], f"归零后应可清理: {结果}")
        self.assertFalse(self._旧快照目录(迁移).exists(), "清理后旧快照目录必须真实删除")
        self.assertEqual(结果["阶段"], "清理")

    def test_无引用记录时正常清理(self):
        迁移 = self._播种迁移()
        结果 = self.版本兼容.清理(迁移id=迁移id)
        self.assertTrue(结果["成功"], f"无引用应可清理: {结果}")
        self.assertTrue(结果["已删除旧快照"])

    def test_阶段不允许仍被拒(self):
        迁移 = self._播种迁移(阶段="开始")
        self.状态.增加引用(包id="资源甲", 版本="1")
        结果 = self.版本兼容.清理(迁移id=迁移id)
        self.assertFalse(结果["成功"])
        self.assertIn("阶段不允许", 结果["错误"])
        self.assertTrue(self._旧快照目录(迁移).is_dir())

    def test_迁移不存在(self):
        结果 = self.版本兼容.清理(迁移id="不存在的迁移")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误"], "迁移不存在")


if __name__ == "__main__":
    unittest.main()
