"""SQLite 提供者并发隔离、连接池和资源收敛回归。"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(系统根))

from 平台控制面.提供者.数据库提供者 import 数据库提供者


class 跟踪连接:
    def __init__(self, 真实连接, *, 关闭失败=False):
        self.真实连接 = 真实连接
        self.关闭失败 = 关闭失败
        self.回滚次数 = 0
        self.关闭次数 = 0

    @property
    def in_transaction(self):
        return self.真实连接.in_transaction

    def execute(self, *参数):
        return self.真实连接.execute(*参数)

    def interrupt(self):
        return self.真实连接.interrupt()

    def commit(self):
        return self.真实连接.commit()

    def rollback(self):
        self.回滚次数 += 1
        return self.真实连接.rollback()

    def close(self):
        self.关闭次数 += 1
        if self.关闭失败:
            raise sqlite3.OperationalError("故意注入旧连接关闭失败")
        return self.真实连接.close()


class 测试SQLite并发与收敛(unittest.TestCase):
    def setUp(self):
        self.临时目录 = tempfile.TemporaryDirectory(prefix="SQLite并发_")
        self.库路径 = Path(self.临时目录.name) / "主库.db"
        self.提供者 = None

    def tearDown(self):
        if self.提供者 is not None:
            self.提供者.关闭()
        self.临时目录.cleanup()

    def _建表(self, 提供者=None):
        提供者 = 提供者 or self.提供者
        self.assertTrue(提供者.连接()["成功"])
        结果 = 提供者.执行("CREATE TABLE 记录(编号 INTEGER PRIMARY KEY, 内容 TEXT)")
        self.assertTrue(结果["成功"], 结果["消息"])

    def test_回滚事务期间普通写入必须排队且不被一同回滚(self):
        self.提供者 = 数据库提供者(self.库路径, 查询超时秒=2)
        self._建表()
        事务已写 = threading.Event()
        允许回滚 = threading.Event()
        普通写完成 = threading.Event()
        结果表 = {}

        def 回滚事务():
            def 工作():
                写入 = self.提供者.执行(
                    "INSERT INTO 记录 VALUES(1, '事务内')")
                self.assertTrue(写入["成功"], 写入["消息"])
                事务已写.set()
                self.assertTrue(允许回滚.wait(2))
                raise ValueError("故意回滚")
            结果表["事务"] = self.提供者.事务(工作)

        def 普通写入():
            结果表["普通"] = self.提供者.执行(
                "INSERT INTO 记录 VALUES(2, '事务外')")
            普通写完成.set()

        事务线程 = threading.Thread(target=回滚事务)
        普通线程 = threading.Thread(target=普通写入)
        事务线程.start()
        self.assertTrue(事务已写.wait(1), "事务未进入写入阶段")
        普通线程.start()
        self.assertFalse(普通写完成.wait(0.15),
                         "同库普通写入不得插进未结束事务")
        允许回滚.set()
        事务线程.join(2)
        普通线程.join(2)
        self.assertFalse(结果表["事务"]["成功"])
        self.assertTrue(结果表["普通"]["成功"], 结果表["普通"]["消息"])
        self.assertEqual(self.提供者.查询(
            "SELECT 编号 FROM 记录 ORDER BY 编号")["结果"], [{"编号": 2}])

    def test_连接池有界且读工作单元跨连接执行(self):
        计数锁 = threading.Lock()
        当前数 = 0
        峰值 = 0
        新建数 = 0

        class 慢读提供者(数据库提供者):
            def _新建连接(内部self):
                nonlocal 当前数, 峰值, 新建数
                连接 = super()._新建连接()
                新建数 += 1

                def 等待():
                    nonlocal 当前数, 峰值
                    with 计数锁:
                        当前数 += 1
                        峰值 = max(峰值, 当前数)
                    time.sleep(0.12)
                    with 计数锁:
                        当前数 -= 1
                    return 1

                连接.create_function("等待", 0, 等待)
                return 连接

        self.提供者 = 慢读提供者(self.库路径, 连接池大小=2, 查询超时秒=1)
        self.assertTrue(self.提供者.连接()["成功"])
        结果表 = []
        线程表 = [threading.Thread(
            target=lambda: 结果表.append(self.提供者.查询("SELECT 等待() AS 值")))
            for _ in range(5)]
        for 线程 in 线程表:
            线程.start()
        for 线程 in 线程表:
            线程.join(2)
        self.assertEqual(len(结果表), 5)
        self.assertTrue(all(项["成功"] for 项 in 结果表), 结果表)
        self.assertLessEqual(峰值, 2)
        self.assertEqual(峰值, 2, "读工作单元应实际使用多个独立连接")
        self.assertLessEqual(新建数, 2, "连接数不得突破连接池边界")

    def test_不同数据库写事务可以并行(self):
        另一路径 = Path(self.临时目录.name) / "另库.db"
        甲 = 数据库提供者(self.库路径, 查询超时秒=2)
        乙 = 数据库提供者(另一路径, 查询超时秒=2)
        self.提供者 = 甲
        self._建表(甲)
        self._建表(乙)
        栅栏 = threading.Barrier(2)
        结果表 = []

        def 执行事务(提供者, 编号):
            def 工作():
                栅栏.wait(timeout=1)
                time.sleep(0.2)
                return 提供者.执行(
                    "INSERT INTO 记录 VALUES(?, '并行')", (编号,))
            结果表.append(提供者.事务(工作))

        开始 = time.monotonic()
        线程表 = [threading.Thread(target=执行事务, args=(甲, 1)),
                  threading.Thread(target=执行事务, args=(乙, 2))]
        for 线程 in 线程表:
            线程.start()
        for 线程 in 线程表:
            线程.join(2)
        耗时 = time.monotonic() - 开始
        乙.关闭()
        self.assertEqual(len(结果表), 2)
        self.assertTrue(all(项["成功"] for 项 in 结果表), 结果表)
        self.assertLess(耗时, 0.7, "跨库事务不得被全局串行锁阻塞")

    def test_关闭有独立硬截止并保留未收敛任务账本(self):
        self.提供者 = 数据库提供者(
            self.库路径, 查询超时秒=5, 关闭硬截止秒=0.15)
        self._建表()
        已进入 = threading.Event()
        释放 = threading.Event()

        def 卡住任务():
            已进入.set()
            释放.wait(3)

        调用线程 = threading.Thread(target=lambda: self.提供者.事务(卡住任务))
        调用线程.start()
        self.assertTrue(已进入.wait(1))
        开始 = time.monotonic()
        try:
            关闭结果 = self.提供者.关闭()
            耗时 = time.monotonic() - 开始
            self.assertLess(耗时, 0.8, "关闭不得按查询超时或无限等待")
            self.assertFalse(关闭结果["成功"])
            self.assertEqual(关闭结果["错误码"], "RESOURCE_NOT_CONVERGED")
            self.assertTrue(self.提供者._任务账本, "未收敛任务必须保留账本")
            拒绝 = self.提供者.查询("SELECT 1")
            self.assertEqual(拒绝["错误码"], "DATABASE_CLOSED")
        finally:
            释放.set()
            调用线程.join(2)

    def test_未收敛任务时关闭不得进入可能阻塞的连接释放(self):
        self.提供者 = 数据库提供者(
            self.库路径, 查询超时秒=5, 关闭硬截止秒=0.1)
        提供者 = self.提供者
        self._建表()
        已进入 = threading.Event()
        释放任务 = threading.Event()

        def 卡住任务():
            已进入.set()
            释放任务.wait(2)

        调用线程 = threading.Thread(target=lambda: 提供者.事务(卡住任务))
        调用线程.start()
        self.assertTrue(已进入.wait(1))
        try:
            with mock.patch.object(
                提供者, "_释放全部连接",
                side_effect=lambda: time.sleep(1),
            ) as 释放调用:
                开始 = time.monotonic()
                关闭结果 = 提供者.关闭()
                耗时 = time.monotonic() - 开始
            self.assertFalse(关闭结果["成功"])
            self.assertEqual(关闭结果["错误码"], "RESOURCE_NOT_CONVERGED")
            self.assertLess(耗时, 0.4, "关闭硬截止后不得继续进入阻塞释放")
            释放调用.assert_not_called()
        finally:
            释放任务.set()
            调用线程.join(2)

    def test_任务提交到账本登记期间关闭不得提前返回成功(self):
        self.提供者 = 数据库提供者(self.库路径, 查询超时秒=2)
        提供者 = self.提供者
        self._建表()
        已提交 = threading.Event()
        允许登记 = threading.Event()
        原提交 = 提供者._执行器.submit

        def 延迟提交(*参数, **关键字):
            未来 = 原提交(*参数, **关键字)
            已提交.set()
            self.assertTrue(允许登记.wait(2))
            return 未来

        查询线程 = threading.Thread(target=lambda: 提供者.查询("SELECT 1"))
        with mock.patch.object(提供者._执行器, "submit", side_effect=延迟提交):
            查询线程.start()
            self.assertTrue(已提交.wait(1))
            关闭结果表 = []
            关闭线程 = threading.Thread(target=lambda: 关闭结果表.append(提供者.关闭()))
            关闭线程.start()
            time.sleep(0.1)
            提前返回 = not 关闭线程.is_alive()
            允许登记.set()
            查询线程.join(2)
            关闭线程.join(2)
        self.assertFalse(提前返回, "关闭不得越过已提交但尚未登记账本的任务")
        self.assertTrue(关闭结果表)

    def test_WITH写入不得走只读路径且必须真实提交(self):
        self.提供者 = 数据库提供者(self.库路径)
        self._建表()
        sql = (
            "WITH 新记录(编号, 内容) AS (VALUES(7, 'CTE写入')) "
            "INSERT INTO 记录 SELECT 编号, 内容 FROM 新记录"
        )
        self.assertFalse(self.提供者._是只读SQL(sql), "WITH写入不能归入只读路径")
        结果 = self.提供者.查询(sql)
        self.assertTrue(结果["成功"], 结果["消息"])
        外部连接 = sqlite3.connect(self.库路径)
        try:
            数量 = 外部连接.execute(
                "SELECT COUNT(*) FROM 记录 WHERE 编号=7 AND 内容='CTE写入'"
            ).fetchone()[0]
        finally:
            外部连接.close()
        self.assertEqual(数量, 1, "WITH写入必须经过写锁并提交")

    def test_重复连接替换前回滚关闭旧连接(self):
        self.提供者 = 数据库提供者(self.库路径)
        self.assertTrue(self.提供者.连接()["成功"])
        真实旧连接 = self.提供者._连接
        真实旧连接.execute("BEGIN")
        跟踪旧连接 = 跟踪连接(真实旧连接)
        self.提供者._连接 = 跟踪旧连接
        结果 = self.提供者.连接()
        self.assertTrue(结果["成功"], 结果["消息"])
        self.assertEqual(跟踪旧连接.回滚次数, 1)
        self.assertEqual(跟踪旧连接.关闭次数, 1)
        self.assertIsNot(self.提供者._连接, 跟踪旧连接)

    def test_旧连接释放失败不得冒充重连成功(self):
        self.提供者 = 数据库提供者(self.库路径)
        self.assertTrue(self.提供者.连接()["成功"])
        跟踪旧连接 = 跟踪连接(self.提供者._连接, 关闭失败=True)
        self.提供者._连接 = 跟踪旧连接
        结果 = self.提供者.连接()
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "RECONNECT_RELEASE_FAILED")
        self.assertEqual(跟踪旧连接.关闭次数, 1)
        self.assertIs(self.提供者._连接, 跟踪旧连接,
                      "旧连接释放失败时不得替换成新连接")
        跟踪旧连接.关闭失败 = False


if __name__ == "__main__":
    unittest.main()
