"""P0-15：任务取消与真实进程组资源收敛回归。"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时.进程终止 import 进程存活, 终止进程组
from 运行核心.任务调度.任务进程 import 任务进程池


def 等待条件(条件, 超时秒: float = 3.0) -> bool:
    截止 = time.monotonic() + 超时秒
    while time.monotonic() < 截止:
        if 条件():
            return True
        time.sleep(0.01)
    return bool(条件())


def 进程存在(进程id: int) -> bool:
    # 平台差异收口：Windows 上 os.kill(pid, 0) 会真把目标进程结束掉，禁止裸用
    return 进程存活(进程id)


def 长时间运行(参数: dict, 取消事件) -> dict:
    就绪文件 = Path(参数["就绪文件"])
    就绪文件.write_text(str(os.getpid()), encoding="utf-8")
    while True:
        time.sleep(0.05)


def 忽略终止运行(参数: dict, 取消事件) -> dict:
    就绪文件 = Path(参数["就绪文件"])
    终止记录 = Path(参数["终止记录"])

    def 记录并忽略(信号值, 帧) -> None:
        del 信号值, 帧
        终止记录.write_text("已收到TERM但继续存活", encoding="utf-8")

    signal.signal(signal.SIGTERM, 记录并忽略)
    就绪文件.write_text(str(os.getpid()), encoding="utf-8")
    while True:
        time.sleep(0.05)


def 启动残留子进程(参数: dict, 取消事件) -> dict:
    就绪文件 = Path(参数["就绪文件"])
    子进程文件 = Path(参数["子进程文件"])
    脚本 = (
        "import os,signal,sys,time;"
        "from pathlib import Path;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8');"
        "\nwhile True: time.sleep(0.05)"
    )
    子进程 = subprocess.Popen(
        [sys.executable, "-c", 脚本, str(子进程文件)], close_fds=True)
    while not 子进程文件.exists():
        time.sleep(0.01)
    就绪文件.write_text(str(os.getpid()), encoding="utf-8")
    while 子进程.poll() is None:
        time.sleep(0.05)
    return {"子进程退出码": 子进程.returncode}


class Test任务进程收敛(unittest.TestCase):
    def setUp(self) -> None:
        self.临时对象 = tempfile.TemporaryDirectory(prefix="任务进程收敛_")
        self.临时目录 = Path(self.临时对象.name)
        self.池列表: list[任务进程池] = []
        self.残留进程id表: list[int] = []

    def tearDown(self) -> None:
        for 池 in self.池列表:
            try:
                池.关闭全部(超时秒=1.5)
            except TypeError:
                池.关闭全部()
        for 进程id in self.残留进程id表:
            if 进程存在(进程id):
                终止进程组(进程id, 信号="强杀")
        self.临时对象.cleanup()

    def 新池(self) -> 任务进程池:
        池 = 任务进程池(存储目录=self.临时目录 / f"状态_{len(self.池列表)}")
        self.池列表.append(池)
        return 池

    def 提交并等就绪(self, 池: 任务进程池, 能力id: str, 函数, **附加参数):
        就绪文件 = self.临时目录 / f"{能力id.replace('.', '_')}_{time.monotonic_ns()}.ready"
        池.注册执行函数(能力id, 函数)
        任务 = 池.提交(能力id=能力id, 参数={"就绪文件": str(就绪文件), **附加参数}, 超时秒=30)
        self.assertTrue(等待条件(就绪文件.exists), "真实工作进程未按时就绪")
        return 任务

    def test_正常取消只在完整进程组确认退出后成功(self):
        池 = self.新池()
        任务 = self.提交并等就绪(池, "任务.正常取消", 长时间运行)

        成功, 消息 = 池.取消(任务.任务id)

        self.assertTrue(成功, 消息)
        self.assertIn("已确认退出", 消息)
        self.assertEqual(任务.状态, "已取消")
        self.assertNotIn(任务.任务id, 池.活动任务表)
        self.assertFalse(任务.进程.is_alive())

    def test_工作进程忽略terminate时升级kill后才能成功(self):
        池 = self.新池()
        终止记录 = self.临时目录 / "忽略终止记录.txt"
        任务 = self.提交并等就绪(
            池, "任务.忽略终止", 忽略终止运行, 终止记录=str(终止记录))

        成功, 消息 = 池.取消(任务.任务id)

        self.assertTrue(等待条件(终止记录.exists), "必须先真实发送TERM")
        self.assertTrue(成功, 消息)
        self.assertIn("已确认退出", 消息)
        self.assertFalse(任务.进程.is_alive())
        self.assertEqual(任务.状态, "已取消")

    def test_取消回收完整进程组不遗留忽略终止的子进程(self):
        池 = self.新池()
        子进程文件 = self.临时目录 / "残留子进程.pid"
        任务 = self.提交并等就绪(
            池, "任务.子进程残留", 启动残留子进程, 子进程文件=str(子进程文件))
        self.assertTrue(等待条件(子进程文件.exists), "真实子进程未启动")
        子进程id = int(子进程文件.read_text(encoding="utf-8"))
        self.残留进程id表.append(子进程id)
        self.assertTrue(进程存在(子进程id))

        成功, 消息 = 池.取消(任务.任务id)

        self.assertTrue(成功, 消息)
        self.assertTrue(等待条件(lambda: not 进程存在(子进程id)),
                        f"取消成功后仍遗留子进程 {子进程id}")
        self.assertEqual(池.活动进程数(), 0)

    def test_请求阶段不得假成功并保留活动账本供重试收敛(self):
        池 = self.新池()
        任务 = self.提交并等就绪(池, "任务.取消重试", 长时间运行)

        首次成功, 首次消息 = 池.取消(任务.任务id, 等待截止秒=0)

        self.assertFalse(首次成功)
        self.assertIn("请求已发出", 首次消息)
        self.assertEqual(任务.状态, "取消中")
        self.assertIn(任务.任务id, 池.活动任务表)
        self.assertNotEqual(任务.完成时间, time.strftime("%Y-%m-%d %H:%M:%S"))

        重试成功, 重试消息 = 池.取消(任务.任务id, 等待截止秒=1.5)
        self.assertTrue(重试成功, 重试消息)
        self.assertIn("已确认退出", 重试消息)
        self.assertEqual(任务.状态, "已取消")
        self.assertNotIn(任务.任务id, 池.活动任务表)

    def test_等待排空关闭都有硬截止且关闭可重试(self):
        池 = self.新池()
        任务 = self.提交并等就绪(池, "任务.截止", 长时间运行)

        开始 = time.monotonic()
        等待成功, 等待消息 = 池.等待(任务.任务id, 超时秒=0.05)
        self.assertFalse(等待成功)
        self.assertIn("截止", 等待消息)
        self.assertLess(time.monotonic() - 开始, 0.3)

        开始 = time.monotonic()
        排空成功, 排空消息 = 池.排空(超时秒=0.05)
        self.assertFalse(排空成功)
        self.assertIn("截止", 排空消息)
        self.assertLess(time.monotonic() - 开始, 0.3)
        self.assertIn(任务.任务id, 池.活动任务表)

        首次关闭, 首次消息 = 池.关闭全部(超时秒=0)
        self.assertFalse(首次关闭)
        self.assertIn("请求已发出", 首次消息)
        self.assertIn(任务.任务id, 池.活动任务表)

        重试关闭, 重试消息 = 池.关闭全部(超时秒=1.5)
        self.assertTrue(重试关闭, 重试消息)
        self.assertEqual(任务.状态, "已取消")
        self.assertEqual(池.活动进程数(), 0)


if __name__ == "__main__":
    unittest.main()
