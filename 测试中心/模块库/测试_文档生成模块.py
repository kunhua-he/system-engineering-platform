"""模块库.文档生成 组合能力真实测试。

覆盖：四格式组合生成（返回统一 生成产物：字节/媒体类型/摘要/诊断）、
格式归一化、非法格式与不可生成格式（参数不合法）、缺库降级
（monkeypatch → 提供者不可用）、生成字节为空（生成失败）。
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest import mock

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.基础类型.文档结构 import 生成产物
from 模块库.文档生成 import 生成文档

四格式参数表 = [
    ("docx", {"内容块列表": [{"类型": "标题", "文本": "模块标题"}, {"类型": "段落", "文本": "模块中文正文"}]}),
    ("xlsx", {"工作表列表": [{"表名": "模块表", "列": ["姓名", "数量"], "行": [["王五", 7]]}]}),
    ("pptx", {"幻灯片列表": [{"标题": "模块演示", "要点": ["模块要点"]}]}),
    ("pdf", {"段落列表": ["模块PDF正文"], "标题": "模块PDF标题"}),
]


class Test生成文档(unittest.TestCase):
    def setUp(self):
        """真实装配：注册提供者能力并经 装配系统 注入唯一能力调用服务。"""
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务

        注册表 = 能力注册表()
        from 支持库.适配层.python_docx提供者 import 注册能力 as 注册docx
        from 支持库.适配层.openpyxl提供者 import 注册能力 as 注册xlsx
        from 支持库.适配层.python_pptx提供者 import 注册能力 as 注册pptx
        from 支持库.适配层.reportlab提供者 import 注册能力 as 注册pdf

        注册docx(注册表)
        注册xlsx(注册表)
        注册pptx(注册表)
        注册pdf(注册表)
        设置全局唯一服务(唯一能力调用服务(注册表))

    def tearDown(self):
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        设置全局唯一服务(None)

    def test_四格式组合生成返回统一产物(self):
        for 格式, 内容参数 in 四格式参数表:
            with self.subTest(格式=格式):
                结果 = 生成文档(格式, 内容参数)
                self.assertTrue(结果.成功, 结果.错误说明)
                产物 = 结果.值
                self.assertIsInstance(产物, 生成产物)
                self.assertEqual(产物.格式, 格式)
                self.assertTrue(产物.字节, f"{格式} 字节为空")
                self.assertTrue(产物.媒体类型, f"{格式} 媒体类型为空")
                self.assertEqual(产物.摘要, hashlib.sha256(产物.字节).hexdigest())
                # 诊断由提供者决定，可为空；媒体类型/摘要必须齐全

    def test_格式大小写与点前缀归一化(self):
        for 格式 in (".DOCX", "XLSX", "Pptx", ".pdf"):
            with self.subTest(格式=格式):
                小写 = 格式.lower()
                if 小写.endswith("docx"):
                    参数 = {"内容块列表": [{"类型": "段落", "文本": "x"}]}
                elif 小写.endswith("xlsx"):
                    参数 = {"工作表列表": [{"表名": "表", "行": [["x"]]}]}
                elif 小写.endswith("pptx"):
                    参数 = {"幻灯片列表": [{"标题": "标题"}]}
                else:
                    参数 = {"段落列表": ["x"]}
                结果 = 生成文档(格式, 参数)
                self.assertTrue(结果.成功, 结果.错误说明)

    def test_非法格式参数不合法(self):
        for 格式 in ("txt", "html", "", None):
            with self.subTest(格式=格式):
                结果 = 生成文档(格式, {})
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "参数不合法")

    def test_不可生成格式参数不合法(self):
        # doc/xls/ppt 是合法格式但不属于生成范围
        for 格式 in ("doc", "xls", "ppt"):
            with self.subTest(格式=格式):
                结果 = 生成文档(格式, {})
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "参数不合法")

    def test_内容参数非字典参数不合法(self):
        结果 = 生成文档("docx", "不是字典")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_缺库提供者不可用(self):
        # 依赖注入：环境变量禁用 python-docx → docx 生成返回 提供者不可用
        from 支持库.适配层.python_docx提供者.实现 import 文字文档 as docx实现
        原缓存 = getattr(docx实现, "_提供者缓存", None)
        docx实现._提供者缓存 = None
        try:
            with mock.patch.dict("os.environ", {"python_docx提供者_禁用库": "docx"}):
                结果 = 生成文档("docx", {"内容块列表": [{"类型": "段落", "文本": "x"}]})
        finally:
            docx实现._提供者缓存 = 原缓存
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")

    def test_支持库生成失败透传(self):
        from 模块库.文档生成.实现 import 文档生成 as 模块实现
        with mock.patch(
            "模块库.文档生成.实现.文档生成.生成函数表",
            {"docx": lambda 内容: (_ for _ in ()).throw(RuntimeError("模拟生成器崩溃"))},
        ):
            结果 = 生成文档("docx", {"内容块列表": [{"类型": "段落", "文本": "x"}]})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "生成失败")

    def test_字节为空生成失败(self):
        空结果 = 结果.成功结果({})
        with mock.patch(
            "模块库.文档生成.实现.文档生成.生成函数表",
            {"docx": lambda 内容: 空结果},
        ):
            生成结果 = 生成文档("docx", {"内容块列表": [{"类型": "段落", "文本": "x"}]})
        self.assertFalse(生成结果.成功)
        self.assertEqual(生成结果.错误码, "生成失败")
        self.assertIn("生成产物为空", 生成结果.错误说明)

    def test_模块注册能力(self):
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        from 模块库.文档生成 import 注册能力

        注册能力(注册表)
        self.assertEqual(len(注册表.条目), 1)
        self.assertEqual(注册表.条目[0].能力id, "文档生成.生成文档")
        self.assertEqual(注册表.条目[0].包id, "模块库.文档生成")


if __name__ == "__main__":
    unittest.main()
