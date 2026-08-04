"""模块库.网页分析 组合能力真实测试。

覆盖：真实装配（注册网页解析支持库能力+注入唯一能力调用服务）下 提取网页信息
最小样本（标题+正文）；平台不可用（调用器未装配 → 提供者不可用）；参数错误
（网页内容非字符串 / 最大长度非整数 → 参数不合法）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest import mock

from 公共契约.基础类型.结果类型 import 结果
from 模块库.网页分析 import 提取网页信息

最小样本 = ("<html><head><title>平台示例标题</title></head>"
            "<body><h1>平台标题</h1><p>第一段正文。</p>"
            "<script>var 隐藏 = 1;</script><p>第二段正文。</p></body></html>")


class Test网页分析模块(unittest.TestCase):
    def setUp(self):
        """真实装配：注册网页解析支持库能力并经 全局唯一服务 注入能力调用器。"""
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
        from 支持库.后端.网页解析 import 注册能力 as 注册网页解析

        注册表 = 能力注册表()
        注册网页解析(注册表)
        设置全局唯一服务(唯一能力调用服务(注册表))
        self.addCleanup(self._卸载)

    @staticmethod
    def _卸载():
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        设置全局唯一服务(None)

    def test_提取网页信息最小样本(self):
        结果 = 提取网页信息(最小样本)
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 结果.值
        self.assertEqual(值["标题"], "平台示例标题")
        self.assertIn("第一段正文", 值["正文"])
        self.assertNotIn("var 隐藏", 值["正文"])  # script 已剔除

    def test_提取网页信息默认与显式最大长度(self):
        结果 = 提取网页信息(最小样本, 最大长度=50)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertLessEqual(len(结果.值["正文"]), 50)

    def test_网页内容非字符串参数不合法(self):
        for 非法内容 in (None, 123, ["<html>"], {"网页": "x"}):
            with self.subTest(内容=非法内容):
                结果 = 提取网页信息(非法内容)
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "参数不合法")

    def test_最大长度非整数参数不合法(self):
        for 非法长度 in ("100", None, 1.5):
            with self.subTest(长度=非法长度):
                结果 = 提取网页信息(最小样本, 最大长度=非法长度)
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "参数不合法")

    def test_平台不可用返回提供者不可用(self):
        """能力调用器未装配（模拟平台不可用）→ 提供者不可用，不抛异常。"""
        with mock.patch(
            "公共契约.能力契约.调用器.获取能力调用器",
            side_effect=RuntimeError("能力调用器未注入"),
        ):
            调用结果 = 提取网页信息(最小样本)
        self.assertFalse(调用结果.成功)
        self.assertEqual(调用结果.错误码, "提供者不可用")
        self.assertIsInstance(调用结果, 结果)

    def test_模块注册能力齐全(self):
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        from 模块库.网页分析 import 注册能力

        注册能力(注册表)
        self.assertEqual(len(注册表.条目), 1)
        self.assertEqual(注册表.条目[0].能力id, "网页分析.提取网页信息")
        self.assertEqual(注册表.条目[0].包id, "模块库.网页分析")


if __name__ == "__main__":
    unittest.main()
