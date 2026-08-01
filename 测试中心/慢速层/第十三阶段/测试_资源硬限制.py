"""第十三阶段：进程资源硬限制真实测试（macOS resource.setrlimit，非 cgroup）。

真实场景：
1. 真实子进程内 RLIMIT_NOFILE=5 → 打开超过上限的文件被拒（OSError EMFILE）
2. 真实子进程内 RLIMIT_NPROC=1 → fork 超过同用户进程上限被拒（OSError EAGAIN）
3. 探测报告结构完整；无法强制的类型（macOS 的 RLIMIT_AS）如实返回 UNENFORCEABLE
4. 应用预算返回已生效/不可强制清单；不可强制预算启动前拒绝；可强制预算在
   独立进程组（新会话）中执行且 exec 前限制真实生效
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.提供者 import 资源硬限制 as 模块


def 子进程自检(类型: str) -> dict:
    """在真实子进程内执行自检并返回 JSON 报告（子进程内 setrlimit 不污染测试进程）。"""
    结果 = subprocess.run(
        [sys.executable, str(Path(模块.__file__).resolve()), "--自检", 类型],
        capture_output=True, text=True, timeout=60)
    if 结果.returncode != 0:
        raise AssertionError(f"自检子进程异常退出: {结果.returncode} {结果.stderr}")
    return json.loads(结果.stdout.strip().splitlines()[-1])


class 测试进程资源硬限制(unittest.TestCase):
    """进程资源硬限制：真实子进程验证，不复制简化算法。"""

    def test_真实子进程内文件句柄上限_打开超过上限被拒(self):
        项 = 子进程自检("文件句柄")
        self.assertEqual(项["状态"], "已生效", 项["说明"])
        self.assertIn("EMFILE", 项["说明"], "超过上限的打开必须被 OSError(EMFILE) 拒绝")
        self.assertIn("被拒", 项["说明"])

    def test_真实子进程内进程数上限_fork超过上限被拒(self):
        项 = 子进程自检("进程数")
        self.assertEqual(项["状态"], "已生效", 项["说明"])
        self.assertIn("EAGAIN", 项["说明"], "超过同用户进程上限的 fork 必须被 OSError(EAGAIN) 拒绝")
        self.assertIn("fork", 项["说明"])

    def test_探测报告结构完整且不可强制如实报告(self):
        报告 = 模块.探测能力()
        self.assertTrue(报告["成功"], 报告["错误说明"])
        for 键 in ("成功", "已生效", "不可强制", "错误说明"):
            self.assertIn(键, 报告, f"探测报告缺少键: {键}")
        已生效类型 = {项["类型"] for 项 in 报告["已生效"]}
        self.assertTrue({"文件句柄", "进程数", "核心转储"} <= 已生效类型,
                        f"macOS 可强制的类型缺失: {已生效类型}")
        for 项 in 报告["已生效"]:
            self.assertEqual(项["状态"], "已生效")
            self.assertTrue(项["说明"])
        不可强制类型 = {项["类型"] for 项 in 报告["不可强制"]}
        self.assertIn("内存", 不可强制类型,
                      "macOS 不支持 RLIMIT_AS 硬限制，必须如实报告不可强制")
        for 项 in 报告["不可强制"]:
            self.assertEqual(项["状态"], 模块.未强制)
            self.assertTrue(项["说明"])
        # 契约直调：无法强制的预算必须返回 UNENFORCEABLE，不能显示为正常
        结果 = 模块.设置限制("内存", 8 * 1024 ** 3, 8 * 1024 ** 3)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], 模块.未强制)
        self.assertTrue(结果["错误说明"])

    def test_应用预算返回清单且不可强制预算拒绝启动(self):
        应用 = 模块.应用预算({"进程数上限": 5000, "文件句柄上限": 1024,
                          "核心转储上限": 0, "内存上限": 8 * 1024 ** 3})
        self.assertFalse(应用["成功"], "存在不可强制项必须如实失败，不能显示为正常")
        已生效类型 = {项["类型"] for 项 in 应用["已生效"]}
        self.assertTrue({"文件句柄", "进程数", "核心转储"} <= 已生效类型)
        self.assertEqual({项["类型"] for 项 in 应用["不可强制"]}, {"内存"})
        # 不可强制预算：独立进程组启动前必须拒绝（UNENFORCEABLE）
        拒绝 = 模块.在独立进程组中运行(
            [sys.executable, "-c", "import os; print(os.getpgrp())"],
            预算={"文件句柄上限": 64, "内存上限": 8 * 1024 ** 3})
        self.assertFalse(拒绝["成功"])
        self.assertEqual(拒绝["错误码"], 模块.未强制)
        self.assertIn("内存", 拒绝["错误说明"])
        # 可强制预算：新会话进程组 + exec 前限制真实生效
        运行 = 模块.在独立进程组中运行(
            [sys.executable, "-c",
             "import os, resource; print(os.getpgrp(), os.getpid(), "
             "resource.getrlimit(resource.RLIMIT_NOFILE)[0])"],
            预算={"文件句柄上限": 64, "核心转储上限": 0}, 超时秒=30)
        self.assertTrue(运行["成功"], 运行["错误说明"])
        进程组id, 进程号, 句柄上限 = [int(段) for 段 in 运行["值"]["输出"].strip().split()]
        self.assertEqual(进程组id, 进程号, "子进程必须是新会话的进程组组长")
        self.assertNotEqual(进程组id, os.getpgrp(), "必须独立于调用方进程组")
        self.assertEqual(句柄上限, 64, "预算必须在 exec 前真实生效")


if __name__ == "__main__":
    unittest.main(verbosity=2)
