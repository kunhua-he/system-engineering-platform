"""Pillow 提供者测试：真实解码/像素统计/占位图 + 损坏/伪装/超大/超时/崩溃/不可用/零残留。
架构验证：主进程不加载 PIL；子进程覆盖启动/调用/超时/崩溃/重启/停止与残留清理；
提供者不可用走环境变量依赖注入。
"""
from __future__ import annotations

import base64
import os
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.Pillow提供者 import 解码图像, 像素统计, 生成占位图
from 支持库.适配层.Pillow提供者.实现 import 提供者 as 提供者模块

最小PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
最小JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q==")


def _大像素PNG(宽度: int, 高度: int) -> bytes:
    """手工构造只声明尺寸的 PNG（头完整、无数据），用于像素超限判定。"""
    头 = b"\x89PNG\r\n\x1a\n"
    IHDR数据 = struct.pack(">IIBBBBB", 宽度, 高度, 8, 2, 0, 0, 0)
    IHDR = (struct.pack(">I", len(IHDR数据)) + b"IHDR" + IHDR数据
            + struct.pack(">I", zlib.crc32(b"IHDR" + IHDR数据)))
    IEND = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return 头 + IHDR + IEND


def _退出子进程(码: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import os; os._exit({码})"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )


def _关闭进程(进程: subprocess.Popen) -> None:
    try:
        进程.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
        if 流:
            try:
                流.close()
            except (OSError, ValueError):
                pass


class TestPillow提供者(unittest.TestCase):
    def test_主进程不加载PIL(self):
        self.assertNotIn("PIL", sys.modules)
        解码图像(最小PNG)
        self.assertNotIn("PIL", sys.modules)

    def test_解码图像PNG正常(self):
        结果 = 解码图像(最小PNG)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, {"格式": "PNG", "宽度": 1, "高度": 1, "模式": "RGBA"})

    def test_解码图像JPEG正常(self):
        结果 = 解码图像(最小JPEG)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "JPEG")
        self.assertEqual(结果.值["宽度"], 1)

    def test_解码图像格式伪装返回格式未知(self):
        结果 = 解码图像("这不是图像内容，只是普通文本伪装成图像".encode("utf-8"))
        self.assertEqual(结果.错误码, "格式未知")

    def test_解码图像损坏返回文件损坏(self):
        结果 = 解码图像(最小PNG[:44])  # 头完整但 IDAT 数据截断
        self.assertEqual(结果.错误码, "文件损坏")

    def test_解码图像像素超大返回超大(self):
        结果 = 解码图像(_大像素PNG(8000, 8000))
        self.assertEqual(结果.错误码, "超大")

    def test_解码图像字节超大返回超大(self):
        结果 = 解码图像(b"\x89PNG" + b"x" * (提供者模块.输入字节上限 + 1))
        self.assertEqual(结果.错误码, "超大")

    def test_解码图像非法参数(self):
        self.assertEqual(解码图像(b"").错误码, "参数不合法")
        self.assertEqual(解码图像("文本").错误码, "参数不合法")

    def test_像素统计纯色精确(self):
        占位 = 生成占位图(4, 4, "纯色", 背景颜色="#123456")
        self.assertTrue(占位.成功, 占位.错误说明)
        结果 = 像素统计(base64.b64decode(占位.值["图像b64"]))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["宽度"], 4)
        self.assertEqual(结果.值["高度"], 4)
        self.assertEqual(结果.值["像素数"], 16)
        self.assertEqual(结果.值["平均颜色"], {"红": 18, "绿": 52, "蓝": 86})

    def test_像素统计超大返回超大(self):
        结果 = 像素统计(_大像素PNG(6000, 6000))
        self.assertEqual(结果.错误码, "超大")

    def test_生成占位图纯色可解码(self):
        结果 = 生成占位图(64, 32, "纯色", 背景颜色="#FF8800")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["格式"], "PNG")
        self.assertEqual((结果.值["宽度"], 结果.值["高度"]), (64, 32))
        图像字节 = base64.b64decode(结果.值["图像b64"])
        self.assertTrue(图像字节.startswith(b"\x89PNG"))
        解码 = 解码图像(图像字节)
        self.assertTrue(解码.成功, 解码.错误说明)
        self.assertEqual(解码.值["格式"], "PNG")

    def test_生成占位图渐变颜色区间(self):
        结果 = 生成占位图(64, 64, "渐变", 前景颜色="#FF0000", 背景颜色="#0000FF")
        self.assertTrue(结果.成功, 结果.错误说明)
        统计 = 像素统计(base64.b64decode(结果.值["图像b64"]))
        self.assertTrue(统计.成功, 统计.错误说明)
        平均 = 统计.值["平均颜色"]
        self.assertGreater(平均["红"], 100)
        self.assertGreater(平均["蓝"], 100)
        self.assertLess(平均["红"], 200)
        self.assertLess(平均["蓝"], 200)
        self.assertEqual(平均["绿"], 0)

    def test_生成占位图文本(self):
        结果 = 生成占位图(300, 150, "文本", 文本="TEST")
        self.assertTrue(结果.成功, 结果.错误说明)
        解码 = 解码图像(base64.b64decode(结果.值["图像b64"]))
        self.assertTrue(解码.成功, 解码.错误说明)
        self.assertEqual((解码.值["宽度"], 解码.值["高度"]), (300, 150))

    def test_生成占位图非法参数(self):
        self.assertEqual(生成占位图(8, 8, "动画").错误码, "参数不合法")
        self.assertEqual(生成占位图(0, 8, "纯色").错误码, "参数不合法")
        self.assertEqual(生成占位图(8, 8, "纯色", 背景颜色="red").错误码, "参数不合法")

    def test_生成占位图超大返回超大(self):
        结果 = 生成占位图(7000, 7000, "纯色")
        self.assertEqual(结果.错误码, "超大")

    def test_超时返回超时(self):
        def 挂起执行(请求, 超时秒=提供者模块.默认超时秒):
            进程 = 提供者模块._启动子进程()
            try:
                进程.communicate(timeout=0.5)  # 不发请求 → 子进程阻塞 → 真实超时
            except subprocess.TimeoutExpired:
                return 提供者模块._失败("超时", "模拟超时", 可重试=True)
            finally:
                提供者模块._终止进程组(进程)
                for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
                    if 流:
                        流.close()
            return 提供者模块._失败("超时", "模拟超时", 可重试=True)
        with mock.patch.object(提供者模块, "执行任务", side_effect=挂起执行):
            结果 = 解码图像(最小PNG)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)

    def test_子进程崩溃返回提供者崩溃(self):
        with mock.patch.object(提供者模块, "_启动子进程", side_effect=lambda: _退出子进程(7)), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            结果 = 解码图像(最小PNG)
        self.assertEqual(结果.错误码, "提供者崩溃")
        self.assertTrue(结果.可重试)

    def test_重启恢复(self):
        原始启动 = 提供者模块._启动子进程
        计数 = {"n": 0}

        def 先崩后正常():
            计数["n"] += 1
            return _退出子进程(9) if 计数["n"] == 1 else 原始启动()
        with mock.patch.object(提供者模块, "_启动子进程", side_effect=先崩后正常), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            第一次 = 解码图像(最小PNG)
            第二次 = 解码图像(最小PNG)
        self.assertEqual(第一次.错误码, "提供者崩溃")
        self.assertTrue(第二次.成功, 第二次.错误说明)

    def test_提供者不可用(self):
        with mock.patch.dict(os.environ, {"Pillow提供者_禁用库": "PIL"}):
            结果 = 解码图像(最小PNG)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertTrue(结果.可重试)

    def test_无残留与停止清理(self):
        for _ in range(3):
            解码图像(最小PNG)
        进程 = 提供者模块._启动子进程()
        self.assertIsNone(进程.poll())
        提供者模块.等待并收集([进程])
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            if 流:
                流.close()
        self.assertIsNotNone(进程.poll())


if __name__ == "__main__":
    unittest.main()
