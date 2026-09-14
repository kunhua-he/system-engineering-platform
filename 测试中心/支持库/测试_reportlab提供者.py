"""reportlab 提供者测试：真实 PDF 生成 / 中文可提取 / 段落 / 表格 / 参数不合法。

覆盖：生成产物字典（字节b64/媒体类型/摘要）、中文字体真实可提取
（用平台 PDF 解析提供者回读验证）、段落与表格渲染、参数不合法、
提供者不可用注入、注册能力与声明一致、完整性摘要与文件清单一致。
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.能力契约.契约 import 能力注册表
from 支持库.适配层.PDF隔离提供者 import 解析PDF隔离
from 支持库.适配层.reportlab提供者 import 生成PDF, 注册能力
from 支持库.适配层.reportlab提供者.实现 import 生成PDF as 实现模块

提供者目录 = (
    Path(__file__).resolve().parents[2]
    / "支持库" / "适配层" / "reportlab提供者"
)


def _提取文本(路径: Path) -> str:
    """用平台 PDF 解析提供者提取全部文本（失败抛 AssertionError）。"""
    结果 = 解析PDF隔离(str(路径))
    if not 结果.成功:
        raise AssertionError(f"解析失败: {结果.错误说明}")
    return "".join(块.get("文本", "") for 块 in (结果.值 or {}).get("块列表", []))


class TestReportlab提供者(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_reportlab提供者_"))

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_真实生成PDF产物字典(self):
        """真实生成：标题+段落+表格，校验产物字典四要素。"""
        结果 = 生成PDF({
            "标题": "报告标题",
            "段落列表": ["第一段正文"],
            "表格列表": [{"表头": ["姓名", "数量"], "行": [["张三", "1"]]}],
        })
        self.assertTrue(结果.成功, 结果.错误说明)
        产物 = 结果.值
        字节 = base64.b64decode(产物["字节b64"])
        self.assertTrue(字节.startswith(b"%PDF"))
        self.assertEqual(产物["媒体类型"], "application/pdf")
        self.assertEqual(产物["摘要"], hashlib.sha256(字节).hexdigest())
        self.assertEqual(产物["字节数"], len(字节))
        self.assertGreater(产物["字节数"], 100)
        self.assertIn("reportlab", 产物["提供者版本"])

    def test_中文可提取(self):
        """中文内容真实写入 PDF 且可被平台解析提供者提取。"""
        结果 = 生成PDF({"标题": "华世王镞", "段落列表": ["支持库报告生成测试。"]})
        self.assertTrue(结果.成功, 结果.错误说明)
        路径 = self.临时目录 / "中文.pdf"
        路径.write_bytes(base64.b64decode(结果.值["字节b64"]))
        文本 = _提取文本(路径)
        self.assertIn("华世王镞", 文本)
        self.assertIn("支持库报告生成测试", 文本)

    def test_段落渲染全部可提取(self):
        """多个段落（含加粗字典项）全部真实渲染可提取。"""
        结果 = 生成PDF({
            "段落列表": ["第一段。", "第二段。", {"文本": "加粗段。", "加粗": True}],
        })
        self.assertTrue(结果.成功, 结果.错误说明)
        路径 = self.临时目录 / "段落.pdf"
        路径.write_bytes(base64.b64decode(结果.值["字节b64"]))
        文本 = _提取文本(路径)
        for 片段 in ("第一段。", "第二段。", "加粗段。"):
            self.assertIn(片段, 文本)

    def test_表格渲染表头与单元格可提取(self):
        """表格表头与行单元格全部真实渲染可提取。"""
        结果 = 生成PDF({
            "表格列表": [{"表头": ["名称", "数量"], "行": [["苹果", "3"], ["香蕉", "5"]]}],
        })
        self.assertTrue(结果.成功, 结果.错误说明)
        路径 = self.临时目录 / "表格.pdf"
        路径.write_bytes(base64.b64decode(结果.值["字节b64"]))
        文本 = _提取文本(路径)
        for 片段 in ("名称", "数量", "苹果", "3", "香蕉", "5"):
            self.assertIn(片段, 文本)

    def test_参数不合法(self):
        """非法参数一律返回 参数不合法。"""
        for 参数 in (
            "不是字典",
            {},
            {"段落列表": "不是列表"},
            {"标题": "x", "表格列表": "不是列表"},
            {"标题": 123},
        ):
            结果 = 生成PDF(参数)
            self.assertFalse(结果.成功, f"应失败: {参数!r}")
            self.assertEqual(结果.错误码, "参数不合法")

    def test_提供者不可用(self):
        """注入 reportlab 不可用 → 提供者不可用。"""
        with mock.patch.object(实现模块, "_提供者可用", return_value=False):
            结果 = 生成PDF({"标题": "测试"})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")

    def test_注册能力与声明一致(self):
        """注册能力可获取且与包声明能力一致（P3 唯一事实源格式）。"""
        注册表 = 能力注册表()
        注册能力(注册表)
        实现 = 注册表.获取("PDF生成.生成PDF")
        self.assertIsNotNone(实现)
        声明数据 = json.loads((提供者目录 / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(实现.能力id, "PDF生成.生成PDF")
        self.assertIn("PDF生成.生成PDF", [能力["能力id"] for 能力 in 声明数据["能力"]])
        # 能力定义是唯一事实源：声明能力清单与能力定义一致
        定义数据 = json.loads((提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        定义能力表 = [能力["能力id"] for 能力 in 定义数据["能力列表"]]
        self.assertIn("PDF生成.生成PDF", 定义能力表)

    def test_完整性摘要一致(self):
        """完整性摘要与包声明一致（文件清单格式，门禁口径）。"""
        摘要数据 = json.loads((提供者目录 / "完整性摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要数据["包id"], "支持库.适配层.reportlab提供者")
        self.assertEqual(摘要数据["摘要算法"], "sha256")
        self.assertTrue(摘要数据["文件清单"], "文件清单不得为空")
        清单路径 = {项["路径"] for 项 in 摘要数据["文件清单"]}
        self.assertIn("__init__.py", 清单路径)
        self.assertIn("能力定义.json", 清单路径)


if __name__ == "__main__":
    unittest.main()
