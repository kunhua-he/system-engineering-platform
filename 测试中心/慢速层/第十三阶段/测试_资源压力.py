"""第十三阶段：资源压力与进程树压力测试——4 个真实压力场景。

场景全部真实执行，数值来自真实系统状态，不伪造：
1. 20 个并发任务：资源监督器线程/并发峰值采样真实达到 20（≥并发数）
2. 打开 50 个文件后：文件句柄采样真实增加（≥50）
3. 5 层真实 python 进程树：killpg 强杀后 ps 无残留
4. 写入 10MB 临时文件后：临时空间采样真实增加（≥10MB）
结束后无残留进程/临时目录（tearDown 兜底清理）。
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(系统根))  # 无条件置顶，防同名测试目录遮蔽真实包

from 平台控制面.提供者.采样器 import 采样文件句柄, 采样临时空间, 组合报告
from 平台控制面.资源监督 import 资源监督器

五层树代码 = """import os, subprocess, sys, time
深度 = int(os.environ["树深度"])
工作目录 = os.environ["树工作目录"]
open(os.path.join(工作目录, "层" + str(深度) + ".pid"), "w").write(str(os.getpid()))
if 深度 < 4:
    subprocess.Popen([sys.executable, "-c", os.environ["树代码"]],
                     env=dict(os.environ, 树深度=str(深度 + 1)))
while True:
    time.sleep(60)
"""


class 假状态:
    """资源监督器最小状态桩：只记录证据，不依赖真实平台状态。"""

    def 追加证据(self, **字段):
        return "证据id-压力测试"


def 建预算(并发数: int) -> dict:
    return {"内存上限": 1024, "线程上限": 并发数, "子进程上限": 并发数,
            "并发调用上限": 并发数, "队列长度": 并发数 * 2, "文件句柄上限": 1024,
            "临时空间上限": 1024, "单次调用超时": 5, "每分钟重启次数": 2,
            "空闲回收时间": 60}


def 并发闸门任务(闸门: threading.Barrier, 秒数: float) -> int:
    """真实并发任务：等 20 个任务同时到达后一起驻留，返回自身 PID。"""
    闸门.wait(timeout=15)
    time.sleep(秒数)
    return os.getpid()


def 查询存活pid(pid表: list[int]) -> list[int]:
    """ps 查询：返回仍在系统中的 PID（含未回收僵尸）。"""
    if not pid表:
        return []
    输出 = subprocess.run(["ps", "-p", ",".join(map(str, pid表)), "-o", "pid="],
                        capture_output=True, text=True).stdout
    return [int(行.strip()) for 行 in 输出.splitlines() if 行.strip()]


class 测试资源压力(unittest.TestCase):
    def tearDown(self):
        """兜底清理：断言失败时也不留进程组与临时目录。"""
        信息 = getattr(self, "进程树信息", None)
        if not 信息:
            return
        try:
            os.killpg(信息["组长pid"], signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        shutil.rmtree(信息["工作目录"], ignore_errors=True)

    def test_场景1_二十并发任务峰值采样真实达到并发数(self):
        """真实 20 个任务同时运行：监督器峰值与组合报告均 ≥20。"""
        监督 = 资源监督器(假状态())
        注册, 消息 = 监督.注册执行单元(单元id="压力甲", 预算=建预算(20))
        self.assertTrue(注册, 消息)
        闸门 = threading.Barrier(20)
        try:
            for _ in range(20):
                成功, 消息, _ = 监督.提交任务("压力甲", 并发闸门任务, 闸门, 0.5)
                self.assertTrue(成功, 消息)
            截止 = time.time() + 15
            峰值报告 = 监督.采样("压力甲")
            while 峰值报告["并发峰值"] < 20 and time.time() < 截止:
                time.sleep(0.05)
                峰值报告 = 监督.采样("压力甲")
            self.assertGreaterEqual(峰值报告["并发峰值"], 20,
                                    "20 并发任务下并发峰值必须真实达到 20")
            self.assertGreaterEqual(峰值报告["线程峰值"], 20,
                                    "20 并发任务下线程峰值必须真实达到 20")
            while 监督.采样("压力甲")["成功"] < 20 and time.time() < 截止:
                time.sleep(0.05)
            self.assertEqual(监督.采样("压力甲")["成功"], 20, "20 个任务必须全部真实完成")
            with tempfile.TemporaryDirectory(prefix="压力组合_") as 目录:
                with open(os.path.join(目录, "压力.txt"), "w", encoding="utf-8") as 文件:
                    文件.write("压力" * 1000)
                报告 = 组合报告(监督器报告=监督.状态报告(), 临时目录=目录)
            self.assertGreaterEqual(报告["并发峰值"], 20, "组合报告并发峰值必须 ≥20")
            self.assertGreaterEqual(报告["线程峰值"], 20, "组合报告线程峰值必须 ≥20")
            self.assertTrue(报告["成功"], 报告["错误说明"])
        finally:
            监督.优雅停止("压力甲")

    def test_场景2_打开五十个文件后句柄采样真实增加(self):
        """真实打开 50 个文件：句柄采样增量必须 ≥50。"""
        前 = 采样文件句柄()
        self.assertTrue(前["成功"], 前["错误说明"])
        已开: list[int] = []
        try:
            for _ in range(50):
                已开.append(os.open("/dev/null", os.O_RDONLY))
            后 = 采样文件句柄()
        finally:
            for 句柄 in 已开:
                os.close(句柄)
        self.assertTrue(后["成功"], 后["错误说明"])
        self.assertGreaterEqual(后["值"] - 前["值"], 50,
                                "每个打开的文件必须占用一个真实句柄")

    def test_场景3_五层进程树强杀后ps无残留(self):
        """真实 5 层 python 进程树：killpg 强杀后 ps 全部消失、目录清理。"""
        目录 = Path(tempfile.mkdtemp(prefix="五层树_"))
        环境 = dict(os.environ, 树代码=五层树代码, 树深度="0", 树工作目录=str(目录))
        组长 = subprocess.Popen([sys.executable, "-c", 五层树代码],
                               env=环境, start_new_session=True)
        信息 = {"组长pid": 组长.pid, "工作目录": str(目录)}
        self.进程树信息 = 信息
        截止 = time.time() + 15
        while len(sorted(目录.glob("层*.pid"))) < 5 and time.time() < 截止:
            time.sleep(0.1)
        pid表 = [int(文件.read_text(encoding="utf-8").strip())
                 for 文件 in sorted(目录.glob("层*.pid"))]
        self.assertEqual(len(pid表), 5, f"应收集到 5 层节点 PID: {pid表}")
        self.assertEqual(len(set(pid表)), 5, "5 层节点 PID 必须互不相同")
        self.assertEqual(len(查询存活pid(pid表)), 5, "强杀前 5 层节点应全部存活")
        组号集合 = {subprocess.run(["ps", "-p", str(进程), "-o", "pgid="],
                               capture_output=True, text=True).stdout.strip()
                   for 进程 in pid表}
        self.assertEqual(组号集合, {str(组长.pid)}, "整棵树应同属一个独立进程组")
        os.killpg(组长.pid, signal.SIGKILL)
        try:
            组长.wait(timeout=10)
        except (ChildProcessError, subprocess.TimeoutExpired):
            pass
        截止 = time.time() + 8
        while 查询存活pid(pid表) and time.time() < 截止:
            time.sleep(0.1)
        self.assertEqual(查询存活pid(pid表), [], "killpg 后 ps 不应有任何残留 PID")
        shutil.rmtree(目录, ignore_errors=True)
        self.assertFalse(目录.exists(), "强杀后临时目录应已清理")
        self.进程树信息 = None

    def test_场景4_写入十兆临时文件后占用采样真实增加(self):
        """真实写入 10MB：临时空间采样增量必须 ≥10MB。"""
        with tempfile.TemporaryDirectory(prefix="十兆临时_") as 目录:
            前 = 采样临时空间(目录)
            self.assertTrue(前["成功"], 前["错误说明"])
            写入字节 = 10 * 1024 * 1024
            with open(os.path.join(目录, "压力10MB.bin"), "wb") as 文件:
                文件.write(b"x" * 写入字节)
            后 = 采样临时空间(目录)
            self.assertTrue(后["成功"], 后["错误说明"])
            self.assertGreaterEqual(后["值"] - 前["值"], 写入字节,
                                    "占用增量必须不小于实际写入的 10MB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
