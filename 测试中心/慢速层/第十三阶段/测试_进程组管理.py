"""第十三阶段：进程组与子进程树回收——真实 3 层进程树场景测试。

每个场景真实 spawn python 父→子→孙 进程树（独立进程组），强杀后
断言：ps 全部 PID 消失、临时目录清理、端口释放可重绑。
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.提供者.进程组管理 import 启动进程树, 强杀进程组, 检查残留


def 查询进程组号(pid: int) -> int | None:
    """ps 查询指定 PID 的进程组号；进程已消失返回 None。"""
    输出 = subprocess.run(["ps", "-p", str(pid), "-o", "pgid="],
                         capture_output=True, text=True).stdout.strip()
    return int(输出) if 输出 else None


def 查询进程存活(pid: int) -> bool:
    """ps 查询指定 PID 是否仍在系统中。"""
    输出 = subprocess.run(["ps", "-p", str(pid), "-o", "pid="],
                         capture_output=True, text=True).stdout.strip()
    return bool(输出)


class 测试进程组管理(unittest.TestCase):
    """真实进程树：启动 → 强杀 → 回收验证，覆盖 4 个场景。"""

    def tearDown(self):
        """兜底清理：断言失败时也不留进程组与临时目录。"""
        信息 = getattr(self, "进程组信息", None)
        if not 信息:
            return
        try:
            os.killpg(信息["进程组id"], signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        shutil.rmtree(信息["工作目录"], ignore_errors=True)

    def _端口可重绑(self, 端口: int) -> bool:
        """测试独立实现端口探测：不依赖生产私有函数。"""
        套接字 = socket.socket()
        try:
            套接字.bind(("127.0.0.1", 端口))
            return True
        except OSError:
            return False
        finally:
            套接字.close()

    def test_场景1_三层进程树强杀后全部回收(self):
        """父/子/孙各自打印 PID 且同属独立进程组；killpg 后全部消失。"""
        self.进程组信息 = 启动进程树()
        信息 = self.进程组信息
        节点表 = 信息["节点pid表"]
        self.assertEqual(len(节点表), 3, "应收集到 3 个节点 PID")
        self.assertEqual(len(set(节点表)), 3, "三层节点 PID 必须互不相同")
        # 独立进程组：全部节点 pgid 都等于组长 PID
        组号集合 = {查询进程组号(进程) for 进程 in 节点表}
        self.assertEqual(组号集合, {信息["进程组id"]}, "整棵树应同属一个独立进程组")
        # 各自打印 PID：落盘日志与 PID 文件一致
        目录 = Path(信息["工作目录"])
        for 序号, 进程 in enumerate(节点表):
            日志 = (目录 / f"节点_{序号}.log").read_text(encoding="utf-8")
            self.assertIn(f"PID={进程}", 日志, f"节点_{序号} 应打印自身 PID")
        # 树存活时孙节点端口应被占用、目录应存在
        self.assertFalse(self._端口可重绑(信息["端口"]), "树存活时端口应被占用")
        self.assertTrue(目录.is_dir(), "树存活时工作目录应存在")
        # 强杀整个进程组
        报告 = 强杀进程组(信息)
        self.assertTrue(报告["成功"], f"强杀报告: {报告}")
        self.assertEqual(报告["未退出pid"], [], "强杀后不应有未退出 PID")
        # ps 中全部 PID 消失
        for 进程 in 节点表:
            self.assertFalse(查询进程存活(进程), f"PID {进程} 应已消失")
        # 临时目录已清理、端口已释放可重绑
        self.assertFalse(目录.exists(), "临时目录应已清理")
        self.assertTrue(self._端口可重绑(信息["端口"]), "端口应已释放可重绑")
        残留 = 检查残留(信息)
        self.assertTrue(残留["无残留"], f"应无残留: {残留}")

    def test_场景2_检查残留能发现存活树并在强杀后清空(self):
        """强杀前检查残留应发现 3 个存活 PID；强杀后无残留。"""
        self.进程组信息 = 启动进程树()
        信息 = self.进程组信息
        残留 = 检查残留(信息)
        self.assertFalse(残留["无残留"], "树存活时检查残留必须报告有残留")
        self.assertEqual(len(残留["存活pid表"]), 3, "存活树应有 3 个 PID")
        self.assertTrue(残留["目录仍存在"], "存活树工作目录应存在")
        self.assertTrue(残留["端口仍被占"], "存活树端口应被占用")
        报告 = 强杀进程组(信息)
        self.assertTrue(报告["成功"], f"强杀报告: {报告}")
        残留 = 检查残留(信息)
        self.assertTrue(残留["无残留"], f"强杀后应无残留: {残留}")

    def test_场景3_组长退出后进程组号仍能强杀孤儿(self):
        """组长自杀后子/孙成孤儿但仍留在原进程组；killpg(组号) 全部回收。"""
        self.进程组信息 = 启动进程树(模式="组长自杀")
        信息 = self.进程组信息
        组长, 子, 孙 = 信息["节点pid表"]
        # 组长已退出、子/孙仍存活（孤儿）
        for _ in range(100):
            if not 查询进程存活(组长):
                break
            time.sleep(0.1)
        self.assertFalse(查询进程存活(组长), "组长自杀模式组长应已退出")
        self.assertTrue(查询进程存活(子), "子进程应仍存活")
        self.assertTrue(查询进程存活(孙), "孙进程应仍存活")
        # 子/孙仍在原进程组：pgid 仍等于组长 PID（组长已死组不散）
        self.assertEqual(查询进程组号(子), 信息["进程组id"], "子进程应留在原进程组")
        self.assertEqual(查询进程组号(孙), 信息["进程组id"], "孙进程应留在原进程组")
        # 强杀进程组（组长已死，进程组号仍然有效）
        报告 = 强杀进程组(信息)
        self.assertTrue(报告["成功"], f"强杀报告: {报告}")
        for 进程 in (组长, 子, 孙):
            self.assertFalse(查询进程存活(进程), f"PID {进程} 应已消失")
        残留 = 检查残留(信息)
        self.assertTrue(残留["无残留"], f"应无残留: {残留}")

    def test_场景4_重复强杀幂等且不报错(self):
        """连续两次强杀同一进程组：第二次幂等成功，残留仍为空。"""
        self.进程组信息 = 启动进程树()
        信息 = self.进程组信息
        报告1 = 强杀进程组(信息)
        self.assertTrue(报告1["成功"], f"首次强杀报告: {报告1}")
        报告2 = 强杀进程组(信息)  # 重复强杀：进程组已不存在，应幂等
        self.assertTrue(报告2["成功"], f"重复强杀应幂等成功: {报告2}")
        self.assertEqual(报告2["未退出pid"], [], "重复强杀不应有未退出 PID")
        残留 = 检查残留(信息)
        self.assertTrue(残留["无残留"], f"重复强杀后应无残留: {残留}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
