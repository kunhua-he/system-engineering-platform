"""pdfplumber 提供者测试：真实 PDF 文本/表格解析 + 加密/损坏/超时/禁用语义。

pdfplumber 为纯 Python 库主进程导入；环境可用时走真实解析成功链；
禁用环境变量/缺库 → 提供者不可用（如实标记，不伪装成功）。
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.pdfplumber提供者 import 解析PDF, 提取表格
from 支持库.适配层.pdfplumber提供者.实现 import PDF文本表格 as 实现模块


def _生成文本PDF(路径: Path, 页数: int = 2) -> Path:
    from reportlab.pdfgen import canvas
    画布 = canvas.Canvas(str(路径))
    for 页 in range(页数):
        画布.drawString(50, 700, f"pdfplumber 提供者测试 第{页 + 1}页")
        画布.showPage()
    画布.save()
    return 路径


def _生成表格PDF(路径: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table
    from reportlab.platypus.tableofcontents import TableStyle
    画布 = canvas.Canvas(str(路径))
    表 = Table([["列甲", "列乙"], ["甲1", "乙1"], ["甲2", "乙2"]])
    表.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    表.wrapOn(画布, 300, 100)
    表.drawOn(画布, 72, 650)
    画布.save()
    return 路径


def _生成加密PDF(路径: Path) -> Path:
    """子进程内 fitz 生成带密码 PDF（测试进程仍不加载 fitz）。"""
    代码 = ("import fitz;d=fitz.open();d.new_page();"
            f"d.save({str(路径)!r}, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='o', user_pw='u')")
    subprocess.run([sys.executable, "-c", 代码], check=True, capture_output=True)
    return 路径


class Testpdfplumber提供者(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_pdfplumber提供者_"))
        self.文本PDF = _生成文本PDF(self.临时目录 / "文本.pdf")
        self.表格PDF = _生成表格PDF(self.临时目录 / "表格.pdf")

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_解析PDF真实成功链(self):
        """真实 PDF 解析成功：文本块/标题/页数上限/提供者版本齐全。"""
        结果 = 解析PDF(str(self.文本PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 结果.值
        self.assertEqual(值["文档类型"], "PDF")
        self.assertTrue(值["块列表"], "文本 PDF 必须解析出块")
        self.assertTrue(all(块["类型"] in ("段落", "表格") for 块 in 值["块列表"]))
        self.assertIn("pdfplumber", 值["提供者版本"])
        self.assertTrue(值["原始文件摘要"])

    def test_解析PDF表格页真实成功(self):
        结果 = 解析PDF(str(self.表格PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(any(块["类型"] == "表格" for 块 in 结果.值["块列表"]))

    def test_提取表格成功(self):
        结果 = 提取表格(str(self.文本PDF), 1)
        self.assertTrue(结果.成功, 结果.错误说明)

    def test_提取表格页序号越界返回空列表(self):
        结果 = 提取表格(str(self.文本PDF), 9)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, [])

    def test_解析PDF文件不存在(self):
        结果 = 解析PDF(str(self.临时目录 / "不存在.pdf"))
        self.assertEqual(结果.错误码, "文件不存在")

    def test_解析PDF参数不合法(self):
        self.assertEqual(解析PDF("").错误码, "参数不合法")
        self.assertEqual(解析PDF(str(self.文本PDF), 最大页数=-1).错误码, "参数不合法")
        self.assertEqual(解析PDF(str(self.文本PDF), 最大字节数=-1).错误码, "参数不合法")
        self.assertEqual(解析PDF(str(self.文本PDF), 超时秒="快").错误码, "参数不合法")

    def test_解析PDF加密文件返回文件加密(self):
        加密PDF = _生成加密PDF(self.临时目录 / "加密.pdf")
        结果 = 解析PDF(str(加密PDF))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件加密")

    def test_解析PDF页数超限返回超出限制(self):
        结果 = 解析PDF(str(self.文本PDF), 最大页数=1)
        self.assertEqual(结果.错误码, "超出限制")

    def test_解析PDF文件大小超限(self):
        结果 = 解析PDF(str(self.文本PDF), 最大字节数=10)
        self.assertEqual(结果.错误码, "超出限制")

    def test_解析PDF损坏返回文件损坏(self):
        损坏 = self.临时目录 / "损坏.pdf"
        损坏.write_bytes(b"%PDF-1.4\n%%EOF broken-fragment")
        结果 = 解析PDF(str(损坏))
        self.assertEqual(结果.错误码, "文件损坏")

    def test_提供者禁用返回提供者不可用(self):
        with mock.patch.dict(sys.modules, {"pdfplumber": None}), \
                mock.patch.dict("os.environ", {"pdfplumber提供者_禁用库": "pdfplumber"}), \
                mock.patch.object(实现模块, "_提供者缓存", None):
            结果 = 解析PDF(str(self.文本PDF))
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试)

    def test_解析超时返回超时可重试(self):
        """工作线程 join 强约束：解析超过 超时秒 → 超时（可重试）。"""
        def 挂起解析(pdfplumber模块, 路径, 最大页数):
            import time
            time.sleep(30)
            return {"块列表": []}
        with mock.patch.object(实现模块, "_解析为字典", side_effect=挂起解析):
            结果 = 解析PDF(str(self.文本PDF), 超时秒=0.2)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)

    def test_公开入口返回统一结果(self):
        """公开入口只返回 结果 对象；不泄漏 pdfplumber 对象/句柄。"""
        结果 = 解析PDF(str(self.文本PDF))
        self.assertTrue(hasattr(结果, "成功"))
        self.assertFalse(hasattr(结果, "pdf"))
        self.assertFalse(hasattr(结果, "open"))


if __name__ == "__main__":
    unittest.main()
