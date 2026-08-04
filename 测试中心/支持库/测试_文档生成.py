"""支持库.后端.文档生成 原子能力真实测试。

覆盖：四格式最小有效文件 + 签名校验（ZIP 成员/PDF 头尾）、中文内容、
生成→第三方库重开往返、缺库降级（monkeypatch → 提供者不可用）、
参数不合法、签名校验独立能力、提供者版本与耗时报告。
"""

from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

系统根 = Path(__file__).resolve().parents[2]

from 公共契约.基础类型.结果类型 import 结果
from 支持库.后端.文档生成 import 生成DOCX, 生成PDF, 生成PPTX, 生成XLSX, 校验签名


class 假调用器:
    """测试注入的假能力调用器：按预设返回失败结果。"""

    def __init__(self, 预设结果=None):
        self.预设结果 = 预设结果

    def 调用能力(self, 能力id, 参数=None, **关键字):
        if self.预设结果 is not None:
            return self.预设结果
        return 结果.失败("提供者不可用", f"{能力id} 不可用（模拟调用器）", 来源="测试", 可重试=True)

    def 幂等重放(self, *args, **kwargs):
        return False

    def 查询调用历史(self, 上限=50):
        return []

    def 最近失败(self, 上限=10):
        return []

    def 回答九问(self, *args, **kwargs):
        return {}

DOCX参数 = {
    "内容块列表": [
        {"类型": "标题", "文本": "测试标题", "级别": 1},
        {"类型": "段落", "文本": "第一段中文内容", "加粗": True},
        {"类型": "表格", "表头": ["列甲", "列乙"], "行": [["值1", "值2"]]},
    ]
}
XLSX参数 = {
    "工作表列表": [
        {"表名": "数据表", "列": ["姓名", "数量"], "行": [["张三", 3], ["李四", 5]]}
    ]
}
PPTX参数 = {
    "幻灯片列表": [
        {"标题": "演示标题", "要点": ["要点一", "要点二"], "备注": "备注内容"}
    ]
}
PDF参数 = {
    "内容块列表": [
        {"类型": "标题", "文本": "PDF中文标题"},
        {"类型": "段落", "文本": "PDF中文段落内容测试"},
    ]
}

OOXML必要成员表 = {
    "docx": ["[Content_Types].xml", "word/document.xml"],
    "xlsx": ["[Content_Types].xml", "xl/workbook.xml"],
    "pptx": ["[Content_Types].xml", "ppt/presentation.xml"],
}


class 测试基类(unittest.TestCase):
    """装配唯一能力调用服务；断言生成结果与签名。"""

    @classmethod
    def setUpClass(cls):
        """安装全部支持库（含受管提供者）并绑定唯一能力调用服务。"""
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

    def 断言OOXML签名(self, 格式: str, 字节: bytes):
        with zipfile.ZipFile(io.BytesIO(字节)) as 压缩包:
            self.assertIsNone(压缩包.testzip())
            名称表 = set(压缩包.namelist())
        for 成员 in OOXML必要成员表[格式]:
            self.assertIn(成员, 名称表, f"{格式} 缺少必要成员 {成员}")

    def 断言PDF签名(self, 字节: bytes):
        self.assertTrue(字节.startswith(b"%PDF"), "缺少 %PDF 文件头")
        self.assertTrue(字节.rstrip().endswith(b"%%EOF"), "缺少 %%EOF 文件尾")
        import fitz

        with fitz.open(stream=字节, filetype="pdf") as 文档:
            self.assertGreaterEqual(文档.page_count, 1)


class Test生成DOCX(测试基类):
    def test_最小有效文件与签名(self):
        结果 = 生成DOCX({"内容块列表": [{"类型": "段落", "文本": "最小文档"}]})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(结果.值.字节.startswith(b"PK"))
        self.断言OOXML签名("docx", 结果.值.字节)
        self.assertEqual(结果.值.格式, "docx")
        self.assertEqual(结果.值.摘要, __import__("hashlib").sha256(结果.值.字节).hexdigest())

    def test_中文内容生成与往返(self):
        结果 = 生成DOCX(DOCX参数)
        self.assertTrue(结果.成功, 结果.错误说明)
        from docx import Document

        文档 = Document(io.BytesIO(结果.值.字节))
        文本 = "\n".join(段落.text for 段落 in 文档.paragraphs)
        self.assertIn("测试标题", 文本)
        self.assertIn("第一段中文内容", 文本)
        self.assertEqual(len(文档.tables), 1)
        self.assertEqual(文档.tables[0].rows[0].cells[0].text, "列甲")
        self.assertEqual(文档.tables[0].rows[1].cells[1].text, "值2")

    def test_空内容参数不合法(self):
        结果 = 生成DOCX({})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_缺库提供者不可用(self):
        # 临时注入假调用器（受管提供者不可用）→ 如实返回 提供者不可用
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定, 设置全局唯一服务

        设置全局唯一服务(假调用器())
        try:
            结果 = 生成DOCX({"内容块列表": [{"类型": "段落", "文本": "x"}]})
        finally:
            创建并绑定(self.__class__.注册表)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")

    def test_生成异常转生成失败(self):
        # 临时注入假调用器（受管提供者返回 生成失败）→ 如实透传
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定, 设置全局唯一服务
        from 公共契约.基础类型.结果类型 import 结果 as 结果类型

        设置全局唯一服务(假调用器(预设结果=结果类型.失败("生成失败", "模拟生成器崩溃", 来源="测试")))
        try:
            结果 = 生成DOCX({"内容块列表": [{"类型": "段落", "文本": "x"}]})
        finally:
            创建并绑定(self.__class__.注册表)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "生成失败")

    def test_报告签名与耗时(self):
        结果 = 生成DOCX(DOCX参数)
        self.assertTrue(结果.成功)
        附加 = 结果.值.附加
        self.assertIn("签名校验", 附加)
        self.assertTrue(附加["签名校验"])
        self.assertIn("生成耗时秒", 附加)
        self.assertGreater(附加["生成耗时秒"], 0)


class Test生成XLSX(测试基类):
    def test_最小有效文件与签名(self):
        结果 = 生成XLSX({"工作表列表": [{"表名": "表", "列": ["列甲"], "行": [["值"]]}]})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.断言OOXML签名("xlsx", 结果.值.字节)

    def test_中文内容生成与往返(self):
        结果 = 生成XLSX(XLSX参数)
        self.assertTrue(结果.成功, 结果.错误说明)
        from openpyxl import load_workbook

        工作簿 = load_workbook(io.BytesIO(结果.值.字节))
        self.assertIn("数据表", 工作簿.sheetnames)
        表单 = 工作簿["数据表"]
        self.assertEqual(表单["A1"].value, "姓名")
        self.assertEqual(表单["A2"].value, "张三")
        self.assertEqual(表单["B3"].value, "5")  # 单元格统一按文本写入（与 V3 兼容）

    def test_空工作表参数不合法(self):
        结果 = 生成XLSX({})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_缺库提供者不可用(self):
        # 临时注入假调用器（受管提供者不可用）→ 如实返回 提供者不可用
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定, 设置全局唯一服务

        设置全局唯一服务(假调用器())
        try:
            结果 = 生成XLSX({"工作表列表": [{"表名": "表", "行": [["x"]]}]})
        finally:
            创建并绑定(self.__class__.注册表)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test生成PPTX(测试基类):
    def test_最小有效文件与签名(self):
        结果 = 生成PPTX({"幻灯片列表": [{"标题": "标题", "要点": ["要点"]}]})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.断言OOXML签名("pptx", 结果.值.字节)

    def test_中文内容生成与往返(self):
        结果 = 生成PPTX(PPTX参数)
        self.assertTrue(结果.成功, 结果.错误说明)
        from pptx import Presentation

        演示文稿 = Presentation(io.BytesIO(结果.值.字节))
        self.assertEqual(len(演示文稿.slides), 1)
        页面 = 演示文稿.slides[0]
        全部文本 = "".join(
            形状.text for 形状 in 页面.shapes if 形状.has_text_frame
        )
        self.assertIn("演示标题", 全部文本)
        self.assertIn("要点一", 全部文本)
        self.assertIn("要点二", 全部文本)
        self.assertIn("备注内容", 页面.notes_slide.notes_text_frame.text)

    def test_空幻灯片参数不合法(self):
        结果 = 生成PPTX({})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_缺库提供者不可用(self):
        # 临时注入假调用器（受管提供者不可用）→ 如实返回 提供者不可用
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定, 设置全局唯一服务

        设置全局唯一服务(假调用器())
        try:
            结果 = 生成PPTX({"幻灯片列表": [{"标题": "标题"}]})
        finally:
            创建并绑定(self.__class__.注册表)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test生成PDF(测试基类):
    def test_最小有效文件与签名(self):
        结果 = 生成PDF({"内容块列表": [{"类型": "段落", "文本": "最小PDF"}]})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.断言PDF签名(结果.值.字节)
        self.assertEqual(结果.值.媒体类型, "application/pdf")

    def test_中文内容生成与往返(self):
        结果 = 生成PDF(PDF参数)
        self.assertTrue(结果.成功, 结果.错误说明)
        import fitz

        with fitz.open(stream=结果.值.字节, filetype="pdf") as 文档:
            文本 = "\n".join(页.get_text() for 页 in 文档)
        self.assertIn("PDF中文标题", 文本)
        self.assertIn("PDF中文段落内容测试", 文本)

    def test_空内容参数不合法(self):
        结果 = 生成PDF({})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_缺库提供者不可用(self):
        # 临时注入假调用器（受管提供者不可用）→ 如实返回 提供者不可用
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定, 设置全局唯一服务

        设置全局唯一服务(假调用器())
        try:
            结果 = 生成PDF({"内容块列表": [{"类型": "段落", "文本": "x"}]})
        finally:
            创建并绑定(self.__class__.注册表)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test校验签名(测试基类):
    def test_正常OOXML签名通过(self):
        for 格式, 参数 in (
            ("docx", {"内容块列表": [{"类型": "段落", "文本": "x"}]}),
            ("xlsx", {"工作表列表": [{"表名": "表", "行": [["x"]]}]}),
            ("pptx", {"幻灯片列表": [{"标题": "标题"}]}),
        ):
            with self.subTest(格式=格式):
                生成结果 = {"docx": 生成DOCX, "xlsx": 生成XLSX, "pptx": 生成PPTX}[格式](参数)
                self.assertTrue(生成结果.成功)
                校验 = 校验签名(格式, 生成结果.值.字节)
                self.assertTrue(校验.成功, 校验.错误说明)

    def test_坏字节签名失败(self):
        for 格式 in ("docx", "xlsx", "pptx"):
            with self.subTest(格式=格式):
                校验 = 校验签名(格式, "这不是ZIP压缩包".encode("utf-8"))
                self.assertFalse(校验.成功)
                self.assertEqual(校验.错误码, "生成失败")

    def test_缺成员签名失败(self):
        import shutil

        结果 = 生成DOCX({"内容块列表": [{"类型": "段落", "文本": "x"}]})
        self.assertTrue(结果.成功)
        # 构造缺失 word/document.xml 的伪 docx：只留 [Content_Types].xml
        with zipfile.ZipFile(io.BytesIO(结果.值.字节)) as 源:
            伪字节 = io.BytesIO()
            with zipfile.ZipFile(伪字节, "w") as 目标:
                for 名称 in 源.namelist():
                    if 名称 == "word/document.xml":
                        continue
                    目标.writestr(名称, 源.read(名称))
        校验 = 校验签名("docx", 伪字节.getvalue())
        self.assertFalse(校验.成功)
        self.assertEqual(校验.错误码, "生成失败")
        self.assertIn("必要成员", 校验.错误说明)

    def test_PDF头尾校验(self):
        结果 = 生成PDF({"内容块列表": [{"类型": "段落", "文本": "x"}]})
        self.assertTrue(结果.成功)
        self.assertTrue(校验签名("pdf", 结果.值.字节).成功)
        # 截断尾部 → 缺 %%EOF → 失败
        self.assertFalse(校验签名("pdf", 结果.值.字节[:-4]).成功)
        # 无 %PDF 头 → 失败
        self.assertFalse(校验签名("pdf", "垃圾内容".encode("utf-8")).成功)

    def test_非法格式参数不合法(self):
        校验 = 校验签名("txt", b"abc")
        self.assertFalse(校验.成功)
        self.assertEqual(校验.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main()
