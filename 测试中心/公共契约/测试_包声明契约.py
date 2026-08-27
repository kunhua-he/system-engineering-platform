"""公共契约：包声明解析与校验测试。"""

from __future__ import annotations
from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import unittest
from pathlib import Path

from 公共契约.包声明.声明 import 从字典构建, 加载声明文件, 校验版本


class Test包声明契约(unittest.TestCase):
    def test_合法声明可构建(self):
        声明 = 从字典构建({"包id": "支持库.测试", "名称": "测试", "类型": "支持库", "版本": "1.2.3", "能力": []})
        self.assertEqual(声明.包id, "支持库.测试")
        self.assertEqual(声明.版本, "1.2.3")

    def test_缺失必填字段拒绝(self):
        with self.assertRaises(ValueError):
            从字典构建({"包id": "支持库.测试", "名称": "测试", "类型": "支持库", "版本": "1.0.0"})

    def test_非法类型拒绝(self):
        with self.assertRaises(ValueError):
            从字典构建({"包id": "x", "名称": "x", "类型": "业务", "版本": "1.0.0"})

    def test_非法版本拒绝(self):
        with self.assertRaises(ValueError):
            校验版本("v1")
        with self.assertRaises(ValueError):
            校验版本("1.2")

    def test_能力声明解析(self):
        声明 = 从字典构建({
            "包id": "x", "名称": "x", "类型": "模块", "版本": "1.0.0",
            "能力": [{"能力id": "x.能力", "名称": "能力", "参数": [{"名称": "甲", "类型": "文本"}], "返回": "结果"}],
        })
        self.assertEqual(len(声明.能力), 1)
        self.assertEqual(声明.能力[0].能力id, "x.能力")

    def test_加载声明文件(self):
        样例 = Path(__file__).resolve().parents[2] / "支持库/后端/文件系统支持库/包声明.json"
        声明 = 加载声明文件(样例)
        self.assertEqual(声明.包id, "支持库.后端.文件系统支持库")
        self.assertGreaterEqual(len(声明.能力), 9)


if __name__ == "__main__":
    unittest.main()
