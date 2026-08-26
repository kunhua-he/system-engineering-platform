"""模块库.文件管理 文件内容扩充能力真实测试。

覆盖：受控二进制读取（真实读回/路径越界/超大拒绝/文件不存在）、
头部读取（PNG 头断言）、流式摘要（3MB+ 大文件与 sha256 全量对比）、
平台不可用降级（提供者不可用）、既有能力回归（读取/写入/复制/移动/删除/列出）。
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.文件管理 import (
    删除文件,
    复制文件,
    读取文件,
    读取二进制文件,
    读取文件头部字节,
    流式创建摘要,
    列出文件,
    移动文件,
    写入文件,
)

PNG签名 = b"\x89PNG\r\n\x1a\n"


def _装配调用器() -> None:
    """真实装配：注册文件系统与资源管理支持库能力并注入唯一能力调用服务。"""
    from 公共契约.能力契约.契约 import 能力注册表
    from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
    from 支持库.后端.文件系统支持库.文件操作 import 注册能力 as 注册文件系统
    from 支持库.后端.系统核心支持库.资源管理 import 注册能力 as 注册资源管理

    注册表 = 能力注册表()
    注册文件系统(注册表)
    注册资源管理(注册表)
    设置全局唯一服务(唯一能力调用服务(注册表))


def _卸载调用器() -> None:
    from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务

    设置全局唯一服务(None)


class 测试_文件内容扩充(unittest.TestCase):
    def setUp(self):
        _装配调用器()
        self.临时根 = tempfile.mkdtemp(prefix="测试_文件内容扩充_")
        self.根目录 = Path(self.临时根)
        self.二进制文件 = self.根目录 / "图像.png"
        self.二进制文件.write_bytes(PNG签名 + b"\x00\x01\x02\x03" * 64)

    def tearDown(self):
        _卸载调用器()

    def test_受控二进制读取真实读回(self):
        结果 = 读取二进制文件(self.临时根, "图像.png", 0)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, PNG签名 + b"\x00\x01\x02\x03" * 64)

    def test_受控二进制读取路径越界拒绝(self):
        结果 = 读取二进制文件(self.临时根, "../越界.bin", 0)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")

    def test_受控二进制读取超大拒绝(self):
        结果 = 读取二进制文件(self.临时根, "图像.png", 4)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件超限")

    def test_受控二进制读取文件不存在(self):
        结果 = 读取二进制文件(self.临时根, "缺失.bin", 0)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_头部读取PNG头(self):
        结果 = 读取文件头部字节(self.临时根, "图像.png", 8)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, PNG签名)

    def test_头部读取自定义字节数(self):
        结果 = 读取文件头部字节(self.临时根, "图像.png", 4)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, PNG签名[:4])

    def test_头部读取路径越界拒绝(self):
        结果 = 读取文件头部字节(self.临时根, "../越界.bin", 8)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")

    def test_平台不可用时返回提供者不可用(self):
        """卸载调用器后调用能力：模块返回 提供者不可用，不抛异常。"""
        _卸载调用器()
        结果 = 读取文件(str(self.二进制文件))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        _装配调用器()

    def test_流式摘要大文件分块(self):
        大文件 = self.根目录 / "大文件.bin"
        内容 = bytes(range(256)) * (3 * 1024 * 1024 // 256 + 512)
        大文件.write_bytes(内容)
        期望 = hashlib.sha256(内容).hexdigest()
        结果 = 流式创建摘要(str(大文件))
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, 期望)

    def test_流式摘要文件不存在(self):
        结果 = 流式创建摘要(str(self.根目录 / "缺失.bin"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_既有能力回归(self):
        文本 = self.根目录 / "回归.txt"
        self.assertTrue(写入文件(str(文本), "回归内容").成功)
        self.assertEqual(读取文件(str(文本)).值, "回归内容")
        副本 = self.根目录 / "回归副本.txt"
        self.assertTrue(复制文件(str(文本), str(副本)).成功)
        移动目标 = self.根目录 / "回归移动.txt"
        self.assertTrue(移动文件(str(副本), str(移动目标)).成功)
        self.assertFalse(读取文件(str(副本)).成功)
        self.assertEqual(读取文件(str(移动目标)).值, "回归内容")
        列表结果 = 列出文件(self.临时根)
        self.assertTrue(列表结果.成功)
        self.assertIn("回归.txt", 列表结果.值)
        self.assertIn("回归移动.txt", 列表结果.值)
        self.assertTrue(删除文件(str(文本)).成功)
        self.assertFalse(读取文件(str(文本)).成功)


if __name__ == "__main__":
    unittest.main()
