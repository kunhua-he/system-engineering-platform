"""任务进程池有界测试：最大活动数/有界队列/提交截止/资源繁忙/取消真实终止/停止排空。

覆盖手册第十节 10.1：任务队列与线程池必须有界；提交超过容量必须阻塞到明确截止
或返回统一资源繁忙错误；禁止为每个任务无限创建进程与监视线程；取消不得假称
终止副作用（工作进程真实退出后才发布 已取消 终态）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.任务调度.任务进程 import 任务进程池, 资源繁忙错误

终态集合 = {"成功", "失败", "已取消", "超时", "崩溃"}


def 等待条件(条件, 超时秒: float = 8.0) -> bool:
    截止 = time.monotonic() + 超时秒
    while time.monotonic() < 截止:
        if 条件():
            return True
        time.sleep(0.01)
    return bool(条件())


def 任务短暂停顿(参数: dict, 取消事件) -> dict:
    time.sleep(float(参数.get("等待秒", 0.5)))
    return {"取消已见": 取消事件.is_set()}


class Test任务进程池有界(unittest.TestCase):
    def setUp(self):
        self.临时对象 = tempfile.TemporaryDirectory(prefix="任务进程池有界_")
        self.存储目录 = Path(self.临时对象.name) / "状态"
        self.池列表: list[任务进程池] = []

    def tearDown(self):
        for 池 in self.池列表:
            池.停止()
        self.临时对象.cleanup()

    def _新池(self, **参数) -> 任务进程池:
        池 = 任务进程池(存储目录=self.存储目录, **参数)
        self.池列表.append(池)
        return 池

    def test_最大活动数限制同时活动进程不超过上限(self):
        池 = self._新池(最大活动数=4, 最大排队数=8)
        池.注册执行函数("任务.停顿", 任务短暂停顿)
        提交结果 = []
        for _ in range(8):
            提交结果.append(池.提交(能力id="任务.停顿", 参数={"等待秒": 0.4}))
        self.assertEqual(len(提交结果), 8)
        self.assertTrue(等待条件(lambda: 池.活动进程数() >= 4), "应有 4 个任务同时运行")
        self.assertLessEqual(池.活动进程数(), 4)
        self.assertTrue(等待条件(lambda: all(任务.状态 in 终态集合 for 任务 in 提交结果)))
        self.assertEqual(池.活动进程数(), 0, "全部完成后活动进程必须归零")
        self.assertTrue(all(任务.状态 == "成功" for 任务 in 提交结果),
                        "排队任务也必须真实执行，不得假成功或丢失")

    def test_有界队列满立即返回资源繁忙且不丢任务(self):
        池 = self._新池(最大活动数=1, 最大排队数=1, 提交截止秒=0)
        池.注册执行函数("任务.停顿", 任务短暂停顿)
        任务一 = 池.提交(能力id="任务.停顿", 参数={"等待秒": 0.8})
        排队结果: list = []
        # 后台线程提交任务二：无空槽且队列未满 → 排队并阻塞等待槽位
        def 后台提交任务二() -> None:
            排队结果.append(池.提交(能力id="任务.停顿", 参数={"等待秒": 0.2}))

        线程 = threading.Thread(target=后台提交任务二, daemon=True)
        线程.start()
        self.assertTrue(等待条件(lambda: len(池.等待队列) == 1), "任务二应进入有界等待队列")
        # 队列已满（最大排队数 1）且提交截止秒为 0 → 立即返回资源繁忙，不假成功
        with self.assertRaises(资源繁忙错误) as 上下文:
            池.提交(能力id="任务.停顿", 参数={"等待秒": 0.2})
        self.assertIn("资源繁忙", str(上下文.exception))
        线程.join(8)
        self.assertEqual(len(排队结果), 1, "排队任务不得丢失")
        任务二 = 排队结果[0]
        self.assertTrue(等待条件(lambda: 任务一.状态 in 终态集合))
        self.assertEqual(任务一.状态, "成功")
        self.assertTrue(等待条件(lambda: 任务二.状态 in 终态集合))
        self.assertEqual(任务二.状态, "成功")
        self.assertEqual(池.活动进程数(), 0)

    def test_提交截止超时抛出资源繁忙(self):
        池 = self._新池(最大活动数=1, 最大排队数=1, 提交截止秒=0.2)
        池.注册执行函数("任务.停顿", 任务短暂停顿)
        任务一 = 池.提交(能力id="任务.停顿", 参数={"等待秒": 2.0})
        排队结果: list = []

        def 后台提交任务二() -> None:
            排队结果.append(池.提交(能力id="任务.停顿", 参数={"等待秒": 0.1}))

        线程 = threading.Thread(target=后台提交任务二, daemon=True)
        线程.start()
        self.assertTrue(等待条件(lambda: len(池.等待队列) == 1), "任务二应进入有界等待队列")
        # 队列满且提交截止秒大于 0 → 阻塞到明确截止后抛资源繁忙
        开始 = time.monotonic()
        with self.assertRaises(资源繁忙错误) as 上下文:
            池.提交(能力id="任务.停顿", 参数={"等待秒": 0.1})
        消耗 = time.monotonic() - 开始
        self.assertGreaterEqual(消耗, 0.15, "队列满时应阻塞到明确截止而非立即失败")
        self.assertLess(消耗, 2.0)
        self.assertIn("资源繁忙", str(上下文.exception))
        # 抛错只拒绝第三个任务，已在运行与排队的任务不受影响
        self.assertTrue(等待条件(lambda: 任务一.状态 in 终态集合))
        self.assertEqual(任务一.状态, "成功")
        线程.join(8)
        self.assertEqual(len(排队结果), 1, "排队任务不得丢失")
        self.assertTrue(等待条件(lambda: 排队结果[0].状态 in 终态集合),
                        "排队任务必须真实执行完成")
        self.assertEqual(排队结果[0].状态, "成功")

    def test_取消运行中任务进程真实终止(self):
        池 = self._新池()
        池.注册执行函数("任务.长停", 任务短暂停顿)
        任务 = 池.提交(能力id="任务.长停", 参数={"等待秒": 30})
        self.assertTrue(等待条件(lambda: 任务.进程 is not None and 任务.进程.is_alive()))
        成功, 消息 = 池.取消(任务.任务id)
        self.assertTrue(成功)
        self.assertIn("终止", 消息)
        self.assertTrue(等待条件(lambda: 任务.状态 in 终态集合))
        self.assertEqual(任务.状态, "已取消")
        self.assertFalse(任务.进程.is_alive(), "取消后工作进程必须真实退出")
        self.assertEqual(池.活动进程数(), 0)

    def test_停止后活动进程归零排队被拒且监视线程退出(self):
        池 = self._新池(最大活动数=1, 最大排队数=2, 提交截止秒=5)
        池.注册执行函数("任务.长停", 任务短暂停顿)
        任务一 = 池.提交(能力id="任务.长停", 参数={"等待秒": 30})
        排队异常: list[BaseException] = []

        def 后台排队提交() -> None:
            try:
                池.提交(能力id="任务.长停", 参数={"等待秒": 30})
            except BaseException as 错误:
                排队异常.append(错误)

        线程 = threading.Thread(target=后台排队提交, daemon=True)
        线程.start()
        self.assertTrue(等待条件(lambda: len(池.等待队列) == 1), "排队任务应处于有界等待队列")
        self.assertTrue(等待条件(lambda: 池.活动进程数() == 1))
        池.停止()
        池.停止()
        self.assertEqual(池.活动进程数(), 0, "停止后活动进程必须归零")
        self.assertEqual(len(池.等待队列), 0, "停止后排队任务必须被清空拒绝")
        self.assertEqual(任务一.状态, "已取消")
        self.assertFalse(任务一.进程.is_alive())
        with self.assertRaises(RuntimeError):
            池.提交(能力id="任务.长停", 参数={"等待秒": 0.1})
        线程.join(5)
        self.assertEqual(len(排队异常), 1, "停止必须拒绝排队中的任务")
        self.assertIn("已停止", str(排队异常[0]))
        if 池.监视线程 is not None:
            self.assertTrue(等待条件(lambda: not 池.监视线程.is_alive()),
                            "停止后监视线程必须退出")

    def test_内部监视线程有界不超过最大活动数加一(self):
        池 = self._新池(最大活动数=4, 最大排队数=16)
        池.注册执行函数("任务.停顿", 任务短暂停顿)
        for _ in range(4):
            池.提交(能力id="任务.停顿", 参数={"等待秒": 0.3})
        池.注册执行函数("任务.快", lambda 参数: {"快": True})
        池.提交(能力id="任务.快")
        池.注册执行函数("任务.瞬", lambda 参数: {"瞬": True})
        池.提交(能力id="任务.瞬")
        池.注册执行函数("任务.短", lambda 参数: {"短": True})
        池.提交(能力id="任务.短")
        # 提交再多任务，内部监视线程始终只有一个，总量不超过 最大活动数+1
        池.注册执行函数("任务.更多", 任务短暂停顿)
        for 序号 in range(8):
            池.提交(能力id="任务.更多", 参数={"等待秒": 0.2})
        self.assertTrue(等待条件(lambda: 池.监视线程 is not None and 池.监视线程.is_alive()))
        内部线程数 = sum(
            1 for 线程 in threading.enumerate()
            if "任务进程池" in 线程.name and 线程.is_alive())
        self.assertLessEqual(内部线程数, 池.最大活动数 + 1,
                             "监视线程总数不得超过 最大活动数+1")
        self.assertEqual(内部线程数, 1, "进程池内部应只有一个轮询监视线程")
        self.assertTrue(等待条件(lambda: 池.活动进程数() == 0))


if __name__ == "__main__":
    unittest.main()
