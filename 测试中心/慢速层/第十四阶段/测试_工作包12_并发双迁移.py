"""第十四阶段 P1-12 并发双迁移治理：真实双进程互斥迁移测试（慢速层）。

5 个真实场景：① 单进程推进成功（状态=已完成、表结构真实变化）；
② 两个真实进程同时迁移同一存储：恰好一个推进、另一个复用结果，
最终状态=已完成且只迁移一次（迁移执行次数唯一，无双写）；
③ 迁移中途失败整体回滚（注入第二步抛异常）：表结构无半变化、
失败记录明确；④ 已完成后再次迁移：直接复用结果，不重复执行；
⑤ 两个进程用不同迁移任务id同时迁移同一存储：第二个明确冲突。
全部使用真实 sqlite 写锁（BEGIN IMMEDIATE）与元信息状态位。
"""
import multiprocessing
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.发布管理.迁移互斥编排器 import 迁移互斥编排器

上下文 = multiprocessing.get_context("fork")


def 子进程执行迁移(存储目录: str, 迁移任务id: str, 结果队列, 延迟秒: float = 0.0) -> None:
    """真实子进程独立执行迁移，结果经队列回传。"""
    类 = 迁移互斥编排器
    if 延迟秒:
        class 慢速编排器(迁移互斥编排器):
            步骤延迟秒 = 延迟秒
        类 = 慢速编排器
    编排器 = 类(存储目录)
    try:
        结果, 状态 = 编排器.执行迁移(迁移任务id)
        结果队列.put((结果, 状态))
    except Exception as 错误:
        结果队列.put(("异常", str(错误)))
    finally:
        编排器.清理()


class 失败注入编排器(迁移互斥编排器):
    """注入第二步写入失败：模拟迁移中途真实失败。"""

    def _步骤2_写入记录(self, 连接: sqlite3.Connection) -> None:
        super()._步骤2_写入记录(连接)
        raise RuntimeError("注入第二步写入失败")


class Test并发双迁移治理(unittest.TestCase):
    """并发双迁移治理：真实 sqlite 锁互斥与状态位治理。"""

    def setUp(self) -> None:
        self.临时目录 = tempfile.mkdtemp(prefix="迁移互斥测试_")
        self.存储目录 = os.path.join(self.临时目录, "存储")

    def tearDown(self) -> None:
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def 编排器(self) -> 迁移互斥编排器:
        return 迁移互斥编排器(self.存储目录)

    def _库断言(self, 期望表存在: bool) -> None:
        """真实读取库：断言迁移目标表/列/记录是否就位。"""
        连接 = sqlite3.connect(os.path.join(self.存储目录, "迁移状态.db"))
        try:
            表行 = 连接.execute("SELECT name FROM sqlite_master "
                              "WHERE type='table' AND name='迁移目标表'").fetchone()
            if 期望表存在:
                self.assertIsNotNone(表行)
                列集合 = {行[1] for 行 in 连接.execute("PRAGMA table_info(迁移目标表)").fetchall()}
                self.assertIn("扩展列", 列集合)
                记录 = 连接.execute("SELECT 名称 FROM 迁移目标表 WHERE id='版本1'").fetchone()
                self.assertEqual(记录, ("迁移验证记录",))
            else:
                self.assertIsNone(表行)  # 表结构未半变化
        finally:
            连接.close()

    def test_单进程执行迁移成功推进(self) -> None:
        编排器 = self.编排器()
        try:
            结果, 状态 = 编排器.执行迁移("迁移任务一号")
            self.assertEqual((结果, 状态), ("推进", "已完成"))
            self.assertEqual(编排器.查询迁移状态(), "已完成")
            self._库断言(期望表存在=True)  # 表结构真实变化
            self.assertEqual(编排器._次数(编排器._打开()), 1)
        finally:
            编排器.清理()

    def test_两进程同时迁移只允许一个推进(self) -> None:
        队列甲, 队列乙 = 上下文.Queue(), 上下文.Queue()
        进程甲 = 上下文.Process(target=子进程执行迁移,
                              args=(self.存储目录, "迁移任务同一", 队列甲))
        进程乙 = 上下文.Process(target=子进程执行迁移,
                              args=(self.存储目录, "迁移任务同一", 队列乙))
        进程甲.start()
        进程乙.start()
        进程甲.join(120)
        进程乙.join(120)
        try:
            self.assertFalse(进程甲.is_alive())
            self.assertFalse(进程乙.is_alive())
            结果甲 = 队列甲.get(timeout=10)
            结果乙 = 队列乙.get(timeout=10)
        finally:
            队列甲.close()
            队列乙.close()
        self.assertEqual({结果甲[0], 结果乙[0]}, {"推进", "复用"})  # 恰好一个推进
        for _, 状态 in (结果甲, 结果乙):
            self.assertEqual(状态, "已完成")
        编排器 = self.编排器()
        try:
            self.assertEqual(编排器.查询迁移状态(), "已完成")
            self.assertEqual(编排器._次数(编排器._打开()), 1)  # 只迁移一次，无双写
        finally:
            编排器.清理()

    def test_迁移中途失败整体回滚(self) -> None:
        编排器 = 失败注入编排器(self.存储目录)
        try:
            结果, 状态 = 编排器.执行迁移("迁移任务失败")
            self.assertEqual((结果, 状态), ("失败", "失败"))
            self.assertEqual(编排器.查询迁移状态(), "失败")
            self._库断言(期望表存在=False)  # 整体回滚到迁移前，无半状态
            记录 = 编排器._读状态(编排器._打开())
            self.assertIn("注入第二步写入失败", 记录["错误"])  # 失败记录明确
        finally:
            编排器.清理()

    def test_已完成后再次迁移直接复用(self) -> None:
        编排器 = self.编排器()
        try:
            结果1, _ = 编排器.执行迁移("迁移任务一号")
            self.assertEqual(结果1, "推进")
            结果2, 状态2 = 编排器.执行迁移("迁移任务一号")
            self.assertEqual((结果2, 状态2), ("复用", "已完成"))
            self.assertEqual(编排器._次数(编排器._打开()), 1)  # 未重复执行迁移步骤
            self.assertEqual(编排器.查询迁移状态(), "已完成")
        finally:
            编排器.清理()

    def test_不同任务id同时迁移第二个明确冲突(self) -> None:
        队列甲, 队列乙 = 上下文.Queue(), 上下文.Queue()
        进程甲 = 上下文.Process(target=子进程执行迁移,
                              args=(self.存储目录, "迁移任务甲", 队列甲, 1.2))
        进程乙 = 上下文.Process(target=子进程执行迁移,
                              args=(self.存储目录, "迁移任务乙", 队列乙))
        进程甲.start()
        time.sleep(0.4)  # 甲已持锁处于迁移中，制造冲突观察窗口
        进程乙.start()
        进程甲.join(120)
        进程乙.join(120)
        try:
            self.assertFalse(进程甲.is_alive())
            self.assertFalse(进程乙.is_alive())
            结果甲 = 队列甲.get(timeout=10)
            结果乙 = 队列乙.get(timeout=10)
        finally:
            队列甲.close()
            队列乙.close()
        self.assertEqual(结果甲[0], "推进")  # 甲推进
        self.assertEqual(结果乙[0], "冲突")  # 第二个明确冲突，不能并发推进
        编排器 = self.编排器()
        try:
            self.assertEqual(编排器.查询迁移状态(), "已完成")
            self.assertEqual(编排器._次数(编排器._打开()), 1)  # 甲的迁移只执行一次
        finally:
            编排器.清理()


if __name__ == "__main__":
    unittest.main()
