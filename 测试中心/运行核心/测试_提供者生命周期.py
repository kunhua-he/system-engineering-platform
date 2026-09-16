"""提供者生命周期权威化测试（第三十阶段C3）。

覆盖：注册表/实际进程/依赖锁三方对齐、启动/停止/重启、超时取消、
崩溃后零残留（线程/进程/端口/临时目录/句柄）、隔离边界检查、
资源有界（进程数/日志）。全部真实独立进程（python 子进程）场景，
串行执行（并行数 0）。

说明：测试提供者目录放在临时目录，无第三方 pip 依赖（避免真实
venv 构建）；第三方目录 用 依赖锁.json 模拟"目录有记录"事实点。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时.进程终止 import 终止进程组
from 启动监督器.健康监督 import 系统提供者健康监督
from 运行核心.运行环境管理器.提供者生命周期 import 提供者生命周期管理器, 提供者路由
from 支持库.适配层.提供者注册表.提供者注册表 import 提供者注册表

测试能力id = "进程.最小操作"


def 创建提供者目录(父目录: Path, 名称: str, 依赖锁: dict | None = None) -> Path:
    """创建提供者目录；依赖锁非空时写入 依赖锁.json。"""
    目录 = 父目录 / 名称
    目录.mkdir(parents=True, exist_ok=True)
    if 依赖锁 is not None:
        (目录 / "依赖锁.json").write_text(
            json.dumps(依赖锁, ensure_ascii=False, indent=2), encoding="utf-8")
    return 目录


class 提供者生命周期测试(unittest.TestCase):
    """提供者生命周期权威化主测试（真实独立进程）。"""

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="提供者生命周期测试"))
        self.适配层根 = self.临时根 / "适配层"
        self.适配层根.mkdir()
        self.提供者A目录 = 创建提供者目录(self.适配层根, "测试提供者A")
        self.提供者B目录 = 创建提供者目录(self.适配层根, "测试提供者B")
        self.第三方X目录 = 创建提供者目录(self.适配层根, "第三方X提供者", {
            "包": [{"名称": "演示扩展", "版本": "1.0.0", "模块名": "演示扩展模块"}],
            "直接依赖": [{"名称": "演示扩展", "版本": "1.0.0"}],
        })
        self.注册表 = 提供者注册表()
        self.管理器 = 提供者生命周期管理器(self.适配层根, self.注册表)
        self.登记结果 = self.管理器.登记路由(
            提供者路由(提供者id="测试提供者A", 提供者目录=self.提供者A目录,
                      运行方式="系统解释器", 能力列表=[测试能力id]))

    def tearDown(self):
        self.管理器.清理全部()
        self.管理器.清理临时目录()
        shutil.rmtree(self.临时根, ignore_errors=True)

    # ---------- 三方对齐 ----------

    def test_扫描提供者路由_依赖锁为事实点(self):
        """只有含 依赖锁.json 的目录成为扫描路由（第三方事实点）。"""
        路由表 = self.管理器.扫描提供者路由()
        扫描id表 = [路由.提供者id for 路由 in 路由表]
        self.assertIn("第三方X提供者", 扫描id表)
        self.assertNotIn("测试提供者A", 扫描id表)  # 无锁目录不自动登记
        x路由 = next(路由 for 路由 in 路由表 if 路由.提供者id == "第三方X提供者")
        self.assertEqual(x路由.pip模块名表, ["演示扩展模块"])
        self.assertEqual(x路由.运行方式, "独立进程")
        self.assertTrue(x路由.依赖锁路径.is_file())

    def test_登记路由_幂等与能力冲突(self):
        """同目录重复登记幂等；同能力不同目录必须冲突失败。"""
        重复结果 = self.管理器.登记路由(
            提供者路由(提供者id="测试提供者A", 提供者目录=self.提供者A目录,
                      运行方式="系统解释器", 能力列表=[测试能力id]))
        self.assertTrue(重复结果.成功)
        # 另一提供者登记同一能力 → 注册表冲突（禁止运行时另选实现）
        冲突结果 = self.管理器.登记路由(
            提供者路由(提供者id="测试提供者B", 提供者目录=self.提供者B目录,
                      运行方式="系统解释器", 能力列表=[测试能力id]))
        self.assertFalse(冲突结果.成功)
        self.assertEqual(冲突结果.错误码, "提供者冲突")
        self.assertIn("禁止登记另一实现", 冲突结果.错误说明)

    def test_对齐核对_三方一致与严格检出(self):
        """登记后核对无问题；未登记含锁目录在严格模式检出。"""
        self.assertEqual(self.管理器.对齐核对(), [])
        问题列表 = self.管理器.对齐核对(严格=True)
        self.assertTrue(any("含依赖锁但未登记" in 问题 for 问题 in 问题列表))
        # 登记第三方X 后严格核对无问题
        登记x = self.管理器.登记路由(
            提供者路由(提供者id="第三方X提供者", 提供者目录=self.第三方X目录,
                      运行方式="独立进程", 能力列表=["演示.扩展能力"]))
        self.assertTrue(登记x.成功)
        self.assertEqual(self.管理器.对齐核对(严格=True), [])

    def test_对齐核对_登记目录缺失检出(self):
        """登记目录被删除 → 对齐核对检出，运行时不得继续选择。"""
        临时目录 = 创建提供者目录(self.适配层根, "测试提供者临时")
        登记 = self.管理器.登记路由(
            提供者路由(提供者id="测试提供者临时", 提供者目录=临时目录,
                      运行方式="系统解释器", 能力列表=["临时.能力"]))
        self.assertTrue(登记.成功)
        shutil.rmtree(临时目录)
        问题列表 = self.管理器.对齐核对()
        self.assertTrue(any("目录不存在" in 问题 for 问题 in 问题列表))

    def test_注册表获取路由与移除(self):
        """注册表路由事实点：获取/移除。"""
        路由结果 = self.注册表.获取路由(测试能力id)
        self.assertTrue(路由结果.成功)
        self.assertEqual(路由结果.值.提供者名称, "测试提供者A")
        移除 = self.注册表.移除路由(测试能力id)
        self.assertTrue(移除.成功)
        再次获取 = self.注册表.获取路由(测试能力id)
        self.assertFalse(再次获取.成功)

    # ---------- 生命周期 ----------

    def test_启动健康调用停止(self):
        """启动 → 健康 → 调用成功 → 停止 → 再启动可复用。"""
        成功, 消息 = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功, 消息)
        self.assertTrue(self.管理器.健康检查("测试提供者A"))
        结果 = self.管理器.调用能力("测试提供者A", 测试能力id, {"名称": "测试"})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, {"名称": "测试", "工作器": "真实子进程"})
        停止成功, 停止消息 = self.管理器.停止提供者("测试提供者A")
        self.assertTrue(停止成功, 停止消息)
        # 停止后未初始化调用明确失败
        停止后结果 = self.管理器.调用能力("测试提供者A", 测试能力id)
        self.assertFalse(停止后结果.成功)
        self.assertEqual(停止后结果.错误码, "外部不可访问")
        # 再启动（新进程）可调用
        成功2, 消息2 = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功2, 消息2)
        结果2 = self.管理器.调用能力("测试提供者A", 测试能力id, {"名称": "再测"})
        self.assertTrue(结果2.成功)
        self.assertEqual(结果2.值["名称"], "再测")

    def test_重复启动幂等(self):
        成功, 消息 = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功)
        再次成功, 再次消息 = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(再次成功)
        self.assertIn("已在运行", 再次消息)

    def test_重启提供者(self):
        成功, _ = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功)
        旧进程 = self.管理器._进程表["测试提供者A"]
        旧pid = 旧进程.进程.pid
        重启成功, 重启消息 = self.管理器.重启提供者("测试提供者A")
        self.assertTrue(重启成功, 重启消息)
        新进程 = self.管理器._进程表["测试提供者A"]
        self.assertNotEqual(新进程.进程.pid, 旧pid)
        结果 = self.管理器.调用能力("测试提供者A", 测试能力id, {"名称": "重启后"})
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["名称"], "重启后")

    def test_未登记提供者启动拒绝(self):
        成功, 消息 = self.管理器.启动提供者("不存在提供者")
        self.assertFalse(成功)
        self.assertIn("未登记", 消息)

    # ---------- 超时与取消 ----------

    def test_调用超时与管道排空(self):
        """超时返回 错误码=超时；滞留响应被排空，进程保持可用不串行。"""
        成功, _ = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功)
        超时结果 = self.管理器.调用能力(
            "测试提供者A", 测试能力id, {"名称": "慢操作"}, 超时秒=0.15)
        self.assertFalse(超时结果.成功)
        self.assertEqual(超时结果.错误码, "超时")
        # 等慢操作（0.3 秒）完成且响应滞留后再次调用：调用前排空防错位
        time.sleep(0.35)
        self.assertTrue(self.管理器.健康检查("测试提供者A"))
        结果 = self.管理器.调用能力(
            "测试提供者A", 测试能力id, {"名称": "慢操作"}, 超时秒=1.0)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["名称"], "慢操作")
        正常结果 = self.管理器.调用能力("测试提供者A", 测试能力id, {"名称": "正常"})
        self.assertTrue(正常结果.成功)
        self.assertEqual(正常结果.值["名称"], "正常")

    def test_取消调用(self):
        """取消事件触发 → 错误码=已取消；进程保持健康可继续调用。"""
        成功, _ = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功)
        取消事件 = threading.Event()
        结果盒: list = []

        def 执行调用():
            结果盒.append(self.管理器.调用能力(
                "测试提供者A", 测试能力id, {"名称": "慢操作"},
                超时秒=2.0, 取消事件=取消事件))

        线程 = threading.Thread(target=执行调用, daemon=True)
        线程.start()
        time.sleep(0.1)
        取消事件.set()
        线程.join(timeout=5.0)
        self.assertFalse(线程.is_alive())
        self.assertTrue(结果盒)
        self.assertFalse(结果盒[0].成功)
        self.assertEqual(结果盒[0].错误码, "已取消")
        # 取消后进程健康可继续调用（无残留、无错位）
        self.assertTrue(self.管理器.健康检查("测试提供者A"))
        结果 = self.管理器.调用能力("测试提供者A", 测试能力id, {"名称": "取消后"})
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["名称"], "取消后")

    def test_调用开始前取消(self):
        成功, _ = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功)
        取消事件 = threading.Event()
        取消事件.set()
        结果 = self.管理器.调用能力("测试提供者A", 测试能力id, {"名称": "测试"},
                                    取消事件=取消事件)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "已取消")

    # ---------- 崩溃重启与零残留 ----------

    def test_崩溃自动重启与零残留(self):
        """强杀子进程 → 崩溃检测自动重启（次数有界）→ 停止后零残留。"""
        成功, _ = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功)
        进程 = self.管理器._进程表["测试提供者A"]
        崩溃pid = 进程.进程.pid
        # 平台差异收口：强杀整组由 进程终止.终止进程组 负责
        终止进程组(崩溃pid, 信号="强杀")
        time.sleep(0.3)
        未恢复 = self.管理器.崩溃检测("测试提供者A")
        self.assertFalse(未恢复)  # 已自动重启恢复
        self.assertTrue(self.管理器.健康检查("测试提供者A"))
        结果 = self.管理器.调用能力("测试提供者A", 测试能力id, {"名称": "重启后"})
        self.assertTrue(结果.成功, 结果.错误说明)
        停止成功, _ = self.管理器.停止提供者("测试提供者A")
        self.assertTrue(停止成功)
        self.assertEqual(self.管理器.零残留核对(), [])
        统计 = self.管理器.资源统计()
        self.assertEqual(统计["运行中"], 0)
        self.assertEqual(统计["残留调用线程"], [])

    def test_崩溃后端口释放可重绑(self):
        """占用端口的子进程崩溃后端口必须释放可重绑（零残留）。"""
        端口 = self._空闲端口()
        监听脚本 = (
            "import socket, time;"
            f"s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
            f"s.bind(('127.0.0.1',{端口}));s.listen(1);time.sleep(60)"
        )
        子进程 = subprocess.Popen([sys.executable, "-c", 监听脚本])
        try:
            time.sleep(0.6)
            self.assertFalse(self._端口可重绑(端口))  # 被监听子进程占用
            终止进程组(子进程.pid, 信号="强杀")
            子进程.wait(timeout=5)
            time.sleep(0.3)
            self.assertTrue(self._端口可重绑(端口))  # 崩溃后端口已释放
        finally:
            if 子进程.poll() is None:
                终止进程组(子进程.pid, 信号="强杀")
                子进程.wait(timeout=5)

    def test_清理全部后零残留(self):
        """启动后 清理全部 → 进程/句柄/临时目录/线程零残留。"""
        成功, _ = self.管理器.启动提供者("测试提供者A")
        self.assertTrue(成功)
        残留目录 = self.临时根 / "登记残留目录"
        残留目录.mkdir(exist_ok=True)
        self.管理器.登记临时目录(残留目录)
        self.管理器.清理全部()
        self.assertEqual(self.管理器.零残留核对(), [])
        self.assertFalse(残留目录.exists())  # 登记临时目录已清理
        self.assertEqual(self.管理器.资源统计()["进程数"], 0)

    def _空闲端口(self) -> int:
        套接字 = socket.socket()
        try:
            套接字.bind(("127.0.0.1", 0))
            return 套接字.getsockname()[1]
        finally:
            套接字.close()

    def _端口可重绑(self, 端口: int) -> bool:
        套接字 = socket.socket()
        try:
            套接字.bind(("127.0.0.1", 端口))
            return True
        except OSError:
            return False
        finally:
            套接字.close()

    # ---------- 隔离边界 ----------

    def test_隔离边界_主进程不得导入第三方(self):
        """依赖锁 pip 包模块名不得在主进程 sys.modules；实现目录不得在 sys.path。"""
        登记x = self.管理器.登记路由(
            提供者路由(提供者id="第三方X提供者", 提供者目录=self.第三方X目录,
                      运行方式="独立进程", 能力列表=["演示.扩展能力"]))
        self.assertTrue(登记x.成功)
        self.assertEqual(self.管理器.检查隔离边界(), [])
        # 模拟主进程已导入第三方模块 → 检出
        假模块 = types.ModuleType("演示扩展模块")
        sys.modules["演示扩展模块"] = 假模块
        try:
            问题列表 = self.管理器.检查隔离边界()
            self.assertTrue(any("已在主进程导入" in 问题 for 问题 in 问题列表))
        finally:
            sys.modules.pop("演示扩展模块", None)
        # 模拟主进程 sys.path 含适配层实现目录 → 检出
        系统根 = Path(__file__).resolve().parents[2]
        适配层 = 系统根 / "支持库" / "适配层"
        sys.path.insert(0, str(适配层))
        try:
            问题列表 = self.管理器.检查隔离边界()
            self.assertTrue(any("sys.path 含提供者实现目录" in 问题
                                for 问题 in 问题列表))
        finally:
            sys.path.remove(str(适配层))
        self.assertEqual(self.管理器.检查隔离边界(), [])

    # ---------- 资源有界 ----------

    def test_进程数与日志有界(self):
        """进程数达上限拒绝启动；日志环形裁剪不超上限。"""
        管理器 = 提供者生命周期管理器(self.适配层根, self.注册表, 最大进程数=2)
        创建提供者目录(self.适配层根, "测试提供者C")
        管理器.登记路由(提供者路由(
            提供者id="测试提供者A", 提供者目录=self.提供者A目录,
            运行方式="系统解释器", 能力列表=[测试能力id]))
        管理器.登记路由(提供者路由(
            提供者id="测试提供者B", 提供者目录=self.提供者B目录,
            运行方式="系统解释器", 能力列表=["进程.其他操作"]))
        管理器.登记路由(提供者路由(
            提供者id="测试提供者C", 提供者目录=self.适配层根 / "测试提供者C",
            运行方式="系统解释器", 能力列表=["进程.第三操作"]))
        成功A, _ = 管理器.启动提供者("测试提供者A")
        成功B, _ = 管理器.启动提供者("测试提供者B")
        self.assertTrue(成功A)
        self.assertTrue(成功B)
        拒绝C, 消息C = 管理器.启动提供者("测试提供者C")
        self.assertFalse(拒绝C)
        self.assertIn("已达上限", 消息C)
        # 日志环形裁剪：超过日志上限不增长
        日志上限 = 管理器._日志上限
        for _序号 in range(日志上限 * 3):
            管理器._记录日志("测试提供者A", "有界日志行")
        self.assertLessEqual(len(管理器._日志表["测试提供者A"]), 日志上限)
        管理器.清理全部()

    # ---------- 启动监督器接线 ----------

    def test_健康监督汇入进程健康(self):
        """运行核心进程健康经 汇入进程健康 汇入启动监督器（不启线程）。"""
        证据文件 = self.临时根 / "健康证据.jsonl"
        监督 = 系统提供者健康监督(周期秒=1.0, 证据文件=证据文件,
                                  探针清单=[])  # 不探针，只验证汇入
        监督.汇入进程健康({
            "测试提供者A": {"健康": True, "成功": True, "版本": "模拟1.0.0"},
            "测试提供者B": {"健康": False, "成功": False, "错误码": "外部不可访问"},
        })
        查询 = 监督.查询健康状态()
        self.assertEqual(查询["提供者数"], 2)
        self.assertEqual(查询["健康提供者数"], 1)
        self.assertTrue(查询["提供者"]["测试提供者A"]["健康"])
        self.assertFalse(查询["提供者"]["测试提供者B"]["健康"])
        self.assertEqual(查询["提供者"]["测试提供者B"]["错误码"], "外部不可访问")
        self.assertFalse(监督.停止周期检查())  # 未启动周期线程


if __name__ == "__main__":
    unittest.main()
