"""模块库.文档读取 组合能力真实测试。

覆盖：真实网关装配（后端核心 + 本地网关服务器 + HTTP连接器）下 结构化读取/
读取正文/提取标题/计算段落数 最小样本；平台不可用（连接器未装配 →
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

from 公共契约.基础类型.结果类型 import 结果
from 模块库.文档读取 import 读取正文, 提取标题, 计算段落数, 结构化读取
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.能力调用.HTTP连接器 import HTTP连接器

样本内容 = "第一行标题\n\n第二行正文\n第三行正文\n"


class Test文档读取模块(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """启动真实后端和随机回环网关，所有测试请求走 HTTP。"""
        cls.后端 = 后端核心()
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 地址="127.0.0.1", 端口=0,
            配置={"请求超时秒": 1800, "要求凭证": False, "禁止客户端身份": False},
        )
        成功, 说明 = cls.网关.启动()
        if not 成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"网关启动失败: {说明}")
        from 模块库.文档读取 import 设置HTTP连接器
        设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=cls.网关.端口))

    @classmethod
    def tearDownClass(cls):
        from 模块库.文档读取 import 设置HTTP连接器
        设置HTTP连接器(None)
        cls.网关.优雅停止()
        cls.后端.优雅关闭()

    def setUp(self):
        """每个用例使用独立临时目录与样本文件。"""
        临时目录 = tempfile.mkdtemp(prefix="测试_文档读取_")
        self.addCleanup(shutil.rmtree, 临时目录, ignore_errors=True)
        self.样本路径 = Path(临时目录) / "样本.txt"
        self.样本路径.write_text(样本内容, encoding="utf-8")

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
        """卸载连接器后调用能力：模块返回 提供者不可用，不抛异常。"""
        from 模块库.文档读取 import 设置HTTP连接器
        设置HTTP连接器(None)
        try:
            调用结果 = 结构化读取(str(self.样本路径))
        finally:
            设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=self.网关.端口))
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
