"""模块库：三个样板模块只经支持库公开入口运行的真实测试。"""

from __future__ import annotations
from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import tempfile
import unittest
from pathlib import Path

from 模块库.文件管理 import 复制文件, 读取文件, 删除文件, 写入文件
from 模块库.文档读取 import 计算段落数, 结构化读取, 提取标题, 读取正文
from 模块库.简单窗口 import 打开窗口, 关闭窗口, 创建窗口, 传递参数, 获取窗口描述


class Test文件管理模块(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.mkdtemp(prefix="测试_文件管理_")

    def test_写入读取复制删除(self):
        源 = str(Path(self.临时目录) / "源.txt")
        目标 = str(Path(self.临时目录) / "目标.txt")
        self.assertTrue(写入文件(源, "模块内容").成功)
        读取结果 = 读取文件(源)
        self.assertTrue(读取结果.成功)
        self.assertEqual(读取结果.值, "模块内容")
        self.assertTrue(复制文件(源, 目标).成功)
        self.assertEqual(读取文件(目标).值, "模块内容")
        self.assertTrue(删除文件(源).成功)


class Test文档读取模块(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.mkdtemp(prefix="测试_文档读取_")
        self.路径 = str(Path(self.临时目录) / "文档.txt")
        写入文件(self.路径, "产品标题\n第一段内容。\n第二段内容。")

    def test_读取正文(self):
        结果 = 读取正文(self.路径)
        self.assertTrue(结果.成功)
        self.assertIn("第一段内容", 结果.值)

    def test_提取标题(self):
        结果 = 提取标题(self.路径)
        self.assertEqual(结果.值, "产品标题")

    def test_计算段落数(self):
        结果 = 计算段落数(self.路径)
        self.assertEqual(结果.值, 3)

    def test_结构化读取含序列化(self):
        结果 = 结构化读取(self.路径)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["标题"], "产品标题")
        self.assertEqual(结果.值["段落数"], 3)
        self.assertIn("产品标题", 结果.值["序列化文本"])

    def test_缺失文件返回统一错误结构(self):
        结果 = 结构化读取("/不存在的路径/文档.txt")
        self.assertFalse(结果.成功)
        self.assertIsNotNone(结果.错误)
        self.assertEqual(结果.错误.错误码, "文件不存在")


class Test简单窗口模块(unittest.TestCase):
    def test_创建打开关闭全流程(self):
        创建结果 = 创建窗口("测试窗", "测试", 400, 300)
        self.assertTrue(创建结果.成功)
        打开结果 = 打开窗口("测试窗")
        self.assertTrue(打开结果.成功)
        self.assertEqual(打开结果.值["状态"], "打开")
        参数结果 = 传递参数("测试窗", {"来源": "测试"})
        self.assertEqual(参数结果.值["参数"]["来源"], "测试")
        描述结果 = 获取窗口描述("测试窗")
        self.assertEqual(描述结果.值["标题"], "测试")
        self.assertEqual(描述结果.值["状态"], "打开")
        关闭结果 = 关闭窗口("测试窗")
        self.assertTrue(关闭结果.成功)
        self.assertEqual(关闭结果.值["状态"], "关闭")

    def test_窗口不存在失败(self):
        结果 = 获取窗口描述("不存在的窗")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误.错误码, "窗口不存在")

    def test_非法状态流转失败(self):
        创建窗口("状态窗", "状态", 100, 100)
        结果 = 关闭窗口("状态窗")
        self.assertFalse(结果.成功)


if __name__ == "__main__":
    unittest.main()
