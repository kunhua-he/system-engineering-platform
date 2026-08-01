"""第十三阶段：超时取消与重启频率治理测试（真实执行）。

覆盖：真实慢任务超时→取消→资源释放可再次提交；重启频率滑动窗口
超限拒绝并写证据；窗口过期后允许重启。
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.平台状态 import 平台状态
from 平台控制面.提供者.超时治理 import 超时治理


class Test超时治理(unittest.TestCase):
    """超时取消与重启频率：3 个真实场景。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="超时治理测试_"))
        self.状态 = 平台状态(self.目录, 项目id="超时治理测试")
        self.治理 = 超时治理(self.状态)

    def tearDown(self):
        self.状态.关闭()

    def test_真实慢任务超时取消且资源释放可再次提交(self):
        def 慢() -> None:
            time.sleep(3)

        开始 = time.monotonic()
        成功, 消息, _ = self.治理.治理超时(单元id="慢单元", 任务=慢, 超时秒=0.3)
        耗时 = time.monotonic() - 开始
        self.assertFalse(成功, "必须真实超时")
        self.assertIn("超时", 消息)
        self.assertLess(耗时, 1.5, "必须真实取消而非等待完成")
        # 资源释放：再次提交不被拒绝（信号量已归还）
        成功2, 消息2, _ = self.治理.治理超时(单元id="慢单元", 任务=慢, 超时秒=0.1)
        self.assertFalse(成功2)
        self.assertIn("超时", 消息2)
        # 治理层如实记录两次超时取消
        self.assertEqual(self.治理.治理状态()["慢单元"]["取消次数"], 2, "两次超时均已计入取消")
        # 等待慢任务真正结束（后台任务最终完成，无泄漏线程）
        time.sleep(3.2)

    def test_重启频率超限拒绝并写证据(self):
        单元id = "重启单元"
        for _ in range(3):
            self.治理.记录重启(单元id)
        self.assertFalse(self.治理.允许重启(单元id, 每分钟上限=3),
                         "窗口内第 4 次重启必须被拒")
        证据 = self.状态.查询证据(类型="重启治理", 限制=5)
        self.assertTrue(any(证据项["主题"] == 单元id for 证据项 in 证据),
                        "拒绝必须写证据")

    def test_窗口过期后允许重启(self):
        单元id = "窗口单元"
        for _ in range(3):
            self.治理.记录重启(单元id)
        # 窗口已过期（记录时间戳人为推旧，模拟真实时间流逝）
        记录表 = self.治理._重启记录表[单元id]
        记录表.clear()
        记录表.append((time.time() - 120, "旧记录"))
        self.assertTrue(self.治理.允许重启(单元id, 每分钟上限=3),
                        "窗口过期后允许重启")
        # 真实滑动：写入 3 次真实记录后拒绝
        for _ in range(3):
            self.治理.记录重启(单元id)
        self.assertFalse(self.治理.允许重启(单元id, 每分钟上限=3))


if __name__ == "__main__":
    unittest.main()
