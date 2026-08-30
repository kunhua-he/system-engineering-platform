"""后端核心关闭必须回收资源句柄服务的全部线程数据库连接。"""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 后端核心.后端核心 import 后端核心


class 测试后端核心资源关闭(unittest.TestCase):
    def test_优雅关闭回收请求线程创建的全部权威状态连接(self) -> None:
        with tempfile.TemporaryDirectory(prefix="后端关闭回归_") as 临时目录:
            后端 = 后端核心(Path(临时目录))
            后端.状态.状态 = "运行中"

            def 读取状态() -> None:
                后端.资源句柄服务.权威状态.状态快照()

            线程表 = [threading.Thread(target=读取状态) for _ in range(6)]
            for 线程 in 线程表:
                线程.start()
            for 线程 in 线程表:
                线程.join(timeout=2)
                self.assertFalse(线程.is_alive())

            self.assertGreater(
                len(后端.资源句柄服务.权威状态._连接表), 1,
                "回归夹具必须真实建立多个请求线程连接",
            )
            关闭结果 = 后端.优雅关闭()

            self.assertTrue(关闭结果.成功, 关闭结果.错误说明)
            self.assertEqual(
                后端.资源句柄服务.权威状态._连接表, {},
                "后端已停止时不得残留权威状态SQLite连接",
            )
            self.assertEqual(后端.资源句柄服务.权威状态._连接线程表, {})


if __name__ == "__main__":
    unittest.main()
