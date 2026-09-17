"""模块库.媒体处理 组合能力真实测试：经真实 HTTP 网关调用 FFmpeg 支持库能力。

覆盖：真实 ffmpeg 最小调用（检查提供者/探测媒体/提取音频/转码/抽取帧）、
损坏媒体/无音轨/超长媒体/超出限制等错误码透传、参数错误、平台不可用
（HTTP 连接器未装配如实返回 提供者不可用）、临时文件零残留、注册能力 5 项。

所有模块公开能力经 设置HTTP连接器 装配的 HTTP 连接器走 后端核心+本地网关，
不再走进程内唯一能力调用服务。
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.媒体处理 import 检查提供者, 探测媒体, 提取音频, 转码, 抽取帧
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.能力调用.HTTP连接器 import HTTP连接器

临时根 = Path(tempfile.gettempdir())


def 生成视频(路径: Path, 含音频: bool) -> Path:
    """用真实 ffmpeg 生成最小测试视频（testsrc 画面 + 可选 sine 音轨）。"""
    参数 = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=64x64:rate=10", "-t", "1"]
    if 含音频:
        参数 += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest"]
    参数 += ["-pix_fmt", "yuv420p", str(路径)]
    subprocess.run(参数, capture_output=True, check=True)
    return 路径


def 临时前缀集() -> set:
    return {条目 for 模式 in ("FFmpeg音频_*", "FFmpeg转码_*", "FFmpeg抽帧_*")
            for 条目 in 临时根.glob(模式)}


class 媒体处理装配(unittest.TestCase):
    """真实装配：启动 后端核心 + 本地网关，模块经 HTTP 连接器调用能力。"""

    @classmethod
    def setUpClass(cls):
        from 公共契约.能力契约.调用器 import 设置惰性装配函数
        cls.原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
        设置惰性装配函数(None)
        cls.后端 = 后端核心()
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 地址="127.0.0.1", 端口=0,
            # 请求超时秒 取平台口径 1800（运行核心/启动运行核心网关.py:44；本地网关默认同值）：
            # 10 会把能力契约声明的 超时秒=60/300 判成「超时时间超出允许范围」而全红。
            配置={"请求超时秒": 1800, "要求凭证": False, "禁止客户端身份": False},
        )
        成功, 说明 = cls.网关.启动()
        if not 成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"网关启动失败: {说明}")
        from 模块库.媒体处理 import 设置HTTP连接器
        设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=cls.网关.端口))

    @classmethod
    def tearDownClass(cls):
        from 模块库.媒体处理 import 设置HTTP连接器
        设置HTTP连接器(None)
        cls.网关.优雅停止()
        cls.后端.优雅关闭()
        from 公共契约.能力契约.调用器 import 设置惰性装配函数
        设置惰性装配函数(cls.原惰性装配)

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_媒体处理_"))
        self.可用 = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
        if self.可用:
            self.带音频 = 生成视频(self.临时目录 / "带音频.mp4", 含音频=True)
            self.纯视频 = 生成视频(self.临时目录 / "纯视频.mp4", 含音频=False)
            self.损坏文件 = self.临时目录 / "损坏.bin"
            self.损坏文件.write_bytes(os.urandom(4096))
            self.缺失路径 = str(self.临时目录 / "不存在.mp4")

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)


class Test检查提供者(媒体处理装配):
    def test_真实可用返回版本(self):
        结果 = 检查提供者()
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIn("ffmpeg", 结果.值["版本"])

    def test_超时秒参数不合法(self):
        for 值 in (0, -1, "不是数字"):
            结果 = 检查提供者(超时秒=值)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")

    def test_平台不可用如实返回(self):
        """卸载 HTTP 连接器后调用能力：模块返回 提供者不可用，不抛异常。"""
        from 模块库.媒体处理 import 设置HTTP连接器
        设置HTTP连接器(None)
        结果 = 检查提供者()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=self.网关.端口))

    def test_平台不可用时返回提供者不可用(self):
        """卸载连接器后调用能力：模块返回 提供者不可用，不抛异常（样板命名）。"""
        from 模块库.媒体处理 import 设置HTTP连接器
        设置HTTP连接器(None)
        结果 = 检查提供者()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=self.网关.端口))


class Test探测媒体(媒体处理装配):
    def setUp(self):
        super().setUp()
        if not self.可用:
            self.skipTest("ffmpeg/ffprobe 未配置（如实标记，不伪装可用）")

    def test_真实返回时长与流(self):
        结果 = 探测媒体(str(self.带音频))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertAlmostEqual(结果.值["时长秒"], 1.0, delta=0.5)
        流类型 = {流["类型"] for 流 in 结果.值["流"]}
        self.assertIn("video", 流类型)
        self.assertIn("audio", 流类型)
        self.assertTrue(结果.值["格式"])
        self.assertGreater(结果.值["大小字节"], 0)

    def test_损坏返回损坏媒体(self):
        结果 = 探测媒体(str(self.损坏文件))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "损坏媒体")

    def test_文件不存在(self):
        self.assertEqual(探测媒体(self.缺失路径).错误码, "文件不存在")

    def test_参数不合法(self):
        self.assertEqual(探测媒体("").错误码, "参数不合法")
        self.assertEqual(探测媒体(None).错误码, "参数不合法")


class Test提取音频(媒体处理装配):
    def setUp(self):
        super().setUp()
        if not self.可用:
            self.skipTest("ffmpeg/ffprobe 未配置（如实标记，不伪装可用）")

    def test_真实wav字节返回(self):
        结果 = 提取音频(str(self.带音频))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "wav")
        self.assertGreater(结果.值["字节数"], 0)
        self.assertEqual(len(base64.b64decode(结果.值["字节b64"])), 结果.值["字节数"])

    def test_mp3格式(self):
        结果 = 提取音频(str(self.带音频), 输出格式="mp3")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "mp3")

    def test_无音轨(self):
        结果 = 提取音频(str(self.纯视频))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "无音轨")

    def test_损坏媒体(self):
        结果 = 提取音频(str(self.损坏文件))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "损坏媒体")

    def test_超长媒体(self):
        结果 = 提取音频(str(self.带音频), 最大时长秒=0.001)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超长媒体")

    def test_超出限制(self):
        结果 = 提取音频(str(self.带音频), 最大输出字节=10)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超出限制")

    def test_格式不合法(self):
        结果 = 提取音频(str(self.带音频), 输出格式="exe")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_输出到指定路径(self):
        输出路径 = str(self.临时目录 / "输出.wav")
        结果 = 提取音频(str(self.带音频), 输出路径=输出路径)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(Path(输出路径).is_file())
        self.assertGreater(Path(输出路径).stat().st_size, 0)


class Test转码(媒体处理装配):
    def setUp(self):
        super().setUp()
        if not self.可用:
            self.skipTest("ffmpeg/ffprobe 未配置（如实标记，不伪装可用）")

    def test_真实成功且编码选项透传(self):
        结果 = 转码(str(self.带音频), 输出格式="mkv",
                 编码选项={"分辨率": "32x32", "帧率": "5"})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "mkv")
        self.assertGreater(结果.值["字节数"], 0)
        self.assertEqual(len(base64.b64decode(结果.值["字节b64"])), 结果.值["字节数"])

    def test_编码选项白名单拒绝非法键(self):
        结果 = 转码(str(self.带音频), 编码选项={"音量": "10"})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_格式不合法(self):
        结果 = 转码(str(self.带音频), 输出格式="exe")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


class Test抽取帧(媒体处理装配):
    def setUp(self):
        super().setUp()
        if not self.可用:
            self.skipTest("ffmpeg/ffprobe 未配置（如实标记，不伪装可用）")

    def test_真实jpg(self):
        结果 = 抽取帧(str(self.带音频), 0.5)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "jpg")
        self.assertGreater(结果.值["字节数"], 0)
        self.assertTrue(base64.b64decode(结果.值["字节b64"]).startswith(b"\xff\xd8"))
        self.assertGreater(结果.值["宽度"], 0)
        self.assertGreater(结果.值["高度"], 0)

    def test_png(self):
        结果 = 抽取帧(str(self.带音频), 0.5, 输出格式="png")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "png")

    def test_时间点不合法(self):
        结果 = 抽取帧(str(self.带音频), -1)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


class Test零残留与注册(unittest.TestCase):
    """独立网关装配：残留测试与注册测试不依赖 媒体处理装配 的视频夹具。"""

    @classmethod
    def setUpClass(cls):
        cls.后端 = 后端核心()
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 地址="127.0.0.1", 端口=0,
            # 请求超时秒 取平台口径 1800（运行核心/启动运行核心网关.py:44；本地网关默认同值）：
            # 10 会把能力契约声明的 超时秒=60/300 判成「超时时间超出允许范围」而全红。
            配置={"请求超时秒": 1800, "要求凭证": False, "禁止客户端身份": False},
        )
        成功, 说明 = cls.网关.启动()
        if not 成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"网关启动失败: {说明}")
        from 模块库.媒体处理 import 设置HTTP连接器
        设置HTTP连接器(HTTP连接器(网关地址="127.0.0.1", 网关端口=cls.网关.端口))

    @classmethod
    def tearDownClass(cls):
        from 模块库.媒体处理 import 设置HTTP连接器
        设置HTTP连接器(None)
        cls.网关.优雅停止()
        cls.后端.优雅关闭()

    def test_默认临时文件零残留(self):
        from 公共契约.能力契约.调用器 import 设置惰性装配函数

        原惰性 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
        设置惰性装配函数(None)
        try:
            if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
                self.skipTest("ffmpeg/ffprobe 未配置（如实标记，不伪装可用）")
            临时目录 = Path(tempfile.mkdtemp(prefix="测试_媒体处理残留_"))
            try:
                视频 = 生成视频(临时目录 / "残留.mp4", 含音频=True)
                调用前 = 临时前缀集()
                提取音频(str(视频))
                转码(str(视频), 输出格式="mkv")
                抽取帧(str(视频), 0.5)
                self.assertEqual(临时前缀集(), 调用前)
            finally:
                shutil.rmtree(临时目录, ignore_errors=True)
        finally:
            设置惰性装配函数(原惰性)

    def test_模块注册六个能力(self):
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        from 模块库.媒体处理 import 注册能力

        注册能力(注册表)
        self.assertEqual(len(注册表.条目), 6)
        self.assertEqual([条目.能力id for 条目 in 注册表.条目], [
            "媒体处理.检查提供者",
            "媒体处理.探测媒体",
            "媒体处理.提取音频",
            "媒体处理.拼接媒体",
            "媒体处理.转码",
            "媒体处理.抽取帧",
        ])
        for 条目 in 注册表.条目:
            self.assertEqual(条目.包id, "模块库.媒体处理")


if __name__ == "__main__":
    unittest.main()
