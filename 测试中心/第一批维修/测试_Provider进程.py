"""第一批维修：Provider 进程池、stderr 消费与关闭收敛边界。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时.进程终止 import 进程存活, 终止进程组
# 2026-09-23 补漏：`tearDown` 的 except 分支调 `记录忽略`，但本模块此前**只有**工作器源码
# 字符串（`工作器源码` 内那句）里有这个名字 —— 模块级从未 import ⇒ 一旦真有关闭异常，
# tearDown 自己抛 NameError，把「允许忽略但必须留痕」变成「连测试都收不了尾」。
from 公共契约.诊断.忽略记录 import 记录忽略, 忽略快照
from 平台控制面.提供者.进程提供者 import 本地进程提供者
from 运行核心.加载器.提供者隔离.独立进程 import 提供者进程池

工作器源码 = r'''
import json, os, signal, subprocess, sys, time
# 父进程经 argv[1] 显式传入系统根（-S 模式下无 site，须自行注入才能 import 公共契约）——
# 与生产工作器 运行核心/加载器/提供者隔离/进程工作器.py 的启动协议一致。
if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])
from 公共契约.诊断.忽略记录 import 记录忽略
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("READY", flush=True)
for 行 in sys.stdin:
    请求 = json.loads(行)
    类型 = 请求.get("类型")
    请求id = 请求.get("请求id")
    if 类型 == "健康":
        print(json.dumps({"请求id": 请求id, "成功": True, "值": "健康"}, ensure_ascii=False), flush=True)
        continue
    if 类型 in ("关闭", "停止"):
        print(json.dumps({"请求id": 请求id, "成功": True, "值": "已确认但继续运行"}, ensure_ascii=False), flush=True)
        continue
    参数 = 请求.get("参数") or {}
    子进程pid = None
    if 参数.get("生成子进程"):
        子进程 = subprocess.Popen([sys.executable, "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
        子进程pid = 子进程.pid
    for _ in range(int(参数.get("stderr块数", 0))):
        os.write(2, b"x" * 4096)
    time.sleep(float(参数.get("延迟秒", 0)))
    print(json.dumps({"请求id": 请求id, "成功": True,
                      "值": {"令牌": 参数.get("令牌"), "pid": os.getpid(), "子进程pid": 子进程pid},
                      "错误码": "", "错误说明": ""}, ensure_ascii=False), flush=True)
'''

正常关闭工作器源码 = r'''
import json, os, signal, subprocess, sys, time
print("READY", flush=True)
for 行 in sys.stdin:
    请求 = json.loads(行); 类型 = 请求.get("类型"); 请求id = 请求.get("请求id")
    if 类型 == "健康":
        print(json.dumps({"请求id": 请求id, "成功": True}), flush=True); continue
    if 类型 in ("关闭", "停止"):
        print(json.dumps({"请求id": 请求id, "成功": True}), flush=True); sys.exit(0)
    子进程 = subprocess.Popen([sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
    print(json.dumps({"请求id": 请求id, "成功": True,
                      "值": {"子进程pid": 子进程.pid}}, ensure_ascii=False), flush=True)
'''


def 并发调用(函数, 数量: int = 9):
    结果表 = [None] * 数量
    线程表 = []
    for 序号 in range(数量):
        线程 = threading.Thread(target=lambda i=序号: 结果表.__setitem__(i, 函数(i)))
        线程表.append(线程)
        线程.start()
    for 线程 in 线程表:
        线程.join(8)
    return 结果表


class Provider进程维修测试(unittest.TestCase):
    def setUp(self):
        self.临时对象 = tempfile.TemporaryDirectory(prefix="Provider进程维修_")
        self.工作器 = Path(self.临时对象.name) / "工作器.py"
        self.工作器.write_text(工作器源码, encoding="utf-8")
        self.对象表 = []

    def tearDown(self):
        for 对象 in self.对象表:
            try:
                对象.重试关闭()
            except Exception as 错误:  # 允许忽略，但留痕（哲学第 3 条 2 项）
                记录忽略('测试_Provider进程.tearDown', 错误)
        self.临时对象.cleanup()

    def _运行核心池(self, 池大小=3):
        池 = 提供者进程池("运行核心池", 池大小=池大小, 工作器路径=self.工作器,
                         启动超时秒=2.0, 调用超时秒=1.0)
        self.对象表.append(池)
        self.assertTrue(池.启动()[0])
        return 池

    def _控制面池(self, 池大小=3):
        池 = 本地进程提供者([sys.executable, "-S", str(self.工作器), str(系统根)],
                         池大小=池大小, 启动超时秒=2.0, 调用超时秒=1.0)
        self.对象表.append(池)
        self.assertTrue(池.启动()["成功"])
        return 池

    def test_P0_07_运行核心有界池稳定分配且并发不串包(self):
        池 = self._运行核心池()
        资源键表 = ["资源-1", "资源-3", "资源-0"]
        开始 = time.monotonic()
        结果表 = 并发调用(lambda i: 池.调用(
            能力id="测试.回显", 参数={"令牌": f"令牌-{i}", "延迟秒": 0.15},
            资源键=资源键表[i % 3]))
        耗时 = time.monotonic() - 开始
        self.assertEqual([项.值["令牌"] for 项 in 结果表], [f"令牌-{i}" for i in range(9)])
        资源pid表 = [{结果表[i].值["pid"] for i in range(余数, 9, 3)} for 余数 in range(3)]
        self.assertTrue(all(len(pid集) == 1 for pid集 in 资源pid表), "同一资源键必须稳定落到同一成员")
        self.assertEqual(len(set().union(*资源pid表)), 3, "三个资源键应由三个独立成员并行承载")
        self.assertLess(耗时, 0.9, "请求不应被一个全局通信锁全部串行")
        状态 = 池.状态()
        self.assertEqual(状态["池大小"], 3)
        self.assertEqual(len(set(状态["资源分配"].values())), 3)
        self.assertLessEqual(len(状态["成员表"]), 3)

    def test_P0_07_控制面有界池稳定分配且并发不串包(self):
        池 = self._控制面池()
        资源键表 = ["资源-1", "资源-3", "资源-0"]
        开始 = time.monotonic()
        结果表 = 并发调用(lambda i: 池.调用({
            "类型": "调用", "资源键": 资源键表[i % 3],
            "参数": {"令牌": f"令牌-{i}", "延迟秒": 0.15}}))
        耗时 = time.monotonic() - 开始
        self.assertEqual([项["值"]["令牌"] for 项 in 结果表], [f"令牌-{i}" for i in range(9)])
        资源pid表 = [{结果表[i]["值"]["pid"] for i in range(余数, 9, 3)} for 余数 in range(3)]
        self.assertTrue(all(len(pid集) == 1 for pid集 in 资源pid表), "同一资源键必须稳定落到同一成员")
        self.assertEqual(len(set().union(*资源pid表)), 3, "三个资源键应由三个独立成员并行承载")
        self.assertLess(耗时, 0.9, "请求不应被一个全局通信锁全部串行")
        状态 = 池.状态()
        self.assertEqual(状态["池大小"], 3)
        self.assertEqual(len(set(状态["资源分配"].values())), 3)

    def test_P0_13_两套Provider持续有界消费stderr洪水不死锁(self):
        运行池 = self._运行核心池(1)
        控制池 = self._控制面池(1)
        运行结果 = 运行池.调用(能力id="测试.洪水", 参数={"令牌": "运行", "stderr块数": 256}, 资源键="洪水")
        控制结果 = 控制池.调用({"类型": "调用", "资源键": "洪水",
                              "参数": {"令牌": "控制", "stderr块数": 256}})
        self.assertTrue(运行结果.成功, 运行结果.错误说明)
        self.assertTrue(控制结果["成功"], 控制结果)
        self.assertLessEqual(len(运行池.状态()["成员表"][0]["stderr日志"]), 200)
        self.assertLessEqual(len(控制池.状态()["成员表"][0]["stderr日志"]), 200)

    def test_P0_14_忽略TERM后KILL并确认进程管道线程收敛(self):
        运行池, 控制池 = self._运行核心池(1), self._控制面池(1)
        运行子pid = 运行池.调用(
            能力id="测试.子进程", 参数={"生成子进程": True}, 资源键="进程组").值["子进程pid"]
        控制子pid = 控制池.调用({
            "类型": "调用", "资源键": "进程组", "参数": {"生成子进程": True}})["值"]["子进程pid"]
        for 池, 子pid in ((运行池, 运行子pid), (控制池, 控制子pid)):
            pid表 = list(池.状态()["pid表"])
            结果 = 池.关闭()
            self.assertTrue(结果["成功"], 结果)
            self.assertTrue(结果["已使用SIGKILL"], 结果)
            self.assertEqual(结果["未收敛"], [])
            for pid in pid表:
                self.assertFalse(进程存活(pid), f"关闭成功后进程 {pid} 应已消失")
            self.assertFalse(进程存活(子pid), "关闭成功前必须确认同组子进程也已退出")

    def test_P0_13_控制面健康握手失败不泄漏进程管道线程(self):
        哑工作器 = Path(self.临时对象.name) / "哑工作器.py"
        哑工作器.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        提供者 = 本地进程提供者([sys.executable, "-S", str(哑工作器), str(系统根)],
                            启动超时秒=0.1, 调用超时秒=0.1)
        self.对象表.append(提供者)
        结果 = 提供者.启动()
        self.assertFalse(结果["成功"])
        pid = 提供者.状态()["pid"]
        self.assertIsNotNone(pid)
        self.assertFalse(进程存活(pid), "健康握手失败必须回收刚启动的进程")
        self.assertEqual(提供者._核对资源收敛(), [])

    def test_P0_14_组长正常退出也必须回收同组子进程(self):
        工作器 = Path(self.临时对象.name) / "正常关闭工作器.py"
        工作器.write_text(正常关闭工作器源码, encoding="utf-8")
        运行池 = 提供者进程池("正常退出运行池", 池大小=1, 工作器路径=工作器,
                          启动超时秒=1.0, 调用超时秒=0.2)
        控制池 = 本地进程提供者([sys.executable, "-S", str(工作器), str(系统根)],
                           池大小=1, 启动超时秒=1.0, 调用超时秒=0.2)
        self.对象表.extend((运行池, 控制池))
        self.assertTrue(运行池.启动()[0])
        self.assertTrue(控制池.启动()["成功"])
        子pid表 = [
            运行池.调用(能力id="测试.子孙", 资源键="子孙").值["子进程pid"],
            控制池.调用({"类型": "调用", "资源键": "子孙"})["值"]["子进程pid"],
        ]
        for 池, 子pid in zip((运行池, 控制池), 子pid表):
            try:
                结果 = 池.关闭()
                self.assertTrue(结果["成功"], 结果)
                self.assertFalse(进程存活(子pid), "组长退出不等于进程组已收敛")
            finally:
                终止进程组(子pid, 信号="强杀")

    def test_P0_14_无法收敛返回统一失败保留账本并可重试(self):
        for 池 in (self._运行核心池(1), self._控制面池(1)):
            原核对 = 池._核对资源收敛
            调用次数 = 0

            def 首次失败():
                nonlocal 调用次数
                调用次数 += 1
                return ["模拟读取线程仍存活"] if 调用次数 == 1 else 原核对()

            with patch.object(池, "_核对资源收敛", side_effect=首次失败):
                首次 = 池.关闭()
                self.assertFalse(首次["成功"])
                self.assertIn(首次["错误码"], ("资源未收敛", "资源释放失败"))
                self.assertTrue(首次["可重试"])
                self.assertTrue(首次["未收敛"])
                self.assertTrue(池.状态()["关闭账本"])
                再次 = 池.重试关闭()
                self.assertTrue(再次["成功"], 再次)
                self.assertEqual(再次["未收敛"], [])


class 关闭留痕分支回归(unittest.TestCase):
    """`tearDown` 的「允许忽略但必须留痕」分支必须真能跑。

    2026-09-23 复核：本模块的 `记录忽略` 只出现在 `工作器源码` 那个 `r'''…'''`
    字符串里（给子进程用的），**模块级从未 import** ⇒ 只要 `重试关闭()` 真抛异常，
    tearDown 自己就抛 `NameError: name '记录忽略' is not defined`：本意是「留痕后继续收尾」，
    实际变成「收不了尾」，且异常发生在 tearDown 里会连带掩盖真实用例结果。
    既有用例从未让 `重试关闭` 抛异常（失败分支测的是返回字典，不是异常），故长期潜伏。
    """

    def test_tearDown关闭异常必须留痕而非抛NameError(self):
        用例 = Provider进程维修测试("test_P0_07_运行核心有界池稳定分配且并发不串包")
        用例.setUp()
        前置条数 = len(忽略快照())

        class 假池:
            def 重试关闭(self):
                raise RuntimeError("模拟关闭失败")

        用例.对象表.append(假池())
        try:
            用例.tearDown()          # 改前：此处 NameError；改后：正常收尾
        finally:
            用例.临时对象.cleanup()

        新增 = 忽略快照()[前置条数:]
        命中 = [条 for 条 in 新增 if 条["位置"] == "测试_Provider进程.tearDown"]
        self.assertTrue(命中, f"tearDown 的关闭异常没有留痕：新增记录={新增}")
        self.assertEqual("RuntimeError", 命中[-1]["错误类型"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
