"""后台作业系统：提交即返回、线程池执行、终态收敛、尽力取消、原子落盘与重启收敛。

测试全程用临时隔离存储目录（不复用真实 工程缓存/作业状态/作业.jsonl）。
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from MCP工具箱.作业系统 import (
    作业系统, 是否终态, 状态_等待中, 状态_运行中, 状态_成功, 状态_失败,
    状态_已取消, 状态_崩溃,
)


def _提交(系统: 作业系统, 工具名: str, 参数: dict | None = None) -> str:
    return 系统.提交(工具名, 参数 or {})["作业id"]


def _直到(条件, 超时: float = 5.0, 消息: str = "条件未满足") -> None:
    """轮询到条件成立；超时即断言失败，避免测试挂死。"""
    截止 = time.monotonic() + 超时
    while time.monotonic() < 截止:
        if 条件():
            return
        time.sleep(0.01)
    raise AssertionError(消息)


def _等待终态(系统: 作业系统, 作业id: str, 超时: float = 5.0):
    直到终态 = lambda: 是否终态(系统.查询(作业id).状态)
    _直到(直到终态, 超时, f"作业 {作业id} 超时未到终态：{系统.查询(作业id).状态}")
    return 系统.查询(作业id)


def _等到状态(系统: 作业系统, 作业id: str, 目标: str, 超时: float = 5.0) -> None:
    _直到(lambda: 系统.查询(作业id).状态 == 目标, 超时,
          f"作业 {作业id} 超时未进入 {目标}：{系统.查询(作业id).状态}")


class 作业系统测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        self.存储目录 = Path(self._临时.name) / "作业状态"

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _建系统(self, **参数) -> 作业系统:
        return 作业系统(存储目录=self.存储目录, **参数)

    # ── 提交与执行 ─────────────────────────────────────────────────────

    def test_提交立即返回且结果可查回(self) -> None:
        开工 = threading.Event()
        系统 = self._建系统()

        def 慢活(工具名: str, 参数: dict) -> dict:
            开工.wait(3.0)
            return {"成功": True, "回执": f"{工具名} 干完了"}

        系统.设置执行器(慢活)
        快照 = 系统.提交("run_release_gate", {"包目录": "支持库/文本处理"})
        # 提交当场返回：返回的是快照，不带头结果，后续线程改状态不会污染它
        # （干活线程可能已抢先把状态翻成「运行中」，快照取值两者皆合法，但必非终态）
        self.assertIn(快照["状态"], {状态_等待中, 状态_运行中})
        self.assertTrue(快照["作业id"])
        self.assertNotIn("结果", 快照)
        self.assertEqual(系统.活动数(), 1)

        在跑 = 系统.查询(快照["作业id"])
        self.assertIn(在跑.状态, {状态_等待中, 状态_运行中})
        self.assertFalse(是否终态(在跑.状态))

        开工.set()
        完成 = _等待终态(系统, 快照["作业id"])
        self.assertEqual(完成.状态, 状态_成功)
        self.assertEqual(完成.结果["回执"], "run_release_gate 干完了")
        self.assertEqual(系统.活动数(), 0)
        系统.关闭()

    def test_运行中视图带已运行秒(self) -> None:
        开工 = threading.Event()
        系统 = self._建系统()
        系统.设置执行器(lambda 工具名, 参数: 开工.wait(3.0) or {"成功": True})
        作业id = _提交(系统, "verify_and_record")
        _等到状态(系统, 作业id, 状态_运行中)
        time.sleep(0.02)
        视图 = 系统.视图(系统.查询(作业id))
        self.assertIn("已运行秒", 视图)
        self.assertGreaterEqual(视图["已运行秒"], 0.0)
        开工.set()
        _等待终态(系统, 作业id)
        系统.关闭()

    def test_执行器抛异常判失败并带异常类名(self) -> None:
        系统 = self._建系统()

        def 炸了(工具名: str, 参数: dict) -> dict:
            raise RuntimeError("子进程起不来")

        系统.设置执行器(炸了)
        完成 = _等待终态(系统, _提交(系统, "run_release_gate"))
        self.assertEqual(完成.状态, 状态_失败)
        self.assertEqual(完成.错误码, "RuntimeError")
        self.assertIn("子进程起不来", 完成.错误说明)
        系统.关闭()

    def test_执行器返回失败字典判失败(self) -> None:
        系统 = self._建系统()
        系统.设置执行器(lambda 工具名, 参数: {
            "成功": False, "错误码": "参数无效", "错误说明": "模块名必填",
        })
        完成 = _等待终态(系统, _提交(系统, "validate_module_compliance", {"模块名": ""}))
        self.assertEqual(完成.状态, 状态_失败)
        self.assertEqual(完成.错误码, "参数无效")
        self.assertEqual(完成.错误说明, "模块名必填")
        系统.关闭()

    def test_参数在执行前被清出内存(self) -> None:
        系统 = self._建系统()
        系统.设置执行器(lambda 工具名, 参数: {"成功": True})
        作业id = _提交(系统, "verify_and_record", {"命令": ["python", "-c", "pass"]})
        _等待终态(系统, 作业id)
        self.assertNotIn(作业id, 系统.参数表)
        系统.关闭()

    # ── 取消 ───────────────────────────────────────────────────────────

    def test_未开始作业可被真取消(self) -> None:
        堵住 = threading.Event()
        系统 = self._建系统(最大并发数=1)
        系统.设置执行器(lambda 工具名, 参数: 堵住.wait(3.0) or {"成功": True})

        先头 = _提交(系统, "run_release_gate")
        _等到状态(系统, 先头, 状态_运行中)
        排队 = _提交(系统, "validate_module_compliance")
        self.assertEqual(系统.查询(排队).状态, 状态_等待中)

        成功, 说明 = 系统.取消(排队)
        self.assertTrue(成功)
        self.assertEqual(系统.查询(排队).状态, 状态_已取消)
        self.assertIn("未开始", 说明)
        # 线程没启动，_执行 的 finally 清不到这份参数；也不该再留着 Future
        self.assertNotIn(排队, 系统.参数表)
        self.assertNotIn(排队, 系统.未来表)

        堵住.set()
        _等待终态(系统, 先头)
        系统.关闭()

    def test_运行中取消只标记并丢弃产出(self) -> None:
        开工 = threading.Event()
        放行 = threading.Event()

        def 慢活(工具名: str, 参数: dict) -> dict:
            开工.set()
            放行.wait(3.0)
            return {"成功": True, "回执": "其实跑完了"}

        系统 = self._建系统()
        系统.设置执行器(慢活)
        作业id = _提交(系统, "run_release_gate")
        开工.wait(3.0)

        成功, 说明 = 系统.取消(作业id)
        self.assertTrue(成功)
        self.assertIn("运行中", 说明)

        放行.set()
        完成 = _等待终态(系统, 作业id)
        self.assertEqual(完成.状态, 状态_已取消)
        self.assertEqual(完成.结果, {"成功": True, "回执": "其实跑完了"})
        self.assertIn("丢弃", 完成.错误说明)
        系统.关闭()

    def test_取消已是终态作业幂等(self) -> None:
        系统 = self._建系统()
        系统.设置执行器(lambda 工具名, 参数: {"成功": True})
        作业id = _提交(系统, "run_release_gate")
        _等待终态(系统, 作业id)
        成功, 说明 = 系统.取消(作业id)
        self.assertTrue(成功)
        self.assertIn(状态_成功, 说明)
        系统.关闭()

    def test_取消未知作业id返回失败(self) -> None:
        系统 = self._建系统()
        系统.设置执行器(lambda 工具名, 参数: {"成功": True})
        成功, 说明 = 系统.取消("查无此作业")
        self.assertFalse(成功)
        self.assertIn("未知作业id", 说明)
        系统.关闭()

    # ── 拒绝与边界 ─────────────────────────────────────────────────────

    def test_空工具名与未注入执行器被拒(self) -> None:
        系统 = self._建系统()
        with self.assertRaises(ValueError):
            系统.提交("   ")
        with self.assertRaises(ValueError):
            系统.提交("run_release_gate")  # 还没注入执行器

    def test_作业工具不可嵌套提交(self) -> None:
        系统 = self._建系统()
        系统.设置执行器(lambda 工具名, 参数: {"成功": True})
        for 工具名 in ("tool_job_submit", "tool_job_query", "tool_job_cancel"):
            with self.assertRaises(ValueError):
                系统.提交(工具名)
        系统.关闭()

    def test_查询未知作业id抛KeyError(self) -> None:
        系统 = self._建系统()
        with self.assertRaises(KeyError):
            系统.查询("查无此作业")
        系统.关闭()

    # ── 持久化与重启收敛 ───────────────────────────────────────────────

    def test_终态作业落盘并可重新加载(self) -> None:
        系统 = self._建系统()
        系统.设置执行器(lambda 工具名, 参数: {"成功": True, "回执": "干完了"})
        作业id = _提交(系统, "run_release_gate")
        _等待终态(系统, 作业id)
        系统.关闭()

        账本 = self.存储目录 / "作业.jsonl"
        self.assertTrue(账本.is_file())
        记录 = [json.loads(行) for 行 in 账本.read_text(encoding="utf-8").splitlines() if 行.strip()]
        self.assertEqual(len(记录), 1)
        self.assertEqual(记录[0]["状态"], 状态_成功)
        self.assertEqual(记录[0]["作业id"], 作业id)

        重开 = 作业系统(存储目录=self.存储目录)
        查回 = 重开.查询(作业id)
        self.assertEqual(查回.状态, 状态_成功)
        self.assertEqual(查回.结果["回执"], "干完了")
        重开.关闭()

    def test_重启后未完成作业收敛为崩溃(self) -> None:
        # 手工构造「上次进程死在运行中」的账本，模拟断电/重启。
        半截 = {
            "作业id": "aaaaaaaaaaaaaaaa", "工具": "run_release_gate",
            "状态": 状态_运行中, "结果": None, "错误码": "", "错误说明": "",
            "开工id": "开工00000000001", "创建时间": "2026-09-12 10:00:00",
            "开始时间": "2026-09-12 10:00:01", "完成时间": "",
            "取消标记": False, "结果已截断": False,
        }
        self.存储目录.mkdir(parents=True, exist_ok=True)
        (self.存储目录 / "作业.jsonl").write_text(
            json.dumps(半截, ensure_ascii=False) + "\n", encoding="utf-8",
        )

        系统 = 作业系统(存储目录=self.存储目录)
        收敛 = 系统.查询("aaaaaaaaaaaaaaaa")
        self.assertEqual(收敛.状态, 状态_崩溃)
        self.assertEqual(收敛.错误码, "崩溃")
        self.assertIn("重启", 收敛.错误说明)
        self.assertTrue(收敛.完成时间)
        系统.关闭()

    def test_结果超限落盘截断但内存仍完整(self) -> None:
        大结果 = {"成功": True, "输出": "长" * 5000}
        系统 = self._建系统(结果落盘上限字节=1024)
        系统.设置执行器(lambda 工具名, 参数: 大结果)
        作业id = _提交(系统, "run_release_gate")
        完成 = _等待终态(系统, 作业id)
        self.assertEqual(完成.状态, 状态_成功)
        self.assertEqual(完成.结果["输出"], "长" * 5000)  # 内存内完整
        self.assertTrue(完成.结果已截断)
        系统.关闭()

        重开 = 作业系统(存储目录=self.存储目录)
        落盘 = 重开.查询(作业id).结果
        self.assertTrue(落盘["截断"])
        self.assertGreater(落盘["原字节数"], 1024)
        重开.关闭()

    # ── 列出 ───────────────────────────────────────────────────────────

    def test_列出按创建时间倒序并支持限量(self) -> None:
        系统 = self._建系统()
        系统.设置执行器(lambda 工具名, 参数: {"成功": True})
        编号 = [_提交(系统, "run_release_gate") for _ in range(3)]
        self.assertEqual(len(系统.列出(2)), 2)
        self.assertEqual(len(系统.列出()), 3)
        self.assertEqual({项.作业id for 项 in 系统.列出()}, set(编号))
        系统.关闭()


if __name__ == "__main__":
    unittest.main()
