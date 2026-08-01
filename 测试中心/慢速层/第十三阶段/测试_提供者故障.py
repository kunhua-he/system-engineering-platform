"""第十三阶段：外部提供者故障反向测试（真实故障注入，全部真实执行）。

5 个真实故障场景（禁止模拟）：
1. SQLite：写入后真实断开底层连接 → 自动重连 → 数据不丢（读写双路径）；
2. HTTP：真实杀掉监听套接字（服务崩溃）→ 有限重试 2 次后失败，绝不无限重试；
3. 进程：真实 SIGKILL 强杀子进程 → 自动重启有界（最多 2 次）且证据记录齐全；
4. 动态库：真实加载不存在的库 → 明确 HOST_UNAVAILABLE，禁止伪造成功；
5. PostgreSQL：无 DSN（PG_DSN 不存在）→ 明确 HOST_UNAVAILABLE。

运行：unset PYTHONPATH && python3.14 测试中心/第十三阶段/测试_提供者故障.py
"""
from __future__ import annotations

import os
import shutil
import signal
import sqlite3
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(系统根))

from 平台控制面.提供者.数据库提供者 import 数据库提供者
from 平台控制面.提供者.动态库提供者 import 调用 as 动态库调用, 宿主不可用状态 as 库宿主不可用
from 平台控制面.提供者.HTTP提供者 import HTTP提供者
from 平台控制面.提供者.PostgreSQL提供者 import PostgreSQL提供者, 错误码_宿主不可用
from 平台控制面.提供者.进程提供者 import 本地进程提供者, 最大重启次数

回显服务脚本 = """import json, os, sys
for 行 in sys.stdin:
    请求 = json.loads(行)
    标识 = 请求.get("请求id", "")
    if 请求.get("类型") == "关闭":
        print(json.dumps({"请求id": 标识, "成功": True, "值": "再见"}, ensure_ascii=False), flush=True)
        sys.exit(0)
    print(json.dumps({"请求id": 标识, "成功": True,
                      "值": {"回显": 请求.get("参数", {})}},
                     ensure_ascii=False), flush=True)
"""


class 测试_外部提供者故障反向注入(unittest.TestCase):
    """5 个真实故障场景：真实断开 / 真实崩溃 / 真实强杀 / 真实加载失败 / 真实无DSN。"""

    def test_数据库断开自动重连数据不丢(self):
        """场景1：写入后真实关闭底层连接（外部断开）→ 查询自动重连，数据不丢。"""
        目录 = Path(tempfile.mkdtemp(prefix="故障_数据库_"))
        提供者 = 数据库提供者(目录 / "故障库.db")
        try:
            self.assertTrue(提供者.连接()["成功"])
            提供者.执行("CREATE TABLE 用户(编号 INTEGER PRIMARY KEY, 姓名 TEXT)")
            提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(1, '华哥')")
            旧连接 = 提供者._连接
            旧连接.close()  # 真实故障注入：底层连接被外部断开，引用未清
            查询 = 提供者.查询("SELECT count(*) AS 总数 FROM 用户")
            self.assertTrue(查询["成功"], 查询["消息"])
            self.assertEqual(查询["结果"], [{"总数": 1}], "重连后数据必须不丢")
            self.assertIsNotNone(提供者._连接, "必须已建立新连接")
            self.assertIsNot(提供者._连接, 旧连接, "重连必须是全新连接")
            # 写路径同样自动重连：断开后继续写入，新老数据都在
            提供者._连接.close()
            写入 = 提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(2, '故障注入后')")
            self.assertTrue(写入["成功"], 写入["消息"])
            self.assertEqual(提供者.查询("SELECT count(*) AS 总数 FROM 用户")["结果"],
                             [{"总数": 2}])
            # 独立连接验证磁盘落盘事实：重连不是丢了数据重建空库
            验证 = sqlite3.connect(str(目录 / "故障库.db"))
            try:
                self.assertEqual(验证.execute("SELECT count(*) FROM 用户").fetchone()[0], 2)
            finally:
                验证.close()
        finally:
            提供者.关闭()
            shutil.rmtree(目录, ignore_errors=True)

    def test_HTTP服务崩溃有限重试不无限重试(self):
        """场景2：真实杀掉监听套接字（服务崩溃）→ 有限重试 2 次后失败，不无限重试。"""
        提供者 = HTTP提供者(重试次数=2, 重试退避基数=0.05)
        提供者.启动(lambda 路径, 方法, 请求体: (200, "正常".encode("utf-8"), {}))
        try:
            self.assertTrue(提供者.请求("/健康")["成功"], "崩溃前必须正常服务")
            提供者._服务.server_close()  # 真实故障注入：监听套接字被外部关闭，服务崩溃
            time.sleep(0.2)
            开始 = time.monotonic()
            结果 = 提供者.请求("/健康")
            耗时 = time.monotonic() - 开始
            self.assertFalse(结果["成功"], "服务崩溃后请求必须失败")
            self.assertEqual(结果["重试次数"], 2, "重试次数必须严格等于上限")
            self.assertIn("重试", 结果["错误"])
            self.assertLess(耗时, 3.0, f"必须有限重试后停止，实际耗时 {耗时:.2f} 秒")
        finally:
            提供者.停止()

    def test_进程真实强杀自动重启有界且证据记录(self):
        """场景3：真实 SIGKILL 强杀子进程 → 自动重启有界（最多 2 次）且证据齐全。"""
        python路径 = shutil.which("python3.14") or sys.executable
        提供者 = 本地进程提供者([python路径, "-c", 回显服务脚本], 调用超时秒=2.0)
        self.assertTrue(提供者.启动()["成功"])
        旧pid = 提供者.状态()["pid"]
        self.assertTrue(提供者.调用({"参数": {"序号": 1}})["成功"])
        os.kill(旧pid, signal.SIGKILL)  # 真实强杀
        time.sleep(0.2)
        响应 = 提供者.调用({"参数": {"序号": 2}})  # 崩溃自动重启后重试
        self.assertTrue(响应["成功"], 响应)
        状态 = 提供者.状态()
        self.assertEqual(状态["重启次数"], 1)
        self.assertNotEqual(状态["pid"], 旧pid, "重启后必须是新进程")
        # 第二次强杀：仍自动重启（重启次数 2，达到上限）
        os.kill(状态["pid"], signal.SIGKILL)
        time.sleep(0.2)
        self.assertTrue(提供者.调用({"参数": {"序号": 3}})["成功"])
        self.assertEqual(提供者.状态()["重启次数"], 2)
        # 第三次强杀：超出上限，返回崩溃且不再重启
        os.kill(提供者.状态()["pid"], signal.SIGKILL)
        time.sleep(0.2)
        最后 = 提供者.调用({"参数": {"序号": 4}})
        self.assertFalse(最后["成功"])
        self.assertEqual(最后["错误码"], "崩溃")
        状态 = 提供者.状态()
        self.assertEqual(状态["重启次数"], 最大重启次数, "自动重启必须有界")
        self.assertEqual(状态["状态"], "故障")
        # 证据记录：3 条退出证据（退出码 -9/信号 9/时间）+ 2 条重启证据（次数 1、2）
        退出表 = [证据 for 证据 in 状态["证据列表"] if 证据["类型"] == "退出"]
        重启表 = [证据 for 证据 in 状态["证据列表"] if 证据["类型"] == "重启"]
        self.assertEqual(len(退出表), 3, "每次崩溃必须记录退出证据")
        for 证据 in 退出表:
            self.assertEqual(证据["退出码"], -signal.SIGKILL)
            self.assertEqual(证据["信号"], signal.SIGKILL)
            self.assertIn("时间", 证据)
        self.assertEqual([证据["次数"] for 证据 in 重启表], [1, 2])
        提供者.关闭()  # 进程已死，关闭幂等

    def test_动态库加载不存在库返回宿主不可用(self):
        """场景4：真实加载不存在的库 → 明确 HOST_UNAVAILABLE，禁止伪造成功。"""
        self.assertEqual(库宿主不可用, "HOST_UNAVAILABLE")
        结果 = 动态库调用("绝对不存在的动态库xyz", "某函数", [])
        self.assertFalse(结果.成功, "不存在的库不得伪装成功")
        self.assertEqual(结果.错误码, "HOST_UNAVAILABLE")
        self.assertTrue(结果.错误说明, "必须给出中文错误说明")

    def test_PostgreSQL无DSN返回宿主不可用(self):
        """场景5：PG_DSN 不存在（无连接串）→ 明确 HOST_UNAVAILABLE，禁止伪造成功。"""
        self.assertEqual(错误码_宿主不可用, "HOST_UNAVAILABLE")
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            提供者 = PostgreSQL提供者(连接串=None)  # 走环境变量默认路径：无 DSN
            检测 = 提供者.检测()
            self.assertFalse(检测.成功, "无 DSN 时禁止伪造成功")
            self.assertEqual(检测.错误码, "HOST_UNAVAILABLE")
            self.assertIn("宿主不可用", 检测.错误说明)
            self.assertIn("驱动表", 检测.详情)
            打开 = 提供者.打开连接()
            self.assertFalse(打开.成功)
            self.assertEqual(打开.错误码, "HOST_UNAVAILABLE")
        # 显式空连接串同样必须宿主不可用
        空串提供者 = PostgreSQL提供者(连接串="")
        self.assertEqual(空串提供者.检测().错误码, "HOST_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
