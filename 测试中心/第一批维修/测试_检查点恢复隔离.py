"""检查点恢复：受管库路径必须隔离，供唯一HTTP场景安全使用。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from 支持库.后端.系统核心支持库.检查点恢复 import 保存检查点, 恢复检查点


class 测试检查点恢复隔离(unittest.TestCase):
    def test_两个受管库完全隔离且恢复命中(self) -> None:
        with tempfile.TemporaryDirectory(prefix="检查点隔离_") as 临时:
            根 = Path(临时)
            库甲 = 根 / "甲" / "检查点.db"
            库乙 = 根 / "乙" / "检查点.db"
            保存 = 保存检查点("会话-1", {"阶段": 3}, "1.2.0", str(库甲))
            self.assertTrue(保存.成功, 保存.错误说明)
            保存值 = 保存.值
            self.assertIsInstance(保存值, dict)
            assert isinstance(保存值, dict)
            self.assertEqual(保存值["库路径"], str(库甲))
            self.assertTrue(库甲.is_file())
            甲 = 恢复检查点("会话-1", str(库甲))
            乙 = 恢复检查点("会话-1", str(库乙))
            self.assertTrue(甲.成功, 甲.错误说明)
            甲值 = 甲.值
            self.assertIsInstance(甲值, dict)
            assert isinstance(甲值, dict)
            self.assertEqual(甲值["状态快照"], {"阶段": 3})
            self.assertEqual(甲值["版本"], "1.2.0")
            self.assertTrue(甲值["已找到"])
            self.assertTrue(乙.成功, 乙.错误说明)
            乙值 = 乙.值
            self.assertIsInstance(乙值, dict)
            assert isinstance(乙值, dict)
            self.assertFalse(乙值["已找到"])
            self.assertFalse(库乙.exists())


if __name__ == "__main__":
    unittest.main()
