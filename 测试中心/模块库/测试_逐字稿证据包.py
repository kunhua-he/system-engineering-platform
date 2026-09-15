"""模块库.直播逐字稿 实现.证据包 单元测试：纯字符串，不联网、不写盘。

覆盖：术语为空/非空、单区间多轮、多区间、死循环区间渲染、
时间段格式化（含超过 1 分钟）、底稿行按区间时间过滤、空输入不抛异常。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[2]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 模块库.直播逐字稿.实现.证据包 import 生成证据包, 格式化时间

底稿行 = [
    "[00:10.2-00:14.8] 这一段是疑难句",
    "[01:05.0-01:10.0] 另一处疑难句",
    "[12:05.0-12:09.0] 后面才出现的内容",
]


def 造轮次(数量: int, 前缀: str = "第") -> list[dict]:
    return [{"轮": 序号, "文本": f"{前缀}{序号}轮识别文本", "分段": []} for 序号 in range(1, 数量 + 1)]


class Test证据包结构(unittest.TestCase):
    def test_术语为空时写无(self):
        文本 = 生成证据包(底稿行, [], [], "")
        self.assertIn("# 逐段复核证据包", 文本)
        self.assertIn("## 已确认术语\n（无）", 文本)
        self.assertIn("## 死循环区间\n（无）", 文本)

    def test_术语非空逐条列出(self):
        文本 = 生成证据包([], [], [], "示例品牌、示例门店；示例平台")
        术语段 = 文本.split("## 已确认术语", 1)[1].split("## 死循环区间", 1)[0]
        self.assertIn("- 示例品牌", 术语段)
        self.assertIn("- 示例门店", 术语段)
        self.assertIn("- 示例平台", 术语段)
        self.assertNotIn("（无）", 术语段)
        self.assertNotIn("、", 术语段)

    def test_单区间多轮渲染(self):
        复核列表 = [{"区间id": 1, "开始秒": 10.2, "结束秒": 14.8, "轮次": 造轮次(3)}]
        文本 = 生成证据包(底稿行, 复核列表, [], "")
        self.assertIn("## 第1区间 00:10.2-00:14.8", 文本)
        self.assertIn("### 原始底稿", 文本)
        for 序号 in (1, 2, 3):
            self.assertIn(f"### 第{序号}轮识别", 文本)
            self.assertIn(f"第{序号}轮识别文本", 文本)

    def test_多区间各自渲染(self):
        复核列表 = [
            {"区间id": 1, "开始秒": 10.2, "结束秒": 14.8, "轮次": 造轮次(2, "A")},
            {"区间id": 2, "开始秒": 65.0, "结束秒": 70.0, "轮次": 造轮次(2, "B")},
        ]
        文本 = 生成证据包(底稿行, 复核列表, [], "")
        self.assertIn("## 第1区间 00:10.2-00:14.8", 文本)
        self.assertIn("## 第2区间 01:05.0-01:10.0", 文本)
        标题行 = [行 for 行 in 文本.splitlines() if 行.startswith("## 第")]
        self.assertEqual(len(标题行), 2)
        self.assertIn("A1轮识别文本", 文本)
        self.assertIn("B1轮识别文本", 文本)
        self.assertLess(文本.index("## 第1区间"), 文本.index("## 第2区间"))

    def test_死循环区间渲染(self):
        死循环 = [{"开始秒": 600.0, "结束秒": 900.0, "重复次数": 18, "样例文本": "示例文本"}]
        文本 = 生成证据包([], [], 死循环, "")
        段 = 文本.split("## 死循环区间", 1)[1]
        self.assertIn("- 10:00.0-15:00.0 重复 18 次 样例：示例文本", 段)

    def test_底稿行按区间时间过滤(self):
        复核列表 = [{"区间id": 1, "开始秒": 10.2, "结束秒": 14.8, "轮次": 造轮次(1)}]
        文本 = 生成证据包(底稿行, 复核列表, [], "")
        原始底稿段 = 文本.split("### 原始底稿", 1)[1].split("### 第1轮识别", 1)[0]
        self.assertIn("这一段是疑难句", 原始底稿段)
        self.assertNotIn("另一处疑难句", 原始底稿段)
        self.assertNotIn("后面才出现的内容", 原始底稿段)

    def test_无时间戳底稿行整批保留(self):
        复核列表 = [{"区间id": 1, "开始秒": 0.0, "结束秒": 1.0, "轮次": 造轮次(1)}]
        文本 = 生成证据包(["没有时间戳的一行"], 复核列表, [], "")
        self.assertIn("- 没有时间戳的一行", 文本)

    def test_空输入不抛异常(self):
        文本 = 生成证据包([], [], [], "")
        self.assertTrue(文本.startswith("# 逐段复核证据包\n"))
        无轮次文本 = 生成证据包([], [{"区间id": 1, "开始秒": 0, "结束秒": 1}], [], "")
        self.assertIn("### 识别轮次\n（无）", 无轮次文本)


class Test时间格式(unittest.TestCase):
    def test_时间段格式化不超过一分钟(self):
        self.assertEqual(格式化时间(0), "00:00.0")
        self.assertEqual(格式化时间(10.2), "00:10.2")
        self.assertEqual(格式化时间(59.9), "00:59.9")
        self.assertEqual(格式化时间(59.96), "01:00.0")

    def test_时间段格式化超过一分钟(self):
        self.assertEqual(格式化时间(65.0), "01:05.0")
        self.assertEqual(格式化时间(725.0), "12:05.0")
        self.assertEqual(格式化时间(3600.0), "60:00.0")
        self.assertEqual(格式化时间(-3), "00:00.0")
        self.assertEqual(格式化时间("坏值"), "00:00.0")

    def test_区间标题里的时间也走统一格式(self):
        复核列表 = [{"区间id": 7, "开始秒": 725.0, "结束秒": 800.5, "轮次": 造轮次(1)}]
        文本 = 生成证据包([], 复核列表, [], "")
        self.assertIn("## 第7区间 12:05.0-13:20.5", 文本)


if __name__ == "__main__":
    unittest.main()
