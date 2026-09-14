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
            库1 = 根 / "库1" / "检查点.db"
            库2 = 根 / "库2" / "检查点.db"
            保存 = 保存检查点("会话-1", {"阶段": 3}, "1.2.0", str(库1))
            self.assertTrue(保存.成功, 保存.错误说明)
            保存值 = 保存.值
            self.assertIsInstance(保存值, dict)
            assert isinstance(保存值, dict)
            self.assertEqual(保存值["库路径"], str(库1))
            self.assertTrue(库1.is_file())
            结果1 = 恢复检查点("会话-1", str(库1))
            结果2 = 恢复检查点("会话-1", str(库2))
            self.assertTrue(结果1.成功, 结果1.错误说明)
            值1 = 结果1.值
            self.assertIsInstance(值1, dict)
            assert isinstance(值1, dict)
            self.assertEqual(值1["状态快照"], {"阶段": 3})
            self.assertEqual(值1["版本"], "1.2.0")
            self.assertTrue(值1["已找到"])
            self.assertTrue(结果2.成功, 结果2.错误说明)
            值2 = 结果2.值
            self.assertIsInstance(值2, dict)
            assert isinstance(值2, dict)
            self.assertFalse(值2["已找到"])
            self.assertFalse(库2.exists())


if __name__ == "__main__":
    unittest.main()
