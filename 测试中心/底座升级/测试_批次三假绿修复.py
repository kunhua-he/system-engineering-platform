"""批次三回归：代理端口隔离与门禁进程组回收。"""

from __future__ import annotations

import sys
import unittest


class Test批次三假绿修复(unittest.TestCase):
    def test_4780是应用保留端口(self):
        from 公共契约.运行时.端口策略 import 校验应用监听端口

        with self.assertRaises(ValueError):
            校验应用监听端口(4780)
        校验应用监听端口(45090)
        校验应用监听端口(0)

    def test_本地网关拒绝4780(self):
        from 运行核心.统一网关.本地网关 import 本地网关服务器

        服务器 = 本地网关服务器(网关核心实例=object(), 端口=4780)
        成功, 消息 = 服务器.启动()
        self.assertFalse(成功)
        self.assertIn("保留端口", 消息)

    def test_流式网关拒绝4780(self):
        from 运行核心.统一网关.传输.流式HTTP import 流式HTTP服务器

        成功, 消息 = 流式HTTP服务器(端口=4780).启动()
        self.assertFalse(成功)
        self.assertIn("保留端口", 消息)

    def test_门禁超时返回失败并不留下子进程(self):
        from 开发工具.发布门禁.运行发布门禁 import 运行子进程

        退出码, 输出 = 运行子进程(
            [sys.executable, "-c", "import time; time.sleep(30)"], 超时秒=0.1)
        self.assertNotEqual(退出码, 0)
        self.assertIn("超时", 输出)


if __name__ == "__main__":
    unittest.main()
