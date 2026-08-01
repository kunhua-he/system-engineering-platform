"""文字文档支持库真实解析测试（unittest）。

覆盖：最小有效 docx / 多段落表格中文 / 空文档 / 损坏文件 / 扩展名伪装 /
缺提供者（monkeypatch 模拟）/ doc 转换链（LibreOffice 在则真实转换）/ 往返。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.文字文档 import 解析文字文档
from 支持库.后端.文字文档.实现 import 文字文档 as 实现模块


def _生成docx(路径: Path, 中文: bool = True) -> None:
    from docx import Document
    文档 = Document()
    文档.add_heading("测试标题", level=1)
    文档.add_paragraph("第一段：中文内容。" if 中文 else "First paragraph.")
    表格 = 文档.add_table(rows=2, cols=2)
    表格.cell(0, 0).text = "姓名"
    表格.cell(0, 1).text = "分数"
    表格.cell(1, 0).text = "张三"
    表格.cell(1, 1).text = "95"
    文档.save(str(路径))


class Test文字文档(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.mkdtemp(prefix="测试_文字文档_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_解析最小docx(self):
        路径 = Path(self.临时目录) / "最小.docx"
        _生成docx(路径)
        结果 = 解析文字文档(str(路径), "docx")
        self.assertTrue(结果.成功, f"失败: {结果.错误说明 if not 结果.成功 else ''}")
        文档 = 结果.值
        self.assertEqual(文档.格式, "docx")
        self.assertEqual(文档.标题, "最小.docx")
        文本合集 = " ".join(块.文本 for 块 in 文档.块列表)
        self.assertIn("测试标题", 文本合集)
        self.assertIn("中文内容", 文本合集)
        self.assertTrue(any(块.类型 == "表格" for 块 in 文档.块列表))
        表格块 = next(块 for 块 in 文档.块列表 if 块.类型 == "表格")
        self.assertEqual(表格块.表格数据[0], ["姓名", "分数"])

    def test_空文档解析(self):
        路径 = Path(self.临时目录) / "空.docx"
        from docx import Document
        文档 = Document()
        文档.save(str(路径))
        结果 = 解析文字文档(str(路径), "docx")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值.块列表, [])

    def test_文件不存在(self):
        结果 = 解析文字文档("/不存在的路径/文件.docx", "docx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_格式非法(self):
        路径 = Path(self.临时目录) / "非法.docx"
        _生成docx(路径)
        结果 = 解析文字文档(str(路径), "pdf")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_损坏文件(self):
        路径 = Path(self.临时目录) / "损坏.docx"
        路径.write_bytes(b"not a zip at all" * 100)
        结果 = 解析文字文档(str(路径), "docx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_扩展名伪装(self):
        路径 = Path(self.临时目录) / "伪装.docx"
        路径.write_text("这只是个文本文件", encoding="utf-8")
        结果 = 解析文字文档(str(路径), "docx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_缺提供者返回不可用(self):
        # monkeypatch 模拟 python-docx 缺失
        原缓存 = 实现模块._提供者缓存
        实现模块._提供者缓存 = {"docx": None, "版本": {"python-docx": "不可用"}}
        try:
            路径 = Path(self.临时目录) / "任意.docx"
            路径.write_bytes(b"x")
            结果 = 解析文字文档(str(路径), "docx")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            实现模块._提供者缓存 = 原缓存

    def test_doc转换链(self):
        # 本机 LibreOffice 可用时真实转换
        import shutil
        soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if not Path(soffice).exists():
            self.skipTest("LibreOffice 不可用")
        路径 = Path(self.临时目录) / "旧文档.doc"
        _生成docx(路径)
        # 把 docx 内容另存为 doc（LibreOffice 转换 docx→doc 再验证反向）
        import subprocess
        目标 = Path(self.临时目录) / "旧文档.docx"
        _生成docx(目标)
        子进程 = subprocess.run(
            [soffice, "--headless", "--convert-to", "doc", "--outdir", str(self.临时目录), str(目标)],
            capture_output=True, timeout=120,
        )
        if not 路径.exists():
            self.skipTest("LibreOffice doc 转换未产出")
        结果 = 解析文字文档(str(路径), "doc")
        self.assertTrue(结果.成功, f"doc 解析失败: {结果.错误说明 if not 结果.成功 else ''}")
        self.assertIn("converted_from_doc", 结果.值.警告)

    def test_往返验证(self):
        路径 = Path(self.临时目录) / "往返.docx"
        _生成docx(路径)
        结果 = 解析文字文档(str(路径), "docx")
        self.assertTrue(结果.成功)
        文档 = 结果.值
        self.assertTrue(文档.原始文件摘要)
        self.assertIn("python-docx", 文档.提供者版本)


if __name__ == "__main__":
    unittest.main()
