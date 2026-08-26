"""模块库.文档读取 组合能力真实测试。

覆盖：真实装配（注册支持库能力+注入唯一能力调用服务）下 结构化读取/
读取正文/提取标题/计算段落数 最小样本；平台不可用（调用器未装配 →
提供者不可用）；参数错误（文件路径非文本 → 参数不合法）；文件不存在透传。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest import mock

from 公共契约.基础类型.结果类型 import 结果
from 模块库.文档读取 import 读取正文, 提取标题, 计算段落数, 结构化读取

样本内容 = "第一行标题\n\n第二行正文\n第三行正文\n"


class Test文档读取模块(unittest.TestCase):
    def setUp(self):
        """真实装配：注册支持库能力并经 全局唯一服务 注入能力调用器。"""
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
        from 支持库.后端.文件系统支持库.文件操作 import 注册能力 as 注册文件系统
        from 支持库.后端.数据操作支持库.文本处理 import 注册能力 as 注册文本处理
        from 支持库.后端.数据操作支持库.数据交换 import 注册能力 as 注册数据交换

        注册表 = 能力注册表()
        注册文件系统(注册表)
        注册文本处理(注册表)
        注册数据交换(注册表)
        设置全局唯一服务(唯一能力调用服务(注册表))
        self.addCleanup(self._卸载)
        临时目录 = tempfile.mkdtemp(prefix="测试_文档读取_")
        self.addCleanup(shutil.rmtree, 临时目录, ignore_errors=True)
        self.样本路径 = Path(临时目录) / "样本.txt"
        self.样本路径.write_text(样本内容, encoding="utf-8")

    @staticmethod
    def _卸载():
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        设置全局唯一服务(None)

    def test_结构化读取最小样本(self):
        结果 = 结构化读取(str(self.样本路径))
        self.assertTrue(结果.成功, 结果.错误说明)
        结构 = 结果.值
        self.assertEqual(结构["正文"], 样本内容)
        self.assertEqual(结构["标题"], "第一行标题")
        self.assertEqual(结构["段落数"], 3)
        self.assertIsNone(结构["错误"])
        self.assertIn("第一行标题", 结构["序列化文本"])
        self.assertIn("第二行正文", 结构["序列化文本"])

    def test_读取正文真实调用(self):
        结果 = 读取正文(str(self.样本路径))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, 样本内容)

    def test_提取标题真实调用(self):
        结果 = 提取标题(str(self.样本路径))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, "第一行标题")

    def test_计算段落数真实调用(self):
        结果 = 计算段落数(str(self.样本路径))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, 3)

    def test_文件不存在透传支持库错误(self):
        结果 = 读取正文("/不存在/目录/文件.txt")
        self.assertFalse(结果.成功)
        self.assertTrue(结果.错误码, "支持库错误码不应为空")

    def test_文件路径非法参数不合法(self):
        for 非法路径 in (None, "", "   ", 123):
            with self.subTest(路径=非法路径):
                结果 = 读取正文(非法路径)
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "参数不合法")

    def test_结构化读取文件路径非法参数不合法(self):
        结果 = 结构化读取(None)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_平台不可用返回提供者不可用(self):
        """能力调用器未装配（模拟平台不可用）→ 提供者不可用，不抛异常。"""
        with mock.patch(
            "公共契约.能力契约.调用器.获取能力调用器",
            side_effect=RuntimeError("能力调用器未注入"),
        ):
            调用结果 = 结构化读取(str(self.样本路径))
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
        from 模块库.文档读取 import 注册能力

        注册能力(注册表)
        能力id表 = {条目.能力id for 条目 in 注册表.条目}
        self.assertEqual(能力id表, {
            "文档读取.读取正文",
            "文档读取.提取标题",
            "文档读取.计算段落数",
            "文档读取.结构化读取",
        })
        for 条目 in 注册表.条目:
            self.assertEqual(条目.包id, "模块库.文档读取")


if __name__ == "__main__":
    unittest.main()
