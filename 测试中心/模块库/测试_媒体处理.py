"""模块库.媒体处理 组合能力真实测试：ffprobe 探测、真实提取音频/抽帧/转码、
损坏媒体/无音轨错误码透传、ffmpeg 缺失→提供者不可用（注入）、零残留、注册能力。"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.媒体处理 import 检查提供者, 探测媒体, 提取音频, 转码, 抽取帧

临时根 = Path(tempfile.gettempdir())


def _生成视频(路径: Path, 含音频: bool) -> Path:
    """用真实 ffmpeg 生成最小测试视频（testsrc 画面 + 可选 sine 音轨）。"""
    参数 = ["ffmpeg", "-y", "-f", "lavfi", "-i",
            "testsrc=size=64x64:rate=10", "-t", "1"]
    if 含音频:
        参数 += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest"]
    参数 += ["-pix_fmt", "yuv420p", str(路径)]
    subprocess.run(参数, capture_output=True, check=True)
    return 路径


def _临时前缀集() -> set:
    return {条目 for 模式 in ("FFmpeg音频_*", "FFmpeg转码_*", "FFmpeg抽帧_*")
            for 条目 in 临时根.glob(模式)}


class 测试媒体处理(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.临时目录 = Path(tempfile.mkdtemp(prefix="测试_媒体处理_"))
        cls.可用 = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
        if cls.可用:
            cls.带音频 = _生成视频(cls.临时目录 / "带音频.mp4", 含音频=True)
            cls.纯视频 = _生成视频(cls.临时目录 / "纯视频.mp4", 含音频=False)
            cls.损坏文件 = cls.临时目录 / "损坏.bin"
            cls.损坏文件.write_bytes(os.urandom(4096))
            cls.缺失路径 = str(cls.临时目录 / "不存在.mp4")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.临时目录, ignore_errors=True)

    def setUp(self):
        if not self.可用:
            self.skipTest("ffmpeg/ffprobe 未配置（如实标记，不伪装可用）")

    def test_检查提供者真实可用(self):
        结果 = 检查提供者()
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIn("ffmpeg", 结果.值["版本"])

    def test_检查提供者缺失返回提供者不可用(self):
        with mock.patch("支持库.适配层.FFmpeg提供者.实现.探测.查找命令",
                        return_value=None):
            结果 = 检查提供者()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")

    def test_探测媒体真实返回时长与流(self):
        结果 = 探测媒体(str(self.带音频))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertAlmostEqual(结果.值["时长秒"], 1.0, delta=0.5)
        流类型 = {流["类型"] for 流 in 结果.值["流"]}
        self.assertIn("video", 流类型)
        self.assertIn("audio", 流类型)
        self.assertTrue(结果.值["格式"])
        self.assertGreater(结果.值["大小字节"], 0)

    def test_探测媒体损坏返回损坏媒体(self):
        结果 = 探测媒体(str(self.损坏文件))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "损坏媒体")

    def test_探测媒体文件不存在(self):
        self.assertEqual(探测媒体(self.缺失路径).错误码, "文件不存在")

    def test_探测媒体参数不合法(self):
        self.assertEqual(探测媒体("").错误码, "参数不合法")
        self.assertEqual(探测媒体(None).错误码, "参数不合法")

    def test_提取音频真实wav字节返回(self):
        结果 = 提取音频(str(self.带音频))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "wav")
        self.assertGreater(结果.值["字节数"], 0)
        self.assertEqual(len(base64.b64decode(结果.值["字节b64"])), 结果.值["字节数"])

    def test_提取音频mp3格式(self):
        结果 = 提取音频(str(self.带音频), 输出格式="mp3")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "mp3")

    def test_提取音频无音轨(self):
        结果 = 提取音频(str(self.纯视频))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "无音轨")

    def test_提取音频损坏媒体(self):
        结果 = 提取音频(str(self.损坏文件))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "损坏媒体")

    def test_提取音频超长媒体(self):
        结果 = 提取音频(str(self.带音频), 最大时长秒=0.001)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超长媒体")

    def test_提取音频超出限制(self):
        结果 = 提取音频(str(self.带音频), 最大输出字节=10)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超出限制")

    def test_提取音频格式不合法(self):
        结果 = 提取音频(str(self.带音频), 输出格式="exe")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_提取音频到指定输出路径(self):
        输出路径 = str(self.临时目录 / "输出.wav")
        结果 = 提取音频(str(self.带音频), 输出路径=输出路径)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(Path(输出路径).is_file())
        self.assertGreater(Path(输出路径).stat().st_size, 0)

    def test_转码真实成功且编码选项透传(self):
        结果 = 转码(str(self.带音频), 输出格式="mkv",
                 编码选项={"分辨率": "32x32", "帧率": "5"})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "mkv")
        self.assertGreater(结果.值["字节数"], 0)
        self.assertEqual(len(base64.b64decode(结果.值["字节b64"])), 结果.值["字节数"])

    def test_转码编码选项白名单拒绝非法键(self):
        结果 = 转码(str(self.带音频), 编码选项={"音量": "10"})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_转码格式不合法(self):
        结果 = 转码(str(self.带音频), 输出格式="exe")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_抽取帧真实jpg(self):
        结果 = 抽取帧(str(self.带音频), 0.5)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "jpg")
        self.assertGreater(结果.值["字节数"], 0)
        self.assertTrue(base64.b64decode(结果.值["字节b64"]).startswith(b"\xff\xd8"))

    def test_抽取帧png(self):
        结果 = 抽取帧(str(self.带音频), 0.5, 输出格式="png")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "png")

    def test_抽取帧时间点不合法(self):
        结果 = 抽取帧(str(self.带音频), -1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_探测超时错误码透传(self):
        挂起脚本 = self.临时目录 / "挂起探测.sh"
        挂起脚本.write_text("#!/bin/sh\nsleep 30\n")
        挂起脚本.chmod(0o755)
        with mock.patch("支持库.适配层.FFmpeg提供者.实现.探测.查找命令",
                        return_value=str(挂起脚本)):
            结果 = 探测媒体(str(self.带音频), 超时秒=0.3)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")

    def test_提取音频进程崩溃错误码透传(self):
        崩溃脚本 = self.临时目录 / "崩溃.sh"
        崩溃脚本.write_text("#!/bin/sh\nexit 3\n")
        崩溃脚本.chmod(0o755)
        真实查找 = __import__("支持库.适配层.FFmpeg提供者.实现.探测",
                            fromlist=["查找命令"]).查找命令

        def 假查找(命令名: str):
            return str(崩溃脚本) if 命令名 == "ffmpeg" else 真实查找(命令名)

        with mock.patch("支持库.适配层.FFmpeg提供者.实现.探测.查找命令",
                        side_effect=假查找):
            结果 = 提取音频(str(self.带音频))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "进程崩溃")

    def test_默认临时文件零残留(self):
        调用前 = _临时前缀集()
        提取音频(str(self.带音频))
        转码(str(self.带音频), 输出格式="mkv")
        抽取帧(str(self.带音频), 0.5)
        self.assertEqual(_临时前缀集(), 调用前)


class 测试注册能力(unittest.TestCase):
    def test_模块注册五个能力(self):
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        from 模块库.媒体处理 import 注册能力

        注册能力(注册表)
        self.assertEqual(len(注册表.条目), 5)
        self.assertEqual([条目.能力id for 条目 in 注册表.条目], [
            "媒体处理.检查提供者",
            "媒体处理.探测媒体",
            "媒体处理.提取音频",
            "媒体处理.转码",
            "媒体处理.抽取帧",
        ])
        for 条目 in 注册表.条目:
            self.assertEqual(条目.包id, "模块库.媒体处理")


if __name__ == "__main__":
    unittest.main()
