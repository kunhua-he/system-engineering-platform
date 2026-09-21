"""公共有界 IO 读取器测试：精确上限、超限截断和持续排空。"""

from __future__ import annotations

import io
import subprocess
import sys
import unittest

from 公共契约.运行时.有界IO import 受限读取, 受限通信
from 公共契约.运行时.平台适配 import 子进程组启动标志
from 公共契约.运行时.进程终止 import 终止进程组


class 有界IO测试(unittest.TestCase):
    def test_精确达到上限不算超限(self) -> None:
        内容, 超限 = 受限读取(io.BytesIO(b"12345"), 5, 块大小=2)
        self.assertEqual(内容, b"12345")
        self.assertFalse(超限)

    def test_超限只保留上限并触发一次回调(self) -> None:
        事件: list[str] = []
        内容, 超限 = 受限读取(
            io.BytesIO(b"123456789"), 5, 块大小=2,
            超限回调=lambda: 事件.append("超限"),
        )
        self.assertEqual(内容, b"12345")
        self.assertTrue(超限)
        self.assertEqual(事件, ["超限"])

    def test_数据回调收到完整流且返回内容有界(self) -> None:
        数据: list[bytes] = []
        内容, 超限 = 受限读取(
            io.BytesIO(b"abcdefgh"), 3, 块大小=2,
            数据回调=数据.append,
        )
        self.assertEqual(b"".join(数据), b"abcdefgh")
        self.assertEqual(内容, b"abc")
        self.assertTrue(超限)
    def _终止(self, 进程: subprocess.Popen) -> None:
        if 进程.poll() is not None:
            return
        # 平台差异收口在 公共契约.运行时.进程终止（Windows 走 taskkill 整树）
        终止进程组(进程.pid, 信号="强杀")
        进程.wait(timeout=5)

    def test_受限通信支持输入和双管道(self) -> None:
        进程 = subprocess.Popen(
            [sys.executable, "-c", "import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(d); sys.stderr.buffer.write(b'err')"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **子进程组启动标志(),
        )
        输出, 错误, 超时, 超限 = 受限通信(
            进程, 输入=b"hello", 超时秒=5,
            终止回调=lambda: self._终止(进程),
        )
        self.assertEqual(输出, b"hello")
        self.assertEqual(错误, b"err")
        self.assertFalse(超时)
        self.assertFalse(超限)

    def test_受限通信超限时回收进程组(self) -> None:
        进程 = subprocess.Popen(
            [sys.executable, "-c", "import sys,time; sys.stdout.write('x'*300000); sys.stdout.flush(); time.sleep(30)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **子进程组启动标志(),
        )
        输出, _错误, _超时, 超限 = 受限通信(
            进程, 超时秒=5, 输出上限字节=1024,
            终止回调=lambda: self._终止(进程),
        )
        self.assertTrue(超限)
        self.assertLessEqual(len(输出), 1024)
        self.assertIn(进程.poll(), (-9, -15), "超限后必须已回收进程组（强杀/终止信号）")

    def test_受限通信超时时回收进程组(self) -> None:
        进程 = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **子进程组启动标志(),
        )
        _输出, _错误, 超时, _超限 = 受限通信(
            进程, 超时秒=0.1,
            终止回调=lambda: self._终止(进程),
        )
        self.assertTrue(超时)
        self.assertIn(进程.poll(), (-9, -15), "超时后必须已回收进程组（强杀/终止信号）")


if __name__ == "__main__":
    unittest.main()
