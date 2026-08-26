"""支持库：五个后端原子支持库真实返回值测试。"""

from __future__ import annotations
from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import tempfile
import unittest
from pathlib import Path

from 支持库.后端.文件系统支持库.文件操作 import (
    复制文件, 判断存在, 读取文件, 删除文件, 获取大小, 列出目录, 移动文件, 写入文件,
)
from 支持库.后端.数据操作支持库.数据集合 import 列表查找, 列表排序, 字典获取
from 支持库.后端.数据操作支持库.数据交换 import 反序列化CSV, 反序列化JSON, 序列化CSV, 序列化JSON
from 支持库.后端.数据操作支持库.文本处理 import 按行分割, 查找文本, 去空白, 分割文本, 替换文本, 统计长度, 转大写
from 支持库.后端.数据操作支持库.时间日期 import 解析文本时间, 时间戳转换, 格式化为文本, 获取当前时间, 计算间隔


class Test文件系统(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.mkdtemp(prefix="测试_文件系统_")

    def test_写入读取往返(self):
        路径 = str(Path(self.临时目录) / "往返.txt")
        写入结果 = 写入文件(路径, "内容甲")
        self.assertTrue(写入结果.成功)
        读取结果 = 读取文件(路径)
        self.assertTrue(读取结果.成功)
        self.assertEqual(读取结果.值, "内容甲")

    def test_缺失文件返回失败(self):
        结果 = 读取文件("/不存在的路径/文件.txt")
        self.assertFalse(结果.成功)
        self.assertIsNotNone(结果.错误)
        self.assertEqual(结果.错误.错误码, "文件不存在")

    def test_复制与移动(self):
        源 = str(Path(self.临时目录) / "源.txt")
        复制目标 = str(Path(self.临时目录) / "复制.txt")
        移动目标 = str(Path(self.临时目录) / "移动.txt")
        写入文件(源, "x")
        self.assertTrue(复制文件(源, 复制目标).成功)
        self.assertTrue(判断存在(复制目标))
        self.assertTrue(移动文件(复制目标, 移动目标).成功)
        self.assertFalse(判断存在(复制目标))
        self.assertTrue(判断存在(移动目标))

    def test_删除幂等(self):
        路径 = str(Path(self.临时目录) / "删除.txt")
        写入文件(路径, "x")
        self.assertTrue(删除文件(路径).成功)
        self.assertTrue(删除文件(路径).成功)

    def test_大小与修改时间(self):
        路径 = str(Path(self.临时目录) / "大小.txt")
        写入文件(路径, "12345")
        大小结果 = 获取大小(路径)
        self.assertTrue(大小结果.成功)
        self.assertEqual(大小结果.值, 5)

    def test_列出目录(self):
        路径 = str(Path(self.临时目录) / "列.txt")
        写入文件(路径, "x")
        结果 = 列出目录(self.临时目录)
        self.assertTrue(结果.成功)
        self.assertIn("列.txt", 结果.值)


class Test文本处理(unittest.TestCase):
    def test_分割合并(self):
        结果 = 分割文本("甲,乙", ",")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, ["甲", "乙"])

    def test_替换(self):
        结果 = 替换文本("abcabc", "a", "X")
        self.assertEqual(结果.值, "XbcXbc")

    def test_查找(self):
        self.assertEqual(查找文本("abcdef", "cde").值, 2)
        self.assertEqual(查找文本("abcdef", "zzz").值, -1)

    def test_去空白大小写长度行分割(self):
        self.assertEqual(去空白("  甲  ").值, "甲")
        self.assertEqual(转大写("abc").值, "ABC")
        self.assertEqual(统计长度("系统级").值, 3)
        self.assertEqual(按行分割("a\nb").值, ["a", "b"])


class Test数据集合(unittest.TestCase):
    def test_列表操作(self):
        self.assertEqual(列表排序([3, 1, 2]).值, [1, 2, 3])
        self.assertEqual(列表排序([3, 1, 2], 倒序=True).值, [3, 2, 1])
        self.assertEqual(列表查找([10, 20], 20).值, 1)
        self.assertEqual(列表查找([10, 20], 99).值, -1)

    def test_字典获取默认值(self):
        结果 = 字典获取({"甲": 1}, "乙", 默认值=0)
        self.assertEqual(结果.值, 0)


class Test时间日期(unittest.TestCase):
    def test_当前时间与间隔(self):
        结果 = 获取当前时间()
        self.assertTrue(结果.成功)
        self.assertIn("T", 结果.值 or "")
        间隔 = 计算间隔(100.0, 105.0)
        self.assertAlmostEqual(间隔.值, 5.0)

    def test_格式化与解析往返(self):
        格式 = "%Y-%m-%d %H:%M:%S"
        解析 = 解析文本时间("2026-07-31 12:00:00", 格式)
        self.assertTrue(解析.成功)
        格式化 = 格式化为文本(解析.值, 格式)
        self.assertEqual(格式化.值, "2026-07-31 12:00:00")

    def test_时间戳转换结构(self):
        结构 = 时间戳转换(0).值
        self.assertEqual(结构["年"], 1970)


class Test数据交换(unittest.TestCase):
    def test_JSON往返(self):
        序列化 = 序列化JSON({"名称": "系统级", "数量": 2})
        self.assertTrue(序列化.成功)
        反序列化 = 反序列化JSON(序列化.值)
        self.assertEqual(反序列化.值, {"名称": "系统级", "数量": 2})

    def test_坏JSON失败(self):
        结果 = 反序列化JSON("{坏")
        self.assertFalse(结果.成功)

    def test_CSV往返(self):
        序列化 = 序列化CSV([["名称", "数量"], ["甲", 1]])
        反序列化 = 反序列化CSV(序列化.值)
        self.assertEqual(反序列化.值[0], ["名称", "数量"])
        self.assertEqual(反序列化.值[1], ["甲", "1"])


if __name__ == "__main__":
    unittest.main()
