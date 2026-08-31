"""模型连接与并发资源释放终态测试。

只覆盖本轮新增边界：回调锁外执行、未收敛保留账本、线程池释放有界等待。
"""
from __future__ import annotations

import time
import unittest
from pathlib import Path

import sys

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.并发控制支持库.实现 import 并发控制
from 支持库.后端.大语言模型支持库.模型连接器.实现 import 模型连接器


class 测试模型连接器释放(unittest.TestCase):
    """验证模型句柄在释放失败时不丢失真实资源账本。"""

    def setUp(self) -> None:
        模型连接器.连接表.clear()
        模型连接器.全局模型索引.clear()
        模型连接器.本地进程表.clear()

    def tearDown(self) -> None:
        模型连接器.连接表.clear()
        模型连接器.全局模型索引.clear()
        模型连接器.本地进程表.clear()

    def _创建连接(self) -> int:
        结果 = 模型连接器._登记连接(
            "LLM", {"模型名": "测试模型", "部署形态": "云端"},
            超时秒=1,
        )
        self.assertTrue(结果.成功, 结果.错误说明)
        return 结果.值["句柄"]

    def test_过期回调在锁外执行并成功收口(self) -> None:
        句柄 = self._创建连接()
        连接器 = 模型连接器.连接表[句柄]
        连接器["最后活动时间"] = time.time() - 10
        回调记录: list[bool] = []

        def 释放回调(句柄id: int) -> bool:
            已取得 = 模型连接器.锁.acquire(blocking=False)
            回调记录.append(已取得)
            if 已取得:
                模型连接器.锁.release()
            return True

        连接器["释放函数"] = 释放回调
        模型连接器._回收过期句柄()
        self.assertEqual(回调记录, [True], "释放回调必须在全局锁外执行")
        self.assertNotIn(句柄, 模型连接器.连接表)
        self.assertEqual(模型连接器.查询句柄状态(句柄).值["状态"], "已失效")

    def test_释放失败保留账本并允许重试(self) -> None:
        句柄 = self._创建连接()
        尝试次数 = 0

        def 释放回调(句柄id: int) -> bool:
            nonlocal 尝试次数
            尝试次数 += 1
            return 尝试次数 >= 2

        模型连接器.连接表[句柄]["释放函数"] = 释放回调
        首次 = 模型连接器.释放句柄(句柄)
        self.assertFalse(首次.成功)
        self.assertEqual(首次.错误码, "资源未收敛")
        self.assertIn(句柄, 模型连接器.连接表)
        self.assertEqual(模型连接器.连接表[句柄]["状态"], "释放失败")

        再次 = 模型连接器.释放句柄(句柄)
        self.assertTrue(再次.成功, 再次.错误说明)
        self.assertEqual(再次.值["状态"], "已结束并已释放")
        self.assertNotIn(句柄, 模型连接器.连接表)


class 测试线程池释放(unittest.TestCase):
    """验证线程池关闭不会无限等待，未收敛时保留句柄。"""

    def tearDown(self) -> None:
        并发控制.资源表.clear()
        并发控制.线程池释放等待秒 = 5.0

    def test_线程池释放超时保留账本后可重试(self) -> None:
        class 延迟线程池:
            def __init__(self) -> None:
                self.调用次数 = 0

            def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
                self.调用次数 += 1
                self.assertions = (wait, cancel_futures)
                if self.调用次数 == 1:
                    time.sleep(0.05)

        池 = 延迟线程池()
        并发控制.线程池释放等待秒 = 0.01
        创建结果 = 并发控制._创建("线程池", 池, "测试线程池")
        句柄 = 创建结果.值["句柄"]
        开始 = time.monotonic()
        首次 = 并发控制.释放句柄(句柄)
        耗时 = time.monotonic() - 开始
        self.assertFalse(首次.成功)
        self.assertEqual(首次.错误码, "资源未收敛")
        self.assertLess(耗时, 0.04, "释放接口必须有界返回")
        self.assertIn(句柄, 并发控制.资源表)

        time.sleep(0.06)
        并发控制.线程池释放等待秒 = 1.0
        再次 = 并发控制.释放句柄(句柄)
        self.assertTrue(再次.成功, 再次.错误说明)
        self.assertEqual(再次.值["状态"], "已结束并已释放")
        self.assertEqual(池.调用次数, 2)
        self.assertEqual(池.assertions, (True, True))


if __name__ == "__main__":
    unittest.main()
