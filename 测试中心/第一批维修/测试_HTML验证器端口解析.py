"""#176 反向验证：监听端口解析必须取「已启动」那条，不能取首匹配。

缺陷态：`re.search(r"127\\.0\\.0\\.1:(\\d+)", 文本)` 取首匹配 ⇒ 制品启动期先打印
「连接网关 127.0.0.1:40007」时，会把网关端口当监听端口（功能性假绿）。
本文件先用缺陷态口径证明缺陷真实存在，再断言现口径取对。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 开发工具.HTML验证.制品进程 import _解析监听端口

#: 现场样本：先打印网关地址，再打印自己的监听地址（未完成事项 #176 原文场景）。
双行样本 = ("系统工程平台客户端 启动中\n"
            "连接网关 127.0.0.1:40007\n"
            "已启动 127.0.0.1:45080\n")


def _缺陷态首匹配(文本: str) -> int | None:
    """改前的口径（逐字复现原实现），仅供反向验证对照用。"""
    匹配 = re.search(r"127\.0\.0\.1:(\d+)", 文本)
    return int(匹配.group(1)) if 匹配 else None


class 测试监听端口解析(unittest.TestCase):
    def test_缺陷态确实取错端口(self) -> None:
        """先证明缺陷真实存在：缺陷态在同一段文本上取到的是网关端口 40007。"""
        self.assertEqual(_缺陷态首匹配(双行样本), 40007)

    def test_现口径取到真实监听端口(self) -> None:
        self.assertEqual(_解析监听端口(双行样本), 45080)

    def test_取最后匹配而非首匹配(self) -> None:
        self.assertEqual(_解析监听端口("127.0.0.1:40007\n127.0.0.1:45081\n"), 45081)

    def test_已启动锚点优先于裸端口(self) -> None:
        """「已启动」行在中间、其后还有别的回环地址时，仍取「已启动」那条。"""
        文本 = ("连接网关 127.0.0.1:40007\n"
                "已启动 127.0.0.1:45082\n"
                "连接网关 127.0.0.1:40007\n")
        self.assertEqual(_解析监听端口(文本), 45082)

    def test_单行正常输出(self) -> None:
        self.assertEqual(_解析监听端口("已启动 127.0.0.1:45083\n"), 45083)

    def test_无端口返回空(self) -> None:
        self.assertIsNone(_解析监听端口("启动中，还没有地址\n"))

    def test_空文本返回空(self) -> None:
        self.assertIsNone(_解析监听端口(""))


if __name__ == "__main__":
    unittest.main()
