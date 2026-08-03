"""Tesseract 提供者测试：真实版本探针/语言包/OCR（生成测试图片）+受管进程超时/取消/
输出上限/崩溃/零残留；tesseract 缺失时如实标记"未配置"（skipTest），工具缺失语义仍经注入断言。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path: sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.Tesseract提供者 import 识别图片, 语言包列表, 版本探针
from 支持库.适配层.Tesseract提供者.实现 import 提供者 as 提供者模块
from 支持库.适配层.Tesseract提供者.实现 import 受管进程 as 受管模块
from 支持库.适配层.Tesseract提供者.实现.临时文件 import 临时目录前缀

tesseract存在 = lambda: shutil.which("tesseract") is not None


def _生成图片(路径: Path, 文本: str = "Hello OCR 123") -> None:
    from PIL import Image, ImageDraw
    图片 = Image.new("L", (400, 120), 255)
    ImageDraw.Draw(图片).text((20, 40), 文本, fill=0); 图片.save(路径)


class Test版本探针(unittest.TestCase):
    def test_工具缺失语义(self):
        with mock.patch.object(提供者模块, "_查找工具", return_value=None):
            结果 = 版本探针()
        self.assertEqual((结果.错误码, 结果.可重试), ("工具缺失", True))

    def test_版本探针真实调用(self):
        if not tesseract存在(): self.skipTest("本机未配置 tesseract")
        结果 = 版本探针()
        self.assertTrue(结果.成功 and 结果.值["退出码"] == 0, 结果.错误说明)
        self.assertRegex(结果.值["版本"], r"^\d+(?:\.\d+)+$")


class Test语言包列表(unittest.TestCase):
    def test_工具缺失语义(self):
        with mock.patch.object(提供者模块, "_查找工具", return_value=None):
            结果 = 语言包列表()
        self.assertEqual(结果.错误码, "工具缺失")

    def test_真实调用(self):
        if not tesseract存在(): self.skipTest("本机未配置 tesseract")
        结果 = 语言包列表()
        self.assertTrue(结果.成功 and 结果.值["数量"] > 0, 结果.错误说明)
        self.assertIn("eng", 结果.值["语言列表"])


class Test识别图片(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_Tesseract提供者_"))
        self.图片路径 = self.临时目录 / "ocr_image.png"
        if tesseract存在(): _生成图片(self.图片路径)

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_参数校验(self):
        for 调用 in (识别图片, lambda: 识别图片("a.png", b"xx"),
                     lambda: 识别图片("a.png", 语言=" "),
                     lambda: 识别图片("a.png", 词级数据=1),
                     lambda: 识别图片(图片字节=b"")):
            self.assertEqual(调用().错误码, "参数不合法")

    def test_文件不存在(self):
        self.assertEqual(识别图片(str(self.临时目录 / "不存在.png")).错误码, "文件不存在")

    def test_真实OCR文本(self):
        if not tesseract存在(): self.skipTest("本机未配置 tesseract")
        结果 = 识别图片(str(self.图片路径))
        self.assertTrue(结果.成功 and "123" in 结果.值["文本"], 结果.错误说明)

    def test_真实OCR词级(self):
        if not tesseract存在(): self.skipTest("本机未配置 tesseract")
        结果 = 识别图片(str(self.图片路径), 词级数据=True)
        self.assertTrue(结果.成功 and "文本" in 结果.值["词列表"][0], 结果.错误说明)

    def test_字节输入与临时目录零残留(self):
        if not tesseract存在(): self.skipTest("本机未配置 tesseract")
        结果 = 识别图片(图片字节=self.图片路径.read_bytes())
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue("123" in 结果.值["文本"]
                        and not list(Path(tempfile.gettempdir()).glob(临时目录前缀 + "*")),
                        "识别失败或临时目录未清理（零残留被破坏）")

    def test_语言包缺失语义(self):
        if not tesseract存在(): self.skipTest("本机未配置 tesseract")
        self.assertEqual(识别图片(str(self.图片路径), 语言="zzzz不存在语言").错误码, "语言包缺失")

    def test_识别失败语义(self):
        if not tesseract存在(): self.skipTest("本机未配置 tesseract")
        坏文件 = self.临时目录 / "not_image.txt"
        坏文件.write_text("这不是图片", encoding="utf-8")
        self.assertEqual(识别图片(str(坏文件)).错误码, "识别失败")

    def test_进程崩溃与取消透传(self):
        for 结果 in (提供者模块.结果.成功结果({"退出码": -9, "标准输出": "", "标准错误": ""}),
                     提供者模块.结果.失败("取消", "任务已被取消", 可重试=True)):

            with mock.patch.object(提供者模块, "执行命令", return_value=结果):
                返回值 = 识别图片(str(self.图片路径))
            self.assertEqual(返回值.错误码, "进程崩溃" if 结果.成功 else "取消")


class Test受管进程(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_Tesseract受管进程_"))

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_超时强杀(self):
        开始 = time.monotonic()
        结果 = 受管模块.执行命令([sys.executable, "-c", "import time; time.sleep(30)"], 超时秒=0.5)
        self.assertEqual((结果.错误码, 结果.可重试), ("超时", True))
        self.assertLess(time.monotonic() - 开始, 10)

    def test_取消(self):
        事件 = threading.Event(); threading.Timer(0.3, 事件.set).start()
        结果 = 受管模块.执行命令([sys.executable, "-c", "import time; time.sleep(30)"], 超时秒=30, 取消事件=事件)
        self.assertEqual(结果.错误码, "取消")

    def test_输出上限(self):
        结果 = 受管模块.执行命令([sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"], 输出上限字节=1024)
        self.assertEqual(结果.错误码, "超出限制")

    def test_进程崩溃与退出码数据(self):
        for 代码, 期望 in (("import os, signal; os.kill(os.getpid(), signal.SIGKILL)", -9), ("import sys; sys.exit(3)", 3)):
            结果 = 受管模块.执行命令([sys.executable, "-c", 代码])
            self.assertTrue(结果.成功, 结果.错误说明)
            self.assertEqual(结果.值["退出码"], 期望)

    def test_零残留进程(self):
        pid文件 = self.临时目录 / "pid.txt"
        结果 = 受管模块.执行命令(
            [sys.executable, "-c",
             f"import os, time; open({str(pid文件)!r}, 'w').write(str(os.getpid())); time.sleep(30)"],
            超时秒=0.5)
        self.assertEqual(结果.错误码, "超时")
        with self.assertRaises(OSError):
            os.kill(int(pid文件.read_text()), 0)

    def test_参数不合法与提供者不可用(self):
        self.assertEqual(受管模块.执行命令([]).错误码, "参数不合法")
        self.assertEqual(受管模块.执行命令(["echo"], 超时秒=0).错误码, "参数不合法")
        with mock.patch.object(subprocess, "Popen", side_effect=OSError("失败")):
            结果 = 受管模块.执行命令(["tesseract", "--version"])
        self.assertEqual((结果.错误码, 结果.可重试), ("提供者不可用", True))


if __name__ == "__main__": unittest.main()
