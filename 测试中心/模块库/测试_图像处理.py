"""模块库.图像处理 组合能力真实测试：PNG/JPEG 分析、占位图生成、
按内容识别格式、损坏错误码透传、支持库缺失→提供者不可用、注册能力。"""

from __future__ import annotations

import base64
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.图像处理 import 分析图像文件, 生成占位图, 识别图像格式

最小PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
最小JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q==")


class Test分析图像文件(unittest.TestCase):
    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="图像处理测试_"))

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def _写文件(self, 名称: str, 字节: bytes) -> Path:
        路径 = self.临时目录 / 名称
        路径.write_bytes(字节)
        return 路径

    def test_真实PNG分析返回解码与像素统计(self):
        结果 = 分析图像文件(str(self._写文件("真实.png", 最小PNG)))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "PNG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (1, 1))
        self.assertEqual(结果.值["像素数"], 1)
        self.assertEqual(set(结果.值["平均颜色"]), {"红", "绿", "蓝"})

    def test_真实JPEG分析返回格式与尺寸(self):
        结果 = 分析图像文件(str(self._写文件("真实.jpg", 最小JPEG)))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "JPEG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (1, 1))
        self.assertEqual(结果.值["像素数"], 1)

    def test_已知纯色像素统计精确(self):
        占位 = 生成占位图(4, 4, "纯色", 背景颜色="#123456")
        self.assertTrue(占位.成功, 占位.错误说明)
        文件 = self._写文件("纯色.png", base64.b64decode(占位.值["图像b64"]))
        结果 = 分析图像文件(str(文件))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["平均颜色"], {"红": 18, "绿": 52, "蓝": 86})

    def test_文件不存在返回文件不存在(self):
        结果 = 分析图像文件(str(self.临时目录 / "不存在.png"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_非法路径参数不合法(self):
        for 路径 in ("", None):
            self.assertEqual(分析图像文件(路径).错误码, "参数不合法")

    def test_损坏文件错误码透传(self):
        文件 = self._写文件("损坏.png", 最小PNG[:44])
        结果 = 分析图像文件(str(文件))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_文本伪装文件格式未知(self):
        文件 = self._写文件("伪装.png", "这不是图像内容".encode("utf-8"))
        结果 = 分析图像文件(str(文件))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "格式未知")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 分析图像文件(str(self._写文件("真实.png", 最小PNG)))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试)


class Test生成占位图(unittest.TestCase):
    def test_纯色占位图(self):
        结果 = 生成占位图(64, 32, "纯色", 背景颜色="#FF8800")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "PNG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 32))
        self.assertTrue(base64.b64decode(结果.值["图像b64"]).startswith(b"\x89PNG"))

    def test_渐变占位图(self):
        结果 = 生成占位图(64, 64, "渐变", 前景颜色="#FF0000", 背景颜色="#0000FF")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 64))

    def test_文本占位图(self):
        结果 = 生成占位图(300, 150, "文本", 文本="测试占位")
        self.assertTrue(结果.成功, 结果.错误说明)
        识别 = 识别图像格式(base64.b64decode(结果.值["图像b64"]))
        self.assertTrue(识别.成功, 识别.错误说明)
        self.assertEqual((识别.值["宽度"], 识别.值["高度"]), (300, 150))

    def test_非法参数透传(self):
        self.assertEqual(生成占位图(8, 8, "动画").错误码, "参数不合法")
        self.assertEqual(生成占位图(0, 8, "纯色").错误码, "参数不合法")
        self.assertEqual(生成占位图(8, 8, "纯色", 背景颜色="red").错误码, "参数不合法")


class Test识别图像格式(unittest.TestCase):
    def test_按内容识别JPEG不受后缀影响(self):
        结果 = 识别图像格式(最小JPEG)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "JPEG")

    def test_纯文本伪装返回格式未知(self):
        结果 = 识别图像格式("伪装成图像的内容".encode("utf-8"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "格式未知")

    def test_损坏字节文件损坏透传(self):
        结果 = 识别图像格式(最小PNG[:44])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_支持库缺失提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 识别图像格式(最小PNG)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")


class Test注册能力(unittest.TestCase):
    def test_模块注册三个能力(self):
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        from 模块库.图像处理 import 注册能力

        注册能力(注册表)
        self.assertEqual(len(注册表.条目), 3)
        self.assertEqual([条目.能力id for 条目 in 注册表.条目],
                         ["图像处理.分析图像文件", "图像处理.生成占位图", "图像处理.识别图像格式"])
        for 条目 in 注册表.条目:
            self.assertEqual(条目.包id, "模块库.图像处理")


if __name__ == "__main__":
    unittest.main()
