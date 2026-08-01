"""第十三阶段：真实资源采样器测试（内存/文件句柄/临时空间/组合报告）。

真实场景（全部真实系统调用，数值来自实际运行状态，不伪造）：
1. 真实内存采样 > 0（resource.getrusage RU_MAXRSS）
2. 真实打开 50 个文件后，文件句柄数随之增加（/proc/self/fd 或 /dev/fd）
3. 真实写入临时目录后，临时空间占用随之增加（os.path.getsize 求和）
4. 组合报告含全部键；峰值来自真实资源监督器，真实采样字段为真实正值
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.提供者 import 采样器 as 模块
from 平台控制面.提供者.采样器 import (采样内存, 采样文件句柄, 采样临时空间, 组合报告)
from 平台控制面.资源监督 import 资源监督器


class 假状态:
    """资源监督器所需的最小状态桩：只记录证据，不依赖真实平台状态。"""

    def 追加证据(self, **字段):
        return "证据id-测试"


def 建预算() -> dict:
    return {"内存上限": 1024, "线程上限": 4, "子进程上限": 4, "并发调用上限": 3,
            "队列长度": 10, "文件句柄上限": 256, "临时空间上限": 1024,
            "单次调用超时": 5, "每分钟重启次数": 2, "空闲回收时间": 60}


class 测试真实资源采样器(unittest.TestCase):
    """真实资源采样器：实际系统状态验证，不复制简化算法。"""

    def test_真实内存采样值大于零(self):
        结果 = 采样内存()
        self.assertTrue(结果["成功"], 结果["错误说明"])
        self.assertGreater(结果["值"], 0, "真实进程内存峰值必须大于 0")
        self.assertGreater(结果["原始值"], 0, "原始 RU_MAXRSS 必须大于 0")
        self.assertTrue(结果["原始单位"])

    def test_打开五十个文件后句柄数真实增加(self):
        前 = 采样文件句柄()
        self.assertTrue(前["成功"], 前["错误说明"])
        已开: list[int] = []
        try:
            for _ in range(50):
                已开.append(os.open("/dev/null", os.O_RDONLY))
            后 = 采样文件句柄()
            self.assertTrue(后["成功"], 后["错误说明"])
        finally:
            for 句柄 in 已开:
                os.close(句柄)
        self.assertGreater(后["值"], 前["值"], "打开 50 个文件后句柄数必须增加")
        self.assertGreaterEqual(后["值"] - 前["值"], 50, "每个打开的文件必须占用一个真实句柄")

    def test_写入临时目录后占用真实增加(self):
        with tempfile.TemporaryDirectory(prefix="采样器测试_") as 目录:
            前 = 采样临时空间(目录)
            self.assertTrue(前["成功"], 前["错误说明"])
            写入字节 = 2 * 1024 * 1024
            with open(os.path.join(目录, "数据.bin"), "wb") as 文件:
                文件.write(b"x" * 写入字节)
            后 = 采样临时空间(目录)
            self.assertTrue(后["成功"], 后["错误说明"])
            self.assertGreater(后["值"], 前["值"], "写入后临时空间占用必须增加")
            self.assertGreaterEqual(后["值"] - 前["值"], 写入字节,
                                    "占用增量必须不小于实际写入字节数")

    def test_组合报告含全部键且真实资源监督器峰值生效(self):
        监督 = 资源监督器(假状态())
        注册, 消息 = 监督.注册执行单元(单元id="单元甲", 预算=建预算())
        self.assertTrue(注册, 消息)
        for _ in range(3):
            成功, 消息, _ = 监督.提交任务("单元甲", time.sleep, 0.3)
            self.assertTrue(成功, 消息)
        try:
            with tempfile.TemporaryDirectory(prefix="组合报告_") as 目录:
                with open(os.path.join(目录, "数据.txt"), "w", encoding="utf-8") as 文件:
                    文件.write("组合报告真实写入" * 200)
                报告 = 组合报告(监督器报告=监督.状态报告(), 临时目录=目录)
        finally:
            监督.优雅停止("单元甲")
        for 键 in 模块.报告键表:
            self.assertIn(键, 报告, f"组合报告缺少键: {键}")
        self.assertTrue(报告["成功"], 报告["错误说明"])
        self.assertGreater(报告["内存峰值MB"], 0, "真实内存峰值必须大于 0")
        self.assertGreater(报告["文件句柄数"], 0, "真实文件句柄数必须大于 0")
        self.assertGreater(报告["临时空间字节"], 0, "真实临时空间占用必须大于 0")
        self.assertEqual(报告["线程峰值"], 3, "线程峰值必须来自真实活跃任务数")
        self.assertEqual(报告["并发峰值"], 3, "并发峰值必须来自真实活跃任务数")
        self.assertEqual(报告["队列峰值"], 0)
        self.assertIn("单元甲", 报告["单元表"])
        self.assertTrue(报告["采样时间"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
