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
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.能力调用.HTTP连接器 import HTTP连接器

PNG签名 = b"\x89PNG\r\n\x1a\n"

class 测试_文件内容扩充(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """启动真实后端和随机回环网关，所有测试请求走 HTTP。"""
        cls.后端 = 后端核心()
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 地址="127.0.0.1", 端口=0,
            配置={"请求超时秒": 1800, "要求凭证": False, "禁止客户端身份": False},
        )
        成功, 说明 = cls.网关.启动()
        if not 成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"网关启动失败: {说明}")

    @classmethod
    def tearDownClass(cls):
        cls.网关.优雅停止()
        cls.后端.优雅关闭()

    def setUp(self):
        self.临时根 = tempfile.mkdtemp(prefix="测试_文件内容扩充_")
        self.根目录 = Path(self.临时根)
        self.二进制文件 = self.根目录 / "图像.png"
        self.二进制文件.write_bytes(PNG签名 + b"\x00\x01\x02\x03" * 64)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时根, ignore_errors=True)

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
        原惰性装配 = _停用惰性装配()
        try:
            结果 = 读取文件(str(self.二进制文件))
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            _恢复惰性装配(原惰性装配)

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

def _停用惰性装配():
    """停用惰性装配钩子并返回原值（供「调用器不可用」用例使用）。

    2026-09-19（开工-20260919-193541-2a8e）：模块不再自持 `设置HTTP连接器`，
    只经 `获取能力调用器()` 取注入调用器。卸载调用器后若不**同时**停用惰性装配
    钩子，下一次获取会触发惰性装配把调用器装回来 —— 用例就测不到「不可用」分支。
    """
    from 公共契约.能力契约.调用器 import 设置惰性装配函数, 注册能力调用器
    原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
    设置惰性装配函数(None)
    注册能力调用器(None)
    return 原惰性装配


def _恢复惰性装配(原惰性装配) -> None:
    """还原惰性装配钩子并重新装配（后续用例不受影响）。"""
    from 公共契约.能力契约.调用器 import 设置惰性装配函数
    from 运行核心.能力调用.唯一能力调用 import 创建并绑定
    设置惰性装配函数(原惰性装配)
    创建并绑定()


if __name__ == "__main__":
    unittest.main()
