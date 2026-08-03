"""FFmpeg 提供者测试：真实 ffprobe/ffmpeg 探测、抽取、转码、抽帧 + 超时/取消/
崩溃/截断/零残留；ffmpeg 不可用时如实标记跳过并断言 未配置 语义。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.FFmpeg提供者 import 检查提供者, 探测媒体, 提取音频, 转码, 抽取帧
from 支持库.适配层.FFmpeg提供者.实现 import 进程管理 as 进程模块
from 支持库.适配层.FFmpeg提供者.实现 import 探测 as 探测模块
from 支持库.适配层.FFmpeg提供者.实现 import 处理 as 处理模块


def _生成视频(路径: Path, 含音频: bool, 尺寸: str = "64x64") -> Path:
    参数 = [探测模块.查找命令("ffmpeg"), "-y", "-f", "lavfi", "-i",
            f"testsrc=size={尺寸}:rate=10", "-t", "1"]
    if 含音频:
        参数 += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest"]
    参数 += ["-pix_fmt", "yuv420p", str(路径)]
    subprocess.run(参数, capture_output=True, check=True)
    return 路径


def _生成纯音频(路径: Path) -> Path:
    参数 = [探测模块.查找命令("ffmpeg"), "-y", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=1", str(路径)]
    subprocess.run(参数, capture_output=True, check=True)
    return 路径


def _写脚本(路径: Path, 内容: str) -> str:
    路径.write_text(内容)
    os.chmod(路径, 0o755)
    return str(路径)


def _临时前缀集(临时根: Path) -> set:
    return {项 for 模式 in ("FFmpeg音频_*", "FFmpeg转码_*", "FFmpeg抽帧_*")
            for 项 in 临时根.glob(模式)}


class Test未配置语义(unittest.TestCase):
    def test_未配置提供者返回提供者不可用(self):
        with mock.patch.object(探测模块, "查找命令", return_value=None):
            结果 = 检查提供者()
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertIn("未配置", 结果.错误说明)


class TestFFmpeg提供者(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.临时目录 = Path(tempfile.mkdtemp(prefix="测试_FFmpeg提供者_"))
        cls.可用 = 探测模块.查找命令("ffmpeg") is not None and 探测模块.查找命令("ffprobe") is not None
        if cls.可用:
            cls.带音频 = _生成视频(cls.临时目录 / "带音频.mp4", 含音频=True)
            cls.纯视频 = _生成视频(cls.临时目录 / "纯视频.mp4", 含音频=False)
            cls.标清视频 = _生成视频(cls.临时目录 / "标清.mp4", 含音频=False, 尺寸="320x240")
            cls.低清视频 = _生成视频(cls.临时目录 / "低清.mp4", 含音频=False, 尺寸="160x120")
            cls.纯音频 = _生成纯音频(cls.临时目录 / "纯音频.wav")
            cls.损坏文件 = cls.临时目录 / "损坏.bin"
            cls.损坏文件.write_bytes(os.urandom(4096))
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.临时目录, ignore_errors=True)

    def setUp(self):
        if not self.可用:
            self.skipTest("ffmpeg/ffprobe 未配置（如实标记，不伪装可用）")

    def test_检查提供者可用(self):
        结果 = 检查提供者()
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIn("8.1", 结果.值["版本"]["ffprobe"])

    def test_探测媒体真实(self):
        结果 = 探测媒体(str(self.带音频))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertAlmostEqual(结果.值["时长秒"], 1.0, delta=0.5)
        self.assertIn("video", {流["类型"] for 流 in 结果.值["流"]})

    def test_探测媒体损坏返回损坏媒体(self):
        self.assertEqual(探测媒体(str(self.损坏文件)).错误码, "损坏媒体")

    def test_提取音频成功(self):
        结果 = 提取音频(str(self.带音频))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "wav")
        self.assertGreater(结果.值["字节数"], 0)

    def test_提取音频无音轨(self):
        self.assertEqual(提取音频(str(self.纯视频)).错误码, "无音轨")

    def test_提取音频超长媒体(self):
        self.assertEqual(提取音频(str(self.带音频), 最大时长秒=0.001).错误码, "超长媒体")

    def test_提取音频格式不合法(self):
        self.assertEqual(提取音频(str(self.带音频), 输出格式="exe").错误码, "参数不合法")

    def test_转码成功(self):
        结果 = 转码(str(self.带音频), 输出格式="mkv")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "mkv")

    def test_抽取帧成功(self):
        结果 = 抽取帧(str(self.带音频), 0.5)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "jpg")
        self.assertGreater(结果.值["字节数"], 0)
        self.assertIn("宽度", 结果.值)
        self.assertIn("高度", 结果.值)

    def test_抽取帧真实尺寸匹配(self):
        结果 = 抽取帧(str(self.标清视频), 0.5)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["宽度"], 320)
        self.assertEqual(结果.值["高度"], 240)

    def test_抽取帧尺寸随源真实变化(self):
        高结果 = 抽取帧(str(self.标清视频), 0.5)
        低结果 = 抽取帧(str(self.低清视频), 0.5)
        self.assertTrue(高结果.成功 and 低结果.成功,
                        f"高={高结果.错误说明} 低={低结果.错误说明}")
        self.assertEqual((高结果.值["宽度"], 高结果.值["高度"]), (320, 240))
        self.assertEqual((低结果.值["宽度"], 低结果.值["高度"]), (160, 120))
        self.assertNotEqual(
            (高结果.值["宽度"], 高结果.值["高度"]),
            (低结果.值["宽度"], 低结果.值["高度"]),
            "不同尺寸源视频的抽帧宽高必须不同（禁止固定值）")

    def test_抽取帧损坏媒体(self):
        self.assertEqual(抽取帧(str(self.损坏文件), 0.5).错误码, "损坏媒体")

    def test_抽取帧非视频如实失败(self):
        结果 = 抽取帧(str(self.纯音频), 0.5)
        self.assertFalse(结果.成功, "非视频媒体抽帧必须如实失败")
        self.assertEqual(结果.错误码, "进程崩溃")

    def test_抽取帧程序缺失(self):
        with mock.patch.object(探测模块, "查找命令", return_value=None):
            结果 = 抽取帧(str(self.带音频), 0.5)
        self.assertEqual(结果.错误码, "提供者不可用")

    def test_抽取帧超时(self):
        挂起脚本 = _写脚本(self.临时目录 / "挂起抽帧.sh", "#!/bin/sh\nsleep 30\n")
        真实ffprobe = 探测模块.查找命令("ffprobe")

        def 假查找(命令名: str):
            return 挂起脚本 if 命令名 == "ffmpeg" else 真实ffprobe

        with mock.patch.object(探测模块, "查找命令", side_effect=假查找):
            结果 = 抽取帧(str(self.带音频), 0.5, 超时秒=0.3)
        self.assertEqual(结果.错误码, "超时")

    def test_抽取帧取消透传(self):
        探测输出 = json.dumps({
            "format": {"duration": "1.0", "format_name": "mp4", "size": "1000", "bit_rate": "8000"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264",
                         "width": 320, "height": 240, "sample_rate": None, "channels": None}],
        }).encode()

        def 假执行(命令列表, *, 超时秒, 最大输出字节, 取消函数=None):
            if "ffmpeg" in " ".join(命令列表):
                return 进程模块.受管结果(成功=False, 错误码="取消", 错误摘要="取消: 外部命令执行被终止")
            return 进程模块.受管结果(成功=True, 退出码=0, 标准输出=探测输出)

        with mock.patch.object(探测模块, "执行受管命令", side_effect=假执行), \
                mock.patch.object(处理模块, "执行受管命令", side_effect=假执行):
            结果 = 抽取帧(str(self.带音频), 0.5)
        self.assertEqual(结果.错误码, "取消")
        self.assertFalse(结果.可重试)

    def test_输出超出限制(self):
        self.assertEqual(提取音频(str(self.带音频), 最大输出字节=10).错误码, "超出限制")

    def test_探测超时(self):
        挂起脚本 = _写脚本(self.临时目录 / "挂起探测.sh", "#!/bin/sh\nsleep 30\n")
        with mock.patch.object(探测模块, "查找命令", return_value=挂起脚本):
            结果 = 探测媒体(str(self.带音频), 超时秒=0.3)
        self.assertEqual(结果.错误码, "超时")

    def test_转码进程崩溃(self):
        崩溃脚本 = _写脚本(self.临时目录 / "崩溃.sh", "#!/bin/sh\nexit 3\n")
        真实ffprobe = 探测模块.查找命令("ffprobe")

        def 假查找(命令名: str):
            return 崩溃脚本 if 命令名 == "ffmpeg" else 真实ffprobe

        with mock.patch.object(探测模块, "查找命令", side_effect=假查找):
            结果 = 转码(str(self.带音频))
        self.assertEqual(结果.错误码, "进程崩溃")
        self.assertTrue(结果.可重试)

    def test_取消killpg无残留(self):
        挂起脚本 = _写脚本(self.临时目录 / "挂起.sh", "#!/bin/sh\nsleep 30\n")
        标志 = {"取消": False}
        threading.Timer(0.3, lambda: 标志.update(取消=True)).start()
        结果 = 进程模块.执行受管命令([挂起脚本], 超时秒=10,
                                 最大输出字节=1024,
                                 取消函数=lambda: 标志["取消"])
        self.assertEqual(结果.错误码, "取消")
        with self.assertRaises(ProcessLookupError):
            os.killpg(结果.进程组id, 0)

    def test_输出上限截断(self):
        刷屏脚本 = _写脚本(self.临时目录 / "刷屏.sh",
                      "#!/bin/sh\ni=0; while [ $i -lt 10000 ]; "
                      "do echo 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'; i=$((i+1)); done\n")
        结果 = 进程模块.执行受管命令([刷屏脚本], 超时秒=10, 最大输出字节=256)
        self.assertTrue(结果.成功)
        self.assertTrue(结果.输出截断)
        self.assertLessEqual(len(结果.标准输出), 256)

    def test_临时文件零残留(self):
        临时根 = Path(tempfile.gettempdir())
        前缀集 = _临时前缀集(临时根)
        提取音频(str(self.带音频))
        转码(str(self.带音频), 输出格式="mkv")
        抽取帧(str(self.带音频), 0.5)
        抽取帧(str(self.标清视频), 0.5)
        抽取帧(str(self.低清视频), 0.5)
        抽取帧(str(self.纯音频), 0.5)
        提取音频(str(self.损坏文件))
        self.assertEqual(_临时前缀集(临时根), 前缀集)


