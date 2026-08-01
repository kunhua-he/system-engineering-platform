"""第十三阶段：本地进程真实提供者测试（四个真实场景，全部真实子进程）。

1. 真实 python3.14 -c 子进程回显服务 → 真实调用返回（值/请求id/工作目录/超时）
2. 真实 kill 子进程 → 退出证据（退出码 -9/信号 9）→ 自动重启 → 再次调用成功
3. 连续真实强杀 → 崩溃自动重启有界（最多 2 次）→ 超出后返回崩溃、3 条退出证据
4. 关闭后进程消失（os.kill(pid,0) 与 ps 双重检查）、优雅退出码 0 证据
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.提供者.进程提供者 import 本地进程提供者

回显服务脚本 = """import json, os, sys, time
for 行 in sys.stdin:
    请求 = json.loads(行)
    标识 = 请求.get("请求id", "")
    类型 = 请求.get("类型", "")
    if 类型 == "关闭":
        print(json.dumps({"请求id": 标识, "成功": True, "值": "再见"}, ensure_ascii=False), flush=True)
        sys.exit(0)
    参数 = 请求.get("参数", {}) if isinstance(请求.get("参数"), dict) else {}
    延迟 = 参数.get("延迟秒", 0)
    if 延迟:
        time.sleep(延迟)
    print(json.dumps({"请求id": 标识, "成功": True,
                      "值": {"回显": 参数, "工作目录": os.getcwd()},
                      "错误码": "", "错误说明": ""}, ensure_ascii=False), flush=True)
"""


class 测试_本地进程真实提供者(unittest.TestCase):
    """四个真实场景：真实 python3.14 子进程 + 真实 JSON 行通信 + 真实强杀。"""

    @classmethod
    def setUpClass(cls):
        cls.python路径 = shutil.which("python3.14") or sys.executable
        cls.临时目录 = tempfile.TemporaryDirectory()
        cls.命令表 = [cls.python路径, "-c", 回显服务脚本]

    @classmethod
    def tearDownClass(cls):
        cls.临时目录.cleanup()

    def test_真实启动与调用返回(self):
        提供者 = 本地进程提供者(self.命令表, 工作目录=self.临时目录.name, 调用超时秒=2.0)
        结果 = 提供者.启动()
        self.assertTrue(结果["成功"], 结果)
        pid = 提供者.状态()["pid"]
        os.kill(pid, 0)  # 真实进程存在（不存在会抛 ProcessLookupError）
        self.assertEqual(提供者.状态()["状态"], "运行中")
        请求id = "回显-001"
        响应 = 提供者.调用({"请求id": 请求id, "参数": {"文本": "你好"}}, 超时秒=3.0)
        self.assertTrue(响应["成功"], 响应)
        self.assertEqual(响应["请求id"], 请求id)  # JSON 行协议请求/响应同 id
        self.assertEqual(响应["值"]["回显"]["文本"], "你好")  # 真实回显值
        self.assertEqual(响应["值"]["工作目录"], os.path.realpath(self.临时目录.name))  # 工作目录真实生效
        # 真实超时：子进程延迟 3 秒响应，超时秒 1 → 超时错误
        响应 = 提供者.调用({"参数": {"延迟秒": 3}}, 超时秒=1.0)
        self.assertFalse(响应["成功"])
        self.assertEqual(响应["错误码"], "超时")
        提供者.关闭()

    def test_真实强杀后自动重启再次调用成功(self):
        提供者 = 本地进程提供者(self.命令表, 调用超时秒=2.0)
        self.assertTrue(提供者.启动()["成功"])
        旧pid = 提供者.状态()["pid"]
        self.assertTrue(提供者.调用({"参数": {"序号": 1}})["成功"])
        os.kill(旧pid, signal.SIGKILL)  # 真实强杀子进程
        time.sleep(0.2)
        响应 = 提供者.调用({"参数": {"序号": 2}})  # 崩溃自动重启后再次调用
        self.assertTrue(响应["成功"], 响应)
        self.assertEqual(响应["值"]["回显"]["序号"], 2)
        状态 = 提供者.状态()
        self.assertEqual(状态["重启次数"], 1)
        self.assertNotEqual(状态["pid"], 旧pid)  # 重启后是新进程
        退出证据 = [证据 for 证据 in 状态["证据列表"] if 证据["类型"] == "退出"][-1]
        self.assertEqual(退出证据["退出码"], -signal.SIGKILL)  # 退出码 -9
        self.assertEqual(退出证据["信号"], signal.SIGKILL)  # 信号 9
        self.assertIn("时间", 退出证据)  # 退出时间已写证据
        提供者.关闭()

    def test_崩溃自动重启有界两次后不再重启(self):
        提供者 = 本地进程提供者(self.命令表, 调用超时秒=2.0)
        self.assertTrue(提供者.启动()["成功"])
        最后响应 = None
        for 序号 in (1, 2, 3):
            os.kill(提供者.状态()["pid"], signal.SIGKILL)
            time.sleep(0.15)
            最后响应 = 提供者.调用({"参数": {"序号": 序号}})
        self.assertFalse(最后响应["成功"])
        self.assertEqual(最后响应["错误码"], "崩溃")
        状态 = 提供者.状态()
        self.assertEqual(状态["重启次数"], 2)  # 有界：最多自动重启 2 次
        self.assertEqual(状态["状态"], "故障")
        退出列表 = [证据 for 证据 in 状态["证据列表"] if 证据["类型"] == "退出"]
        self.assertEqual(len(退出列表), 3)  # 三次崩溃三条退出证据
        提供者.关闭()  # 进程已死，关闭幂等

    def test_关闭后进程消失ps检查(self):
        提供者 = 本地进程提供者(self.命令表, 调用超时秒=2.0)
        self.assertTrue(提供者.启动()["成功"])
        pid = 提供者.状态()["pid"]
        self.assertTrue(提供者.调用({"参数": {"文本": "关闭前"}})["成功"])
        结果 = 提供者.关闭()
        self.assertTrue(结果["成功"], 结果)
        状态 = 提供者.状态()
        self.assertEqual(状态["状态"], "已停止")
        退出证据 = [证据 for 证据 in 状态["证据列表"] if 证据["类型"] == "退出"][-1]
        self.assertEqual(退出证据["退出码"], 0)  # 优雅关闭退出码 0
        # ps 检查一：信号探测进程已消失
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        # ps 检查二：ps 输出不再包含该 pid
        输出 = subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True).stdout
        self.assertNotIn(str(pid), 输出)


if __name__ == "__main__":
    unittest.main(verbosity=2)
