"""OCR 模块真实组合测试（unittest）。

覆盖：Pillow 生成占位图 → 真实 tesseract 识别（文本/词级/路径/字节）、
可用性检查真实探针、语言包缺失真实语义、工具缺失注入、超时/取消/崩溃
错误码透传、零残留、参数不合法与文件不存在。
"""

from __future__ import annotations

import base64
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.OCR import 可用性检查
from 模块库.OCR import 识别图片文件
from 模块库.OCR import 识别图片文字
from 支持库.适配层.Pillow提供者 import 生成占位图

测试文本 = "OCR 12345"


def _工具可用() -> bool:
    import shutil as 壳工具
    return 壳工具.which("tesseract") is not None


class TestOCR模块(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.mkdtemp(prefix="测试_OCR模块_")
        占位 = 生成占位图(宽度=900, 高度=200, 占位类型="文本",
                       背景颜色="#FFFFFF", 前景颜色="#000000", 文本=测试文本)
        self.assertTrue(占位.成功, f"生成占位图失败: {占位.错误说明}")
        self.图片字节 = base64.b64decode(占位.值["图像b64"])
        self.图片路径 = str(Path(self.临时目录) / "测试.png")
        Path(self.图片路径).write_bytes(self.图片字节)

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实识别路径入口(self):
        结果 = 识别图片文字(图片路径=self.图片路径)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("12345", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实识别字节入口(self):
        结果 = 识别图片文字(图片字节=self.图片字节)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("OCR", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实词级数据(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 词级数据=True)
        self.assertTrue(结果.成功, f"词级识别失败: {结果.错误码} {结果.错误说明}")
        词列表 = 结果.值["词列表"]
        self.assertGreater(len(词列表), 0)
        词文本 = [词["文本"] for 词 in 词列表]
        self.assertTrue(any("12345" in 词 for 词 in 词文本), f"未识别出目标词: {词文本}")

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_识别图片文件入口(self):
        结果 = 识别图片文件(图片路径=self.图片路径)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("12345", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_可用性检查真实探针(self):
        结果 = 可用性检查()
        self.assertTrue(结果.成功, f"可用性检查失败: {结果.错误码} {结果.错误说明}")
        值 = 结果.值
        self.assertTrue(值["版本"])
        self.assertTrue(值["满足最低版本"])
        self.assertIn("eng", 值["语言列表"])
        self.assertGreater(值["语言数量"], 0)

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_语言包缺失真实语义(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 语言="xx_不存在")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "语言包缺失")

    def test_工具缺失注入(self):
        from 支持库.适配层.Tesseract提供者.实现 import 提供者 as 提供者实现
        with mock.patch.object(提供者实现, "_查找工具", return_value=None):
            结果 = 识别图片文字(图片路径=self.图片路径)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "工具缺失")

    def test_超时透传(self):
        from 模块库.OCR.实现 import OCR as 模块实现
        失败结果 = 结果.失败("超时", "执行超时", 可重试=True)
        with mock.patch.object(模块实现, "识别图片", return_value=失败结果):
            识别 = 识别图片文字(图片路径=self.图片路径)
        self.assertFalse(识别.成功)
        self.assertEqual(识别.错误码, "超时")
        self.assertTrue(识别.可重试)

    def test_取消透传(self):
        from 模块库.OCR.实现 import OCR as 模块实现
        失败结果 = 结果.失败("取消", "任务被取消", 可重试=True)
        with mock.patch.object(模块实现, "识别图片", return_value=失败结果):
            识别 = 识别图片文字(图片路径=self.图片路径)
        self.assertFalse(识别.成功)
        self.assertEqual(识别.错误码, "取消")

    def test_进程崩溃透传(self):
        from 模块库.OCR.实现 import OCR as 模块实现
        失败结果 = 结果.失败("进程崩溃", "被信号杀死", 可重试=True)
        with mock.patch.object(模块实现, "识别图片", return_value=失败结果):
            识别 = 识别图片文字(图片路径=self.图片路径)
        self.assertFalse(识别.成功)
        self.assertEqual(识别.错误码, "进程崩溃")

    def test_参数不合法路径字节同时给(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 图片字节=self.图片字节)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_文件不存在(self):
        结果 = 识别图片文字(图片路径="/不存在的路径/图片.png")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_识别图片文件空路径(self):
        结果 = 识别图片文件(图片路径="")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_字节入口零残留(self):
        临时根 = Path(tempfile.gettempdir())
        识别前 = {目录.name for 目录 in 临时根.glob("Tesseract提供者_*") if 目录.is_dir()}
        结果 = 识别图片文字(图片字节=self.图片字节)
        self.assertTrue(结果.成功)
        识别后 = {目录.name for 目录 in 临时根.glob("Tesseract提供者_*") if 目录.is_dir()}
        self.assertEqual(识别后, 识别前, "字节识别后残留 Tesseract 临时目录")


if __name__ == "__main__":
    unittest.main()
