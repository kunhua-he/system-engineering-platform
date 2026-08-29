"""SQLite 数据库支持库黑盒测试：真实 sqlite3 文件、查询、事务与回滚。

测试只经 SQLite 数据库支持库包级入口，不导入 实现/，不把内存字典当数据库。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.数据库连接支持库.SQLite数据库 import 关闭, 查询, 事务执行, 连接


class 测试SQLite数据库支持库(unittest.TestCase):
    def setUp(self) -> None:
        self.临时目录 = tempfile.TemporaryDirectory(prefix="SQLite支持库_")
        self.数据库 = str(Path(self.临时目录.name) / "测试.db")

    def tearDown(self) -> None:
        self.临时目录.cleanup()

    def test_真实连接查询和关闭(self) -> None:
        self.assertTrue(连接(self.数据库).成功)
        建表 = 事务执行(self.数据库, [
            "CREATE TABLE 项目数据(编号 INTEGER PRIMARY KEY, 名称 TEXT NOT NULL)",
            "INSERT INTO 项目数据(编号, 名称) VALUES(1, '华哥')",
        ])
        self.assertTrue(建表.成功)
        结果 = 查询(self.数据库, "SELECT 编号, 名称 FROM 项目数据 WHERE 编号=?", [1])
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["行列表"], [{"编号": 1, "名称": "华哥"}])
        self.assertTrue(关闭(self.数据库).成功)

    def test_事务失败真实回滚(self) -> None:
        self.assertTrue(事务执行(self.数据库, [
            "CREATE TABLE 项目数据(编号 INTEGER PRIMARY KEY, 名称 TEXT NOT NULL)",
        ]).成功)
        失败 = 事务执行(self.数据库, [
            "INSERT INTO 项目数据(编号, 名称) VALUES(1, '第一次')",
            "INSERT INTO 项目数据(编号, 名称) VALUES(1, '重复')",
        ])
        self.assertFalse(失败.成功)
        结果 = 查询(self.数据库, "SELECT COUNT(*) AS 数量 FROM 项目数据")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["行列表"], [{"数量": 0}])

    def test_参数错误不伪造成功(self) -> None:
        结果 = 查询(self.数据库, "")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main()
