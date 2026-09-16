"""密码签名提供者生命周期测试：超时/崩溃/重启/无残留清理。

子进程覆盖：执行超时→超时强杀；崩溃/非零退出→提供者崩溃；崩溃后
下一次调用重新启动（重启覆盖）；多次调用后无残留进程，等待并收集
能强制清理未退出子进程。能力往返测试见 测试_密码签名提供者.py。
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.运行时.平台适配 import 子进程组启动标志
from 支持库.适配层.密码签名提供者 import 生成密钥对, 签名
from 支持库.适配层.密码签名提供者.实现 import 提供者管理器 as 提供者模块


def _b64(数据: bytes) -> str:
    import base64
    return base64.b64encode(数据).decode("ascii")


def _崩溃子进程(退出码: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import os; os._exit({退出码})"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **子进程组启动标志(),
    )


def _关闭进程(进程: subprocess.Popen) -> None:
    try:
        进程.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    finally:
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            if 流:
                try:
                    流.close()
                except (OSError, ValueError):
                    pass


class Test密码签名提供者生命周期(unittest.TestCase):
    def test_超时返回超时(self):
        def 挂起执行(请求, 超时秒=提供者模块.默认超时秒):
            进程 = 提供者模块._启动子进程()
            try:
                进程.communicate(timeout=0.5)  # 不写请求行 → 子进程阻塞读 stdin
            except subprocess.TimeoutExpired:
                return 提供者模块._失败("超时", "模拟超时", 可重试=True)
            finally:
                提供者模块._终止进程组(进程)
            return 提供者模块._失败("超时", "模拟超时", 可重试=True)

        with mock.patch.object(提供者模块, "执行任务", side_effect=挂起执行):
            结果 = 生成密钥对()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)

    def test_子进程崩溃返回提供者崩溃(self):
        with mock.patch.object(提供者模块, "_启动子进程", side_effect=lambda: _崩溃子进程(7)), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            结果 = 生成密钥对()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者崩溃")
        self.assertTrue(结果.可重试)

    def test_重启恢复(self):
        原始启动 = 提供者模块._启动子进程
        调用计数 = {"n": 0}

        def 先崩后正常():
            调用计数["n"] += 1
            return _崩溃子进程(9) if 调用计数["n"] == 1 else 原始启动()

        with mock.patch.object(提供者模块, "_启动子进程", side_effect=先崩后正常), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            第一次 = 生成密钥对()
            第二次 = 生成密钥对()
        self.assertFalse(第一次.成功)
        self.assertEqual(第一次.错误码, "提供者崩溃")
        self.assertTrue(第二次.成功, 第二次.错误说明)

    def test_无残留进程(self):
        for _ in range(3):
            生成密钥对()
            签名(生成密钥对().值["私钥PEM"], _b64(b"x"))
        进程 = 提供者模块._启动子进程()
        self.assertIsNone(进程.poll())
        提供者模块.等待并收集([进程])
        self.assertIsNotNone(进程.poll())


if __name__ == "__main__":
    unittest.main()
