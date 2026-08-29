"""网页解析支持库与网页分析模块测试（unittest，标准库）。

覆盖：标题提取/正文提取/script 剔除/空白归一化/截断/非法输入/模块组合。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.网络通信支持库.网页解析 import 提取网页标题, 提取网页正文
系统根 = Path(__file__).resolve().parents[2]
from 模块库.网页分析 import 提取网页信息


class Test提取网页标题(unittest.TestCase):
    """网页标题提取。"""

    def test_提取标题(self):
        结果 = 提取网页标题("<html><head><title>测试标题</title></head><body>正文</body></html>")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, "测试标题")

    def test_无标题返回空(self):
        结果 = 提取网页标题("<html><body>没有标题</body></html>")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, "")

    def test_标题带空白去除首尾(self):
        结果 = 提取网页标题("<html><head><title>  两边空白  </title></head></html>")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, "两边空白")

    def test_标题内嵌实体解码(self):
        结果 = 提取网页标题("<html><head><title>a&amp;b &lt;c&gt;</title></head></html>")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, "a&b <c>")

    def test_非字符串参数不合法(self):
        结果 = 提取网页标题(123)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


class Test提取网页正文(unittest.TestCase):
    """网页正文提取。"""

    def test_提取正文(self):
        结果 = 提取网页正文("<html><body><p>第一段</p><p>第二段</p></body></html>")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, "第一段 第二段")

    def test_剔除script与style内容(self):
        内容 = ("<html><body>正文<p>可见</p>"
                "<script>var x = 1;</script>"
                "<style>.hidden{display:none}</style>"
                "尾部</body></html>")
        结果 = 提取网页正文(内容)
        self.assertTrue(结果.成功)
        self.assertNotIn("var x", 结果.值)
        self.assertNotIn("hidden", 结果.值)
        self.assertIn("可见", 结果.值)
        self.assertIn("尾部", 结果.值)

    def test_空白归一化(self):
        结果 = 提取网页正文("<html><body>a\n\n\t  b</body></html>")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, "a b")

    def test_截断到最大长度(self):
        正文 = "汉" * 100
        结果 = 提取网页正文(f"<html><body>{正文}</body></html>", 最大长度=10)
        self.assertTrue(结果.成功)
        self.assertEqual(len(结果.值), 10)
        self.assertEqual(结果.值, "汉" * 10)

    def test_默认最大长度20000(self):
        正文 = "长" * 30000
        结果 = 提取网页正文(f"<html><body>{正文}</body></html>")
        self.assertTrue(结果.成功)
        self.assertEqual(len(结果.值), 20000)

    def test_非字符串参数不合法(self):
        结果 = 提取网页正文(None)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_非法最大长度参数不合法(self):
        结果 = 提取网页正文("<html><body>x</body></html>", 最大长度=-1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        结果2 = 提取网页正文("<html><body>x</body></html>", 最大长度="10")
        self.assertFalse(结果2.成功)
        self.assertEqual(结果2.错误码, "参数不合法")


class Test提取网页信息(unittest.TestCase):
    """网页分析模块组合能力（模块经能力调用器，需装配）。"""

    def setUp(self) -> None:
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.加载器.包安装.支持库安装 import 安装全部支持库
        from 运行核心.加载器.包安装.模块安装 import 安装全部模块
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定
        self._装配注册表 = 能力注册表()
        安装全部支持库(系统根 / "支持库", self._装配注册表)
        # 模块能力同样需要装配并注入连接器（统一口径），否则
        # 网页分析.提取网页信息 无法经唯一能力调用服务路由到底层。
        安装全部模块(系统根 / "模块库", self._装配注册表)
        创建并绑定(self._装配注册表)

    def test_组合提取标题与正文(self):
        结果 = 提取网页信息("<html><head><title>标题A</title></head><body>正文A</body></html>")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["标题"], "标题A")
        self.assertEqual(结果.值["正文"], "正文A")

    def test_组合截断(self):
        结果 = 提取网页信息("<html><body>" + "字" * 50 + "</body></html>", 最大长度=5)
        self.assertTrue(结果.成功)
        self.assertEqual(len(结果.值["正文"]), 5)

    def test_非字符串参数不合法(self):
        结果 = 提取网页信息(123)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main()
