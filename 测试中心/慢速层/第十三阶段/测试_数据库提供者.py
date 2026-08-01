"""第十三阶段：SQLite 真实数据库提供者测试（真实临时库文件，全部真实执行）。

6 个真实场景：建库写入查询 / 连接超时(busy_timeout) / 查询超时(真实中断) /
事务原子(提交落盘+回滚不落盘) / 断开自动重连 / 关闭释放句柄。
"""

import importlib.util
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

# 并行开发期间 提供者/__init__.py 可能引用尚未完成的兄弟提供者模块，
# 本测试直接按文件路径加载被测模块，与包初始化顺序解耦（不依赖共享文件）。
_规格 = importlib.util.spec_from_file_location(
    "数据库提供者被测模块", str(系统根 / "平台控制面" / "提供者" / "数据库提供者.py"))
_被测模块 = importlib.util.module_from_spec(_规格)
_规格.loader.exec_module(_被测模块)
数据库提供者 = _被测模块.数据库提供者
创建数据库能力函数 = _被测模块.创建数据库能力函数

# 真实慢查询：递归 CTE 计数，自然跑完需数秒，用于验证超时真实中断
慢查询SQL = ("WITH RECURSIVE 数(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM 数 "
             "WHERE x < 200000000) SELECT count(*) FROM 数")


class Test数据库提供者真实场景(unittest.TestCase):

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="数据库提供者_"))
        self.库路径 = self.目录 / "测试库.db"
        self.提供者 = 数据库提供者(self.库路径)

    def tearDown(self):
        self.提供者.关闭()
        shutil.rmtree(self.目录, ignore_errors=True)

    def test_真实建库写入与查询(self):
        """场景1：连接真实建库、写入、参数绑定查询；工厂函数同走统一契约。"""
        结果 = self.提供者.连接()
        self.assertTrue(结果["成功"], 结果["消息"])
        self.assertTrue(self.库路径.is_file(), "连接后库文件必须真实落盘")
        建表 = self.提供者.执行("CREATE TABLE 用户(编号 INTEGER PRIMARY KEY, 姓名 TEXT)")
        self.assertTrue(建表["成功"], 建表["消息"])
        写入 = self.提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(?, ?)", (1, "华哥"))
        self.assertEqual(写入["结果"]["影响行数"], 1)
        查询 = self.提供者.查询("SELECT 编号, 姓名 FROM 用户 WHERE 编号 > ?", (0,))
        self.assertTrue(查询["成功"], 查询["消息"])
        self.assertEqual(查询["结果"], [{"编号": 1, "姓名": "华哥"}])
        # 可注册工厂函数（对接 统一能力服务.注册提供者）同样返回统一结果结构
        能力 = 创建数据库能力函数(self.目录 / "能力库.db")
        self.assertTrue(能力({"操作": "连接"})["成功"])
        self.assertEqual(能力({"操作": "查询", "sql": "SELECT 1 AS 一"})["结果"], [{"一": 1}])
        能力({"操作": "关闭"})

    def test_连接超时真实生效(self):
        """场景2：他方持写锁，写入必须真实等待 busy_timeout 到期后失败。"""
        self.提供者.连接(连接超时秒=0.6)
        self.提供者.执行("CREATE TABLE 用户(编号 INTEGER PRIMARY KEY, 姓名 TEXT)")
        他方 = sqlite3.connect(str(self.库路径))
        他方.execute("BEGIN IMMEDIATE")
        try:
            开始 = time.monotonic()
            结果 = self.提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(1, '甲')")
            耗时 = time.monotonic() - 开始
            self.assertFalse(结果["成功"], "锁竞争必须失败")
            self.assertEqual(结果["错误码"], "DATABASE_LOCKED")
            self.assertGreaterEqual(耗时, 0.5, "必须真实等待 busy_timeout 到期")
        finally:
            他方.rollback()
            他方.close()

    def test_查询超时真实中断(self):
        """场景3：慢查询超时后 interrupt 真实中断 SQL，连接仍可复用。"""
        self.提供者.连接(查询超时秒=0.4)
        开始 = time.monotonic()
        结果 = self.提供者.查询(慢查询SQL)
        耗时 = time.monotonic() - 开始
        self.assertFalse(结果["成功"], "慢查询必须超时失败")
        self.assertEqual(结果["错误码"], "QUERY_TIMEOUT")
        self.assertLess(耗时, 8, "中断必须真实生效，不能等查询自然跑完")
        恢复 = self.提供者.查询("SELECT 1 AS 一")
        self.assertTrue(恢复["成功"], 恢复["消息"])
        self.assertEqual(恢复["结果"], [{"一": 1}])

    def test_事务提交与回滚原子(self):
        """场景4：提交原子落盘；异常整体回滚，回滚后数据不落盘。"""
        self.提供者.连接()
        self.提供者.执行("CREATE TABLE 用户(编号 INTEGER PRIMARY KEY, 姓名 TEXT)")

        def 写两条():
            self.提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(1, '甲')")
            self.提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(2, '乙')")
            return "完成"

        提交 = self.提供者.事务(写两条)
        self.assertTrue(提交["成功"], 提交["消息"])
        self.assertEqual(提交["结果"], "完成")

        def 写后抛错():
            self.提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(9, '丙')")
            raise ValueError("事务内故意失败")

        回滚 = self.提供者.事务(写后抛错)
        self.assertFalse(回滚["成功"])
        self.assertEqual(回滚["错误码"], "TRANSACTION_FAILED")
        self.assertIn("回滚", 回滚["消息"])
        # 新连接验证落盘事实：提交的两条在、回滚的一条不落盘
        验证 = sqlite3.connect(str(self.库路径))
        try:
            self.assertEqual(验证.execute("SELECT count(*) FROM 用户").fetchone()[0], 2)
            self.assertIsNone(验证.execute("SELECT 姓名 FROM 用户 WHERE 编号=9").fetchone(),
                              "回滚后数据不得落盘")
        finally:
            验证.close()

    def test_断开自动重连(self):
        """场景5：连接失效（外部关闭底层连接）后，下次操作自动重连且数据不丢。"""
        self.提供者.连接()
        self.提供者.执行("CREATE TABLE 用户(编号 INTEGER PRIMARY KEY, 姓名 TEXT)")
        self.提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(7, '丁')")
        self.提供者._连接.close()  # 模拟外部断开：底层句柄已关，引用未清
        结果 = self.提供者.查询("SELECT count(*) AS 总数 FROM 用户")
        self.assertTrue(结果["成功"], 结果["消息"])
        self.assertEqual(结果["结果"], [{"总数": 1}], "重连后数据必须仍在")
        self.assertIsNotNone(self.提供者._连接, "必须已建立新连接")

    def test_关闭释放句柄(self):
        """场景6：显式关闭后句柄真实释放；之后所有操作返回明确错误。"""
        self.提供者.连接()
        self.提供者.执行("CREATE TABLE 用户(编号 INTEGER PRIMARY KEY, 姓名 TEXT)")
        关闭结果 = self.提供者.关闭()
        self.assertTrue(关闭结果["成功"])
        self.assertIsNone(self.提供者._连接, "关闭后连接句柄必须释放")
        for 操作 in (lambda: self.提供者.查询("SELECT 1"),
                     lambda: self.提供者.执行("INSERT INTO 用户(编号, 姓名) VALUES(1, 'x')")):
            拒绝 = 操作()
            self.assertFalse(拒绝["成功"], "关闭后操作必须拒绝")
            self.assertEqual(拒绝["错误码"], "DATABASE_CLOSED")
            self.assertIn("已关闭", 拒绝["消息"])


if __name__ == "__main__":
    unittest.main()
