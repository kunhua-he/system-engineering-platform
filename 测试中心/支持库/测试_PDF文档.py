"""支持库.后端.办公文档支持库.PDF文档 真实解析测试：经隔离提供者执行。

覆盖：最小有效/多页/中文/空内容/表格/图像/损坏/加密/超页数/超大小/
文件不存在/参数不合法/提供者缺失（环境变量依赖注入）/超时/往返。
生成 PDF 用 reportlab（仅测试侧依赖，支持库本身不依赖）。

架构约束：主进程不 import fitz/pdfplumber（PyMuPDF SWIG 崩溃隔离）；
fitz/pdfplumber 只在 隔离子进程 内加载。测试禁止修改 sys.modules，
"提供者缺失"通过环境变量 PDF隔离提供者_禁用库 注入子进程模拟。
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.办公文档支持库.PDF文档 import 解析PDF


def _生成文本PDF(路径: Path, 页数: int = 1, 加密: bool = False) -> Path:
    """reportlab 生成中文 PDF（内置 CID 字体，无需字体文件）。

    注：pdfminer 对 reportlab 非嵌入 CID 中文字体仅单页提取可靠
    （多页时第 2 页起中文字符被丢弃，实测为 pdfplumber 限制），
    因此中文内容测试用单页，多页结构测试用 ASCII 内容。
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    画布 = canvas.Canvas(str(路径), pagesize=A4)
    if 加密:
        画布.setEncrypt("用户密码")
    画布.setFont("STSong-Light", 14)
    for 序号 in range(1, 页数 + 1):
        画布.drawString(72, 720, f"第{序号}页：你好，PDF 世界")
        画布.showPage()
    画布.save()
    return 路径


def _生成空白PDF(路径: Path) -> Path:
    """reportlab 生成无任何文本的空 PDF。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    画布 = canvas.Canvas(str(路径), pagesize=A4)
    画布.showPage()
    画布.save()
    return 路径


def _生成英文多页PDF(路径: Path, 页数: int = 3) -> Path:
    """reportlab 生成 ASCII 多页 PDF（pdfplumber 多页提取稳定）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    画布 = canvas.Canvas(str(路径), pagesize=A4)
    画布.setFont("Helvetica", 14)
    for 序号 in range(1, 页数 + 1):
        画布.drawString(72, 720, f"Page {序号} of three")
        画布.showPage()
    画布.save()
    return 路径


def _生成表格PDF(路径: Path) -> Path:
    """手绘线条表格 PDF（pdfplumber 可识别；platypus 填充矩形边框不被识别）。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    画布 = canvas.Canvas(str(路径))
    画布.setFont("STSong-Light", 12)
    x0, y0, 行高, 列宽 = 72, 700, 20, 120
    for 序号 in range(4):  # 3 条水平线
        画布.line(x0, y0 - 序号 * 行高, x0 + 2 * 列宽, y0 - 序号 * 行高)
    for 序号 in range(3):  # 2 条垂直线
        画布.line(x0 + 序号 * 列宽, y0, x0 + 序号 * 列宽, y0 - 3 * 行高)
    画布.drawString(x0 + 5, y0 - 15, "姓名")
    画布.drawString(x0 + 列宽 + 5, y0 - 15, "分数")
    画布.drawString(x0 + 5, y0 - 15 - 行高, "张三")
    画布.drawString(x0 + 列宽 + 5, y0 - 15 - 行高, "95")
    画布.save()
    return 路径


def _生成图像PDF(路径: Path) -> Path:
    """生成嵌入图像的 PDF（用隔离提供者的子进程完成，主进程不加载 fitz）。"""
    import subprocess
    脚本 = (
        "import sys, pathlib\n"
        "sys.path.insert(0, '.')\n"
        "import fitz\n"
        "d = fitz.open()\n"
        "p = d.new_page()\n"
        "px = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))\n"
        "px.clear_with(180)\n"
        "p.insert_image(fitz.Rect(50, 50, 150, 150), pixmap=px)\n"
        f"d.save({str(路径)!r})\n"
        "d.close()\n"
        "import os; os._exit(0)\n"
    )
    subprocess.run(
        [sys.executable, "-c", 脚本],
        cwd=str(Path(__file__).resolve().parents[2]),
        check=True, timeout=60,
    )
    return 路径


class TestPDF文档(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """装配唯一能力调用服务：安装全部支持库（含受管提供者）并绑定。"""
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定
        from 运行核心.加载器.包安装.支持库安装 import 安装全部支持库

        cls.注册表 = 能力注册表()
        安装全部支持库(系统根 / "支持库", cls.注册表)
        cls.服务 = 创建并绑定(cls.注册表)

    @classmethod
    def tearDownClass(cls):
        from 运行核心.能力调用.唯一能力调用 import 销毁全局唯一服务
        销毁全局唯一服务()

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_PDF文档_"))
        self.最小PDF = _生成文本PDF(self.临时目录 / "最小.pdf")
        self.多页PDF = _生成英文多页PDF(self.临时目录 / "多页.pdf", 页数=3)
        self.空PDF = _生成空白PDF(self.临时目录 / "空.pdf")

    def test_最小有效PDF中文(self):
        结果 = 解析PDF(str(self.最小PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        文档 = 结果.值
        self.assertEqual(文档.文档类型, "PDF")
        self.assertEqual(文档.格式, "pdf")
        self.assertTrue(文档.标题)
        段落文本 = "".join(块.文本 for 块 in 文档.块列表 if 块.类型 == "段落")
        self.assertIn("你好", 段落文本)
        self.assertIn("pdfplumber", 文档.提供者版本)
        self.assertIn("fitz", 文档.提供者版本)
        self.assertEqual(len(文档.原始文件摘要), 64)
        self.assertEqual(文档.解析方式, "pdfplumber+fitz")

    def test_多页PDF页码正确(self):
        结果 = 解析PDF(str(self.多页PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        页面块 = [块 for 块 in 结果.值.块列表 if 块.类型 == "页面"]
        self.assertEqual(len(页面块), 3)
        self.assertEqual([块.来源位置.页码 for 块 in 页面块], [1, 2, 3])
        self.assertIn("Page 3", "".join(块.文本 for 块 in 结果.值.块列表))

    def test_空内容PDF(self):
        结果 = 解析PDF(str(self.空PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        文档 = 结果.值
        self.assertGreaterEqual(len(文档.块列表), 1)
        self.assertEqual(文档.块列表[0].类型, "页面")
        self.assertEqual(文档.标题, "")

    def test_表格提取(self):
        表格PDF = _生成表格PDF(self.临时目录 / "表格.pdf")
        结果 = 解析PDF(str(表格PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        表格块 = [块 for 块 in 结果.值.块列表 if 块.类型 == "表格"]
        self.assertGreaterEqual(len(表格块), 1)
        全部单元格 = [单元格 for 行 in 表格块[0].表格数据 for 单元格 in 行]
        self.assertIn("张三", 全部单元格)

    def test_图像提取与资源渲染(self):
        图像PDF = _生成图像PDF(self.临时目录 / "图像.pdf")
        结果 = 解析PDF(str(图像PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        文档 = 结果.值
        图像块 = [块 for 块 in 文档.块列表 if 块.类型 == "图像"]
        self.assertGreaterEqual(len(图像块), 1)
        self.assertGreaterEqual(len(文档.资源列表), 1)
        资源 = 文档.资源列表[0]
        self.assertEqual(资源.类型, "图像")
        self.assertTrue(资源.字节数据b64)
        字节 = base64.b64decode(资源.字节数据b64)
        self.assertGreater(len(字节), 0)
        self.assertTrue(资源.媒体类型.startswith("image/"))

    def test_损坏文件(self):
        损坏 = self.临时目录 / "损坏.pdf"
        损坏.write_bytes("这不是PDF文件".encode("utf-8"))
        结果 = 解析PDF(str(损坏))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_加密文件(self):
        加密 = _生成文本PDF(self.临时目录 / "加密.pdf", 加密=True)
        结果 = 解析PDF(str(加密))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件加密")

    def test_超出页数限制(self):
        结果 = 解析PDF(str(self.多页PDF), 最大页数=2)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超出限制")

    def test_超出大小限制(self):
        结果 = 解析PDF(str(self.最小PDF), 最大字节数=100)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超出限制")

    def test_文件不存在(self):
        结果 = 解析PDF(str(self.临时目录 / "不存在.pdf"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_参数不合法(self):
        结果 = 解析PDF("")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_pdfplumber缺失返回提供者不可用(self):
        # 依赖注入：环境变量禁用 pdfplumber，子进程内不加载 → 提供者不可用
        with mock.patch.dict(os.environ, {"PDF隔离提供者_禁用库": "pdfplumber"}):
            结果 = 解析PDF(str(self.最小PDF))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试)

    def test_fitz缺失降级成功(self):
        # 依赖注入：环境变量禁用 fitz，子进程内仅 pdfplumber → 降级成功
        with mock.patch.dict(os.environ, {"PDF隔离提供者_禁用库": "fitz"}):
            结果 = 解析PDF(str(self.最小PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        文档 = 结果.值
        self.assertEqual(文档.解析方式, "pdfplumber")
        self.assertTrue(any("fitz" in 警告 for 警告 in 文档.警告))
        self.assertEqual(文档.提供者版本.get("fitz"), "不可用")

    def test_超时返回超时(self):
        结果 = 解析PDF(str(self.最小PDF), 超时秒=1e-9)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")

    def test_生成解析往返(self):
        结果 = 解析PDF(str(self.多页PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        文档 = 结果.值
        self.assertEqual(len([块 for 块 in 文档.块列表 if 块.类型 == "页面"]), 3)
        # 同一文件两次解析摘要一致
        再次 = 解析PDF(str(self.多页PDF))
        self.assertEqual(文档.原始文件摘要, 再次.值.原始文件摘要)
        self.assertEqual(文档.标题, 再次.值.标题)


if __name__ == "__main__":
    unittest.main()
