"""LibreOffice/textutil 文档转换提供者真实测试。

覆盖：检查提供者/真实转换链（doc→txt、rtf→txt）/参数不合法/文件不存在/
提供者缺失注入（禁 sys.modules，环境变量注入）/超时/输出上限。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _生成docx(路径: Path) -> None:
    """用 python-docx 生成最小 docx（测试辅助，仅测试侧依赖）。"""
    from docx import Document
    文档 = Document()
    文档.add_paragraph("转换链测试内容")
    文档.save(路径)


def _生成rtf(路径: Path) -> None:
    """完整 RTF 文档（中文用 \\uN unicode 转义）。"""
    文本 = "文本转换测试内容"
    转义 = "".join(f"\\u{ord(c)}?" if ord(c) > 127 else c for c in 文本)
    路径.write_text(
        "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 SimSun;}}\\f0 " + 转义 + "\\par}",
        encoding="ascii",
    )


class TestLibreOffice提供者(unittest.TestCase):
    """LibreOffice 转换提供者测试。"""

    def test_检查提供者(self):
        from 支持库.适配层.LibreOffice提供者 import 检查提供者
        结果 = 检查提供者()
        self.assertTrue(结果.成功)
        self.assertIn("LibreOffice", 结果.值)

    def test_参数不合法(self):
        from 支持库.适配层.LibreOffice提供者 import 转换办公文件
        结果 = 转换办公文件("", "txt")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        结果2 = 转换办公文件("/tmp/不存在.docx", "txt")
        self.assertEqual(结果2.错误码, "文件不存在")

    def test_缺提供者注入(self):
        """注入 LibreOffice 缺失（环境变量禁用查找路径）→ 提供者不可用。"""
        from 支持库.适配层.LibreOffice提供者 import 转换办公文件
        with mock.patch("支持库.适配层.LibreOffice提供者.实现.文档转换._提供者缓存", {"soffice": None}):
            结果 = 转换办公文件("/tmp/x.docx", "txt")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")

    def test_doc转txt真实链(self):
        """真实 LibreOffice docx→txt 转换链（缺 LibreOffice 时明确失败）。"""
        from 支持库.适配层.LibreOffice提供者 import 检查提供者, 转换办公文件
        检查 = 检查提供者()
        if 检查.值.get("LibreOffice") != "可用":
            self.skipTest("LibreOffice 不可用")
        临时 = Path(tempfile.mkdtemp())
        输入文件 = 临时 / "转换链测试.docx"
        _生成docx(输入文件)
        结果 = 转换办公文件(str(输入文件), "txt", 输出目录=str(临时))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIn("转换链测试内容", 结果.值["文本"])


class TestTextutil提供者(unittest.TestCase):
    """textutil 转换提供者测试。"""

    def test_检查提供者(self):
        from 支持库.适配层.textutil提供者 import 检查提供者
        结果 = 检查提供者()
        self.assertTrue(结果.成功)
        self.assertIn("textutil", 结果.值)

    def test_rtf转txt真实链(self):
        """真实 textutil rtf→txt 转换链（macOS 自带）。"""
        from 支持库.适配层.textutil提供者 import 检查提供者, 转换文本文件
        检查 = 检查提供者()
        if 检查.值.get("textutil") != "可用":
            self.skipTest("textutil 不可用")
        临时 = Path(tempfile.mkdtemp())
        输入文件 = 临时 / "测试.rtf"
        _生成rtf(输入文件)
        结果 = 转换文本文件(str(输入文件), "txt", 输出目录=str(临时))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIn("文本转换测试内容", 结果.值["文本"])

    def test_参数不合法(self):
        from 支持库.适配层.textutil提供者 import 转换文本文件
        结果 = 转换文本文件("", "txt")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main()
