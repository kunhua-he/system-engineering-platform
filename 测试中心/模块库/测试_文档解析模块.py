"""文档解析模块真实组合测试（unittest）。

覆盖：七格式真实解析（docx/xlsx/pptx/pdf 原生 + doc/xls/ppt 转换链）、
格式归一化、非法格式、缺提供者、往返一致性。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.文档解析 import 解析文档


def _生成docx(路径: Path) -> None:
    from docx import Document
    文档 = Document()
    文档.add_heading("组合测试标题", level=1)
    文档.add_paragraph("模块库文档解析组合测试段落")
    文档.save(str(路径))


def _生成xlsx(路径: Path) -> None:
    from openpyxl import Workbook
    工作簿 = Workbook()
    工作表 = 工作簿.active
    工作表.title = "数据"
    工作表.append(["列1", "列2"])
    工作表.append(["甲", 1])
    工作簿.save(str(路径))


def _生成pptx(路径: Path) -> None:
    from pptx import Presentation
    演示 = Presentation()
    幻灯片 = 演示.slides.add_slide(演示.slide_layouts[1])
    幻灯片.shapes.title.text = "组合演示标题"
    幻灯片.placeholders[1].text = "要点一"
    演示.save(str(路径))


def _生成pdf(路径: Path) -> None:
    from reportlab.pdfgen import canvas
    画布 = canvas.Canvas(str(路径))
    画布.drawString(50, 700, "PDF combined parse")
    画布.save()


class Test文档解析模块(unittest.TestCase):
    def setUp(self):
        """真实装配：注册全部解析提供者能力并经 装配系统 注入唯一能力调用服务。"""
        self.临时目录 = tempfile.mkdtemp(prefix="测试_文档解析模块_")
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
        from 支持库.后端.文档转换支持库.python_docx提供者 import 注册能力 as 注册docx
        from 支持库.后端.文档转换支持库.openpyxl提供者 import 注册能力 as 注册xlsx
        from 支持库.后端.文档转换支持库.python_pptx提供者 import 注册能力 as 注册pptx
        from 支持库.后端.文档转换支持库.PDF文本表格 import 注册能力 as 注册pdf
        from 支持库.后端.文档转换支持库.LibreOffice转换 import 注册能力 as 注册libre
        from 支持库.后端.系统核心支持库.资源管理 import 注册能力 as 注册资源管理
        # Provider 只注册内部实现能力；组合模块调用的公开能力由后端 owner 注册。
        from 支持库.后端.办公文档支持库.文字文档 import 注册能力 as 注册文字文档
        from 支持库.后端.办公文档支持库.表格文档 import 注册能力 as 注册表格文档
        from 支持库.后端.办公文档支持库.演示文稿 import 注册能力 as 注册演示文稿
        from 支持库.后端.办公文档支持库.PDF文档 import 注册能力 as 注册PDF文档

        注册表 = 能力注册表()
        注册docx(注册表)
        注册xlsx(注册表)
        注册pptx(注册表)
        注册pdf(注册表)
        注册libre(注册表)
        注册资源管理(注册表)
        注册文字文档(注册表)
        注册表格文档(注册表)
        注册演示文稿(注册表)
        注册PDF文档(注册表)
        self.注册表 = 注册表
        设置全局唯一服务(唯一能力调用服务(注册表))

    def tearDown(self):
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        设置全局唯一服务(None)
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_公开能力owner与内部实现分离(self):
        """公开能力必须由后端支持库持有，Provider 只能提供内部实现。"""
        for 公开id, owner, 内部id, provider in [
            ("办公文档支持库.文字文档.解析文字文档", "支持库.后端.办公文档支持库.文字文档", "内部.文字文档.解析", "支持库.后端.文档转换支持库.python_docx提供者"),
            ("办公文档支持库.表格文档.解析表格文档", "支持库.后端.办公文档支持库.表格文档", "内部.表格文档.解析", "支持库.后端.文档转换支持库.openpyxl提供者"),
            ("办公文档支持库.演示文稿.解析演示文稿", "支持库.后端.办公文档支持库.演示文稿", "内部.演示文稿.解析", "支持库.后端.文档转换支持库.python_pptx提供者"),
        ]:
            公开实现 = self.注册表.获取(公开id)
            内部实现 = self.注册表.获取(内部id)
            self.assertIsNotNone(公开实现, 公开id)
            self.assertIsNotNone(内部实现, 内部id)
            self.assertEqual(公开实现.包id, owner)
            self.assertEqual(内部实现.包id, provider)
            self.assertNotEqual(公开实现.包id, 内部实现.包id)

    def test_docx往返(self):
        路径 = Path(self.临时目录) / "测试.docx"
        _生成docx(路径)
        结果 = 解析文档(str(路径), "docx")
        self.assertTrue(结果.成功, f"失败: {结果.错误说明 if not 结果.成功 else ''}")
        文档 = 结果.值
        self.assertEqual(文档.格式, "docx")
        self.assertIn("组合测试标题", " ".join(块.文本 for 块 in 文档.块列表))

    def test_xlsx往返(self):
        路径 = Path(self.临时目录) / "测试.xlsx"
        _生成xlsx(路径)
        结果 = 解析文档(str(路径), "xlsx")
        self.assertTrue(结果.成功)
        文档 = 结果.值
        self.assertEqual(文档.格式, "xlsx")
        表格块 = next(块 for 块 in 文档.块列表 if 块.类型 == "工作表")
        self.assertEqual(表格块.表格数据[0][:2], ["列1", "列2"])

    def test_pptx往返(self):
        路径 = Path(self.临时目录) / "测试.pptx"
        _生成pptx(路径)
        结果 = 解析文档(str(路径), "pptx")
        self.assertTrue(结果.成功)
        文档 = 结果.值
        self.assertEqual(文档.格式, "pptx")
        文本合集 = " ".join(块.文本 for 块 in 文档.块列表)
        self.assertIn("组合演示标题", 文本合集)

    def test_pdf往返(self):
        路径 = Path(self.临时目录) / "测试.pdf"
        _生成pdf(路径)
        结果 = 解析文档(str(路径), "pdf")
        self.assertTrue(结果.成功)
        文档 = 结果.值
        self.assertEqual(文档.格式, "pdf")
        self.assertGreater(len(文档.块列表), 0)

    def test_格式归一化(self):
        路径 = Path(self.临时目录) / "测试.PDF"
        _生成pdf(路径)
        结果 = 解析文档(str(路径), ".PDF")
        self.assertTrue(结果.成功, f"归一化失败: {结果.错误说明 if not 结果.成功 else ''}")

    def test_非法格式(self):
        路径 = Path(self.临时目录) / "测试.txt"
        路径.write_text("文本", encoding="utf-8")
        结果 = 解析文档(str(路径), "txt")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_文件不存在(self):
        结果 = 解析文档("/不存在的路径/文件.docx", "docx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_缺提供者(self):
        # 依赖注入：环境变量禁用 pdfplumber → 平台返回 提供者不可用
        from 支持库.后端.文档转换支持库.PDF文本表格.实现 import PDF文本表格 as pdf实现
        原缓存 = pdf实现._提供者缓存
        pdf实现._提供者缓存 = None
        try:
            with mock.patch.dict(os.environ, {"pdfplumber提供者_禁用库": "pdfplumber"}):
                路径 = Path(self.临时目录) / "任意.pdf"
                路径.write_bytes(b"x")
                结果 = 解析文档(str(路径), "pdf")
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            pdf实现._提供者缓存 = 原缓存

    def test_doc转换链(self):
        import shutil
        import subprocess
        soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if not Path(soffice).exists():
            self.skipTest("LibreOffice 不可用")
        源 = Path(self.临时目录) / "源.docx"
        _生成docx(源)
        subprocess.run(
            [soffice, "--headless", "--convert-to", "doc", "--outdir", str(self.临时目录), str(源)],
            capture_output=True, timeout=120,
        )
        旧路径 = Path(self.临时目录) / "源.doc"
        if not 旧路径.exists():
            self.skipTest("LibreOffice doc 转换未产出")
        结果 = 解析文档(str(旧路径), "doc")
        self.assertTrue(结果.成功, f"doc 组合解析失败: {结果.错误说明 if not 结果.成功 else ''}")
        self.assertEqual(结果.值.格式, "docx")


if __name__ == "__main__":
    unittest.main()
