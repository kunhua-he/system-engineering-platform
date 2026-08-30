"""进程管理：启动能力必须可原子等待本地端口就绪。"""
from __future__ import annotations

import socket
import sys
import tempfile
import unittest

from 支持库.后端.系统核心支持库.进程管理 import 启动进程, 释放句柄


class 测试进程就绪等待(unittest.TestCase):
    def test_启动成功时端口已经可连接(self) -> None:
        with socket.socket() as 探针:
            探针.bind(("127.0.0.1", 0))
            端口 = 探针.getsockname()[1]
        with tempfile.TemporaryDirectory() as 工作目录:
            结果 = 启动进程(
                命令=sys.executable,
                参数=["-m", "http.server", str(端口), "--bind", "127.0.0.1"],
                工作目录=工作目录,
                就绪地址=f"127.0.0.1:{端口}",
                就绪超时秒=5.0,
            )
            self.assertTrue(结果.成功, 结果.错误说明)
            句柄 = 结果.值["句柄"]
            try:
                with socket.create_connection(("127.0.0.1", 端口), timeout=1):
                    pass
            finally:
                self.assertTrue(释放句柄(句柄).成功)


if __name__ == "__main__":
    unittest.main()
