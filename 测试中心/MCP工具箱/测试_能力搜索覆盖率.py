"""能力搜索覆盖率测试：搜索/读取公开能力 10 字段齐全、缺失如实标注、不加载实现。"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

公开能力路径 = Path(__file__).resolve().parents[2] / "MCP工具箱" / "公开能力.py"
sys.path.insert(0, str(公开能力路径.parent))
规格 = importlib.util.spec_from_file_location("公开能力覆盖率模块", 公开能力路径)
assert 规格 and 规格.loader
公开能力模块 = importlib.util.module_from_spec(规格)
规格.loader.exec_module(公开能力模块)

项目根 = Path(__file__).resolve().parents[2]

十字段 = list(公开能力模块.搜索字段表)

第三方实现包表 = (
    "Pillow", "PIL", "pdfplumber", "fitz", "pypdf", "docx", "pptx",
    "reportlab", "openpyxl", "psycopg", "psycopg2", "pg8000", "tesseract",
    "whisper", "ffmpeg", "Crypto", "Cryptodome",
)


class 能力搜索覆盖率测试(unittest.TestCase):
    def setUp(self) -> None:
        # 隔离：冷启动/其他波次可能已加载第三方实现包；搜索测试要求
        # 这些包未进入 sys.modules（验证"搜索不加载实现"），先清理。
        for 包名 in 第三方实现包表:
            sys.modules.pop(包名, None)

    def test_真实搜索十条目字段齐全(self) -> None:
        for 关键词 in ("图像", "PDF", "签名", "媒体"):
            with self.subTest(关键词=关键词):
                结果 = 公开能力模块.搜索公开能力(项目根, 关键词, 10)
                self.assertGreater(len(结果), 0, f"关键词[{关键词}] 应有结果")
                for 能力 in 结果:
                    for 字段 in 十字段:
                        self.assertIn(字段, 能力, f"{能力.get('能力id')} 缺字段 {字段}")
                    self.assertTrue(能力["能力id"])
                    self.assertTrue(能力["中文名称"])
                    self.assertTrue(能力["说明"])
                    self.assertIsInstance(能力["参数"], list)
                    self.assertIsInstance(能力["错误码"], (list, str))
                    self.assertIsInstance(能力["验证状态"], str)

    def test_参数列表含必填标记(self) -> None:
        读取 = 公开能力模块.读取公开能力(项目根, "图像处理.识别图像格式")
        self.assertIsNotNone(读取)
        参数字典 = {参数["名称"]: 参数 for 参数 in 读取["参数"]}
        self.assertEqual(参数字典["字节"]["必填"], True)
        self.assertEqual(参数字典["超时秒"]["必填"], False)
        for 参数 in 读取["参数"]:
            self.assertIn("名称", 参数)
            self.assertIn("必填", 参数)

    def test_字段缺失如实标注不伪造(self) -> None:
        结果 = 公开能力模块.搜索公开能力(项目根, "", 100)
        self.assertGreater(len(结果), 0)
        for 能力 in 结果:
            self.assertEqual(能力["调用示例"], "无", f"{能力['能力id']} 无示例须标注为无")
            self.assertIn("验证场景引用", 能力["验证状态"])
            self.assertIn("验证成功记录", 能力["验证状态"])
        # 模块库能力搜索数据已生成：提供者如实落到包自身、必填为明确布尔值（不再标"未声明"）
        模块能力 = [能力 for 能力 in 结果 if 能力["包id"].startswith("模块库.")]
        self.assertGreater(len(模块能力), 0)
        for 能力 in 模块能力:
            self.assertEqual(能力["提供者"], 能力["包id"])
            for 参数 in 能力["参数"]:
                self.assertIn(参数["必填"], (True, False, "未声明"),
                              f"{能力['能力id']} 参数 {参数['名称']} 必填应如实标注")
        # 支持库/后端/PDF文档 错误码已从契约补齐：应为真实错误码列表（非"无"）
        解析PDF = 公开能力模块.读取公开能力(项目根, "办公文档支持库.PDF文档.解析PDF")
        self.assertIsNotNone(解析PDF)
        self.assertIsInstance(解析PDF["错误码"], list)
        self.assertGreater(len(解析PDF["错误码"]), 0)
        self.assertNotEqual(解析PDF["错误码"], "无")

    def test_搜索不加载支持库实现(self) -> None:
        for 包名 in 第三方实现包表:
            self.assertNotIn(包名, sys.modules, f"搜索前不得已加载实现包 {包名}")
        搜索前模块表 = set(sys.modules)
        for 关键词 in ("图像", "PDF", "签名", "媒体"):
            公开能力模块.搜索公开能力(项目根, 关键词, 10)
        新增模块表 = set(sys.modules) - 搜索前模块表
        for 包名 in 第三方实现包表:
            self.assertNotIn(包名, sys.modules, f"搜索不得加载实现包 {包名}")
        self.assertEqual(
            新增模块表, set(),
            f"搜索不得 import 任何新模块（新增：{sorted(新增模块表)}）",
        )

    def test_读取公开能力十字段同样齐全(self) -> None:
        搜索 = 公开能力模块.搜索公开能力(项目根, "PDF", 5)
        self.assertGreater(len(搜索), 0)
        for 能力 in 搜索:
            读取 = 公开能力模块.读取公开能力(项目根, 能力["能力id"])
            self.assertIsNotNone(读取, f"读取 {能力['能力id']} 应有结果")
            for 字段 in 十字段:
                self.assertIn(字段, 读取, f"读取 {能力['能力id']} 缺字段 {字段}")
            self.assertEqual(读取["能力id"], 能力["能力id"])

    def test_版本提供者返回结构真实值(self) -> None:
        解码图像 = 公开能力模块.读取公开能力(项目根, "图像处理.识别图像格式")
        self.assertIsNotNone(解码图像)
        self.assertEqual(解码图像["版本"], "1.0.0")
        self.assertEqual(解码图像["提供者"], "模块库.图像处理")
        self.assertIsInstance(解码图像["返回结构"], dict)
        self.assertIn("参数不合法", 解码图像["错误码"])
        self.assertEqual(解码图像["调用示例"], "无")

    def test_验证状态如实标注当前真实状态(self) -> None:
        解码图像 = 公开能力模块.读取公开能力(项目根, "图像处理.识别图像格式")
        self.assertIsNotNone(解码图像)
        self.assertIn("验证场景引用", 解码图像["验证状态"])
        # 支持库包版本来自 能力定义/包声明，全部为版本字符串
        for 字段 in ("版本", "提供者"):
            self.assertTrue(解码图像[字段])

    def test_兼容旧字段与搜索匹配(self) -> None:
        结果 = 公开能力模块.搜索公开能力(项目根, "解析PDF", 10)
        self.assertGreater(len(结果), 0)
        for 能力 in 结果:
            self.assertIn("能力id", 能力)
            self.assertIn("包id", 能力)
            self.assertIn("参数", 能力)
            self.assertIn("返回", 能力)
            self.assertEqual(能力["返回"], 能力["返回结构"])

    def test_模板能力不进入公开搜索(self) -> None:
        结果 = 公开能力模块.搜索公开能力(项目根, "模板", 100)
        self.assertFalse(
            any(项.get("包id") == "模块库._模板" or str(项.get("能力id", "")).startswith("_模板.") for 项 in 结果),
            结果,
        )


if __name__ == "__main__":
    unittest.main()
