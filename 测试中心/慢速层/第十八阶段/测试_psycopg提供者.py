"""psycopg/psycopg2 数据库提供者测试。

覆盖：缺驱动 → 提供者不可用；连接串非法 → 参数不合法；超时非法 → 参数不合法；
有真实 PostgreSQL（环境变量 PG测试连接串 或本机 5432）时验证 连接/查询/事务。
驱动缺失必须明确失败（不 skip）；真实连接用例用 skipUnless。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[3]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

测试连接串 = os.environ.get("PG测试连接串") or "postgresql://postgres:postgres@127.0.0.1:5432/postgres"


def _驱动可用(模块名: str) -> bool:
    try:
        __import__(模块名)
        return True
    except ImportError:
        return False


class Testpsycopg提供者(unittest.TestCase):
    """psycopg 提供者测试。"""

    def test_连接串非法(self):
        from 支持库.适配层.psycopg提供者.实现.提供者 import 连接
        结果 = 连接("")  # 空串
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_超时非法(self):
        from 支持库.适配层.psycopg提供者.实现.提供者 import 连接
        结果 = 连接("postgresql://u@127.0.0.1:5432/db", 超时秒=0)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_SQL非法(self):
        from 支持库.适配层.psycopg提供者.实现.提供者 import 查询
        结果 = 查询("postgresql://u@127.0.0.1:5432/db", "")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_驱动缺失明确失败(self):
        """缺驱动 → 提供者不可用（不 skip）。"""
        from 支持库.适配层.psycopg提供者.实现 import 提供者 as 模块
        原可用 = 模块._驱动可用
        模块._驱动可用 = False
        try:
            结果 = 模块.连接("postgresql://u@127.0.0.1:5432/db")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            模块._驱动可用 = 原可用

    @unittest.skipUnless(_驱动可用("psycopg"), "psycopg 未安装")
    def test_真实连接(self):
        from 支持库.适配层.psycopg提供者.实现.提供者 import 连接, 查询, 事务执行
        结果 = 连接(测试连接串, 超时秒=5)
        if 结果.错误码 in ("连接失败", "超时"):
            self.skipTest(f"本机无 PostgreSQL 服务: {结果.错误说明}")
        self.assertTrue(结果.成功, 结果.错误说明)
        # 查询
        查询结果 = 查询(测试连接串, "SELECT 1 AS 一", 超时秒=5)
        self.assertTrue(查询结果.成功, 查询结果.错误说明)
        self.assertEqual(查询结果.值["行列表"][0]["一"], 1)


class Testpsycopg2提供者(unittest.TestCase):
    """psycopg2 提供者测试。"""

    def test_连接串非法(self):
        from 支持库.适配层.psycopg2提供者.实现.提供者 import 连接
        结果 = 连接(None)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_驱动缺失明确失败(self):
        from 支持库.适配层.psycopg2提供者.实现 import 提供者 as 模块
        原可用 = 模块._驱动可用
        模块._驱动可用 = False
        try:
            结果 = 模块.连接("postgresql://u@127.0.0.1:5432/db")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            模块._驱动可用 = 原可用

    @unittest.skipUnless(_驱动可用("psycopg2"), "psycopg2 未安装")
    def test_真实连接(self):
        from 支持库.适配层.psycopg2提供者.实现.提供者 import 连接, 查询, 事务执行
        结果 = 连接(测试连接串, 超时秒=5)
        if 结果.错误码 in ("连接失败", "超时"):
            self.skipTest(f"本机无 PostgreSQL 服务: {结果.错误说明}")
        self.assertTrue(结果.成功, 结果.错误说明)
        查询结果 = 查询(测试连接串, "SELECT 1 AS 一", 超时秒=5)
        self.assertTrue(查询结果.成功, 查询结果.错误说明)
        self.assertEqual(查询结果.值["行列表"][0]["一"], 1)
        # 事务回滚：第一条成功第二条失败 → 回滚
        事务结果 = 事务执行(测试连接串, ["CREATE TABLE IF NOT EXISTS _提供者测试 (id int)", "INSERT INTO 不存在表 VALUES (1)"], 超时秒=5)
        self.assertFalse(事务结果.成功)


if __name__ == "__main__":
    unittest.main()
