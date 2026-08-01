"""第十三阶段：提供者注册表与统一结果测试（真实执行链）。

覆盖：注册真实函数→真实返回值；未注册→CAPABILITY_NOT_FOUND；
提供者抛异常→可重试；超时→CALL_TIMEOUT 且资源释放可再次提交；
证据账本有调用记录；卸载释放执行单元。
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
from 平台控制面.提供者.注册表 import 注册表


def 完整预算(并发: int = 2) -> dict:
    return {"内存上限": 100, "线程上限": 并发, "子进程上限": 1, "并发调用上限": 并发,
            "队列长度": 10, "文件句柄上限": 50, "临时空间上限": 100,
            "单次调用超时": 3, "每分钟重启次数": 2, "空闲回收时间": 60}


class Test注册表(unittest.TestCase):
    """提供者注册表：5 个真实场景。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="注册表测试_"))
        self.状态 = 平台状态(self.目录, 项目id="注册表测试")
        self.注册表 = 注册表(self.状态)

    def tearDown(self):
        for 能力id in list(self.注册表._提供者表):
            self.注册表.卸载(能力id)
        self.状态.关闭()

    def test_注册并真实调用返回真实值(self):
        成功, 消息 = self.注册表.注册(
            能力id="计算.求和", 调用函数=lambda 甲, 乙: 甲 + 乙, 预算=完整预算())
        self.assertTrue(成功, 消息)
        结果 = self.注册表.调用(能力id="计算.求和", 参数={"甲": 2, "乙": 3})
        self.assertTrue(结果["成功"], 结果["消息"])
        self.assertEqual(结果["结果"], 5, "真实函数返回值")
        self.assertEqual(结果["错误码"], "")

    def test_未注册能力返回稳定错误码(self):
        结果 = self.注册表.调用(能力id="不存在.能力")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "CAPABILITY_NOT_FOUND")

    def test_提供者异常返回可重试(self):
        def 抛异常() -> None:
            raise RuntimeError("真实异常")

        self.注册表.注册(能力id="异常.能力", 调用函数=抛异常, 预算=完整预算())
        结果 = self.注册表.调用(能力id="异常.能力")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "CALL_FAILED")
        self.assertTrue(结果["可重试"], "可恢复异常应可重试")

    def test_超时取消且资源释放可再次提交(self):
        def 慢() -> None:
            time.sleep(3)

        self.注册表.注册(能力id="慢.能力", 调用函数=慢,
                       预算={**完整预算(), "单次调用超时": 1})
        开始 = time.monotonic()
        结果 = self.注册表.调用(能力id="慢.能力", 超时秒=0.3)
        耗时 = time.monotonic() - 开始
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "CALL_TIMEOUT")
        self.assertLess(耗时, 1.5, "必须真实超时而非等待完成")
        # 超时后资源释放：再次提交不被"队列已满"拒绝
        结果2 = self.注册表.调用(能力id="慢.能力", 超时秒=0.1)
        self.assertFalse(结果2["成功"])
        self.assertEqual(结果2["错误码"], "CALL_TIMEOUT", "超时后资源已释放，可再次提交")

    def test_调用证据写入账本(self):
        self.注册表.注册(能力id="证据.能力", 调用函数=lambda: 1, 预算=完整预算())
        self.注册表.调用(能力id="证据.能力")
        证据 = self.状态.查询证据(类型="调用", 限制=10)
        self.assertTrue(证据, "调用必须有证据")
        self.assertTrue(any(证据项["主题"] == "证据.能力" for 证据项 in 证据),
                        "证据主题必须包含能力id")

    def test_卸载释放执行单元(self):
        self.注册表.注册(能力id="卸载.能力", 调用函数=lambda: 1, 预算=完整预算())
        self.assertTrue(self.注册表.已注册("卸载.能力"))
        self.assertTrue(self.注册表.卸载("卸载.能力"))
        self.assertFalse(self.注册表.已注册("卸载.能力"))
        self.assertNotIn("单元_卸载.能力", self.注册表.监督器._池表, "卸载后执行单元释放")


if __name__ == "__main__":
    unittest.main()
