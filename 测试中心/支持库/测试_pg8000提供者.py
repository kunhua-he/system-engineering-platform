"""pg8000 提供者测试：参数不合法/驱动缺失/真实连接/连接生命周期受管/注册与摘要一致。

无数据库服务时必须明确失败（连接失败/超时），绝不假装连接成功；
连接对象与游标调用后必然关闭（mock 驱动验证释放）。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.能力契约.契约 import 能力注册表
from 支持库.适配层.pg8000提供者 import 关闭, 连接, 查询, 注册能力, 事务执行
from 支持库.适配层.pg8000提供者.实现 import 提供者 as 模块

提供者目录 = (
    Path(__file__).resolve().parents[2]
    / "支持库" / "适配层" / "pg8000提供者"
)
测试连接串 = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
无服务连接串 = "postgresql://127.0.0.1:59999/nodb"


def _驱动可用() -> bool:
    try:
        __import__("pg8000")
        return True
    except ImportError:
        return False


class _假游标:
    def __init__(self, 连接):
        self.连接 = 连接
        self.已关闭 = False
        self.description = None
        self.记录 = []

    def execute(self, SQL, 参数=None):
        self.记录.append(SQL)

    def fetchall(self):
        return []

    def close(self):
        self.已关闭 = True


class _假连接:
    def __init__(self):
        self.已关闭 = False
        self.游标 = _假游标(self)
        self.已回滚 = False
        self.已提交 = False

    def cursor(self):
        return self.游标

    def close(self):
        self.已关闭 = True

    def commit(self):
        self.已提交 = True

    def rollback(self):
        self.已回滚 = True


class Testpg8000提供者(unittest.TestCase):
    def test_参数不合法(self):
        """非法参数一律返回 参数不合法。"""
        for 调用 in (
            连接(""),
            连接("不是URL", 超时秒=2),
            连接("postgresql://u@127.0.0.1:5432/db", 超时秒=0),
            查询("postgresql://u@127.0.0.1:5432/db", ""),
            查询("postgresql://u@127.0.0.1:5432/db", "SELECT 1", 参数="x"),
            事务执行("postgresql://u@127.0.0.1:5432/db", []),
            事务执行("postgresql://u@127.0.0.1:5432/db", ["SELECT 1", 3]),
            关闭(""),
        ):
            self.assertFalse(调用.成功)
            self.assertEqual(调用.错误码, "参数不合法")

    def test_驱动缺失明确失败(self):
        """缺驱动 → 提供者不可用（不 skip、不假装成功）。"""
        原可用 = 模块._驱动可用
        模块._驱动可用 = False
        try:
            for 调用 in (
                连接(测试连接串),
                查询(测试连接串, "SELECT 1"),
                事务执行(测试连接串, ["SELECT 1"]),
                关闭(测试连接串),
            ):
                self.assertFalse(调用.成功)
                self.assertEqual(调用.错误码, "提供者不可用")
        finally:
            模块._驱动可用 = 原可用

    def test_无数据库服务明确失败(self):
        """无服务端口 → 连接失败/超时（绝不假装连接成功）。"""
        结果 = 连接(无服务连接串, 超时秒=2)
        self.assertFalse(结果.成功)
        self.assertIn(结果.错误码, ("连接失败", "超时"))

    def test_连接生命周期受管调用后关闭(self):
        """连接成功路径：连接对象必然关闭（mock 驱动验证释放）。"""
        with mock.patch.object(模块.pg8000, "connect",
                               return_value=_假连接()) as 假调用:
            结果 = 连接("postgresql://u@127.0.0.1:5432/db", 超时秒=2)
        self.assertTrue(结果.成功, 结果.错误说明)
        假连接 = 假调用.return_value
        self.assertTrue(假连接.已关闭, "连接对象未关闭（泄漏）")
        self.assertTrue(假连接.游标 is not None)

    def test_查询生命周期游标与连接关闭(self):
        """查询路径：游标与连接对象调用后必然关闭。"""
        with mock.patch.object(模块.pg8000, "connect",
                               return_value=_假连接()) as 假调用:
            结果 = 查询("postgresql://u@127.0.0.1:5432/db", "SELECT 1", 超时秒=2)
        self.assertTrue(结果.成功, 结果.错误说明)
        假连接 = 假调用.return_value
        self.assertTrue(假连接.已关闭, "查询连接未关闭（泄漏）")
        self.assertTrue(假连接.游标.已关闭, "查询游标未关闭（泄漏）")

    def test_事务执行生命周期受管(self):
        """事务路径：连接对象调用后关闭且提交路径可达。"""
        with mock.patch.object(模块.pg8000, "connect",
                               return_value=_假连接()) as 假调用:
            结果 = 事务执行("postgresql://u@127.0.0.1:5432/db",
                           ["SELECT 1"], 超时秒=2)
        self.assertTrue(结果.成功, 结果.错误说明)
        假连接 = 假调用.return_value
        self.assertTrue(假连接.已关闭, "事务连接未关闭（泄漏）")

    @unittest.skipUnless(_驱动可用(), "pg8000 未安装")
    def test_真实连接查询事务(self):
        """有真实 PostgreSQL 服务时验证 连接/查询/事务 闭环。"""
        连接结果 = 连接(测试连接串, 超时秒=5)
        if 连接结果.错误码 in ("连接失败", "超时"):
            self.skipTest(f"本机无 PostgreSQL 服务: {连接结果.错误说明}")
        self.assertTrue(连接结果.成功, 连接结果.错误说明)
        查询结果 = 查询(测试连接串, "SELECT 1 AS 一", 超时秒=5)
        self.assertTrue(查询结果.成功, 查询结果.错误说明)
        self.assertEqual(查询结果.值["行列表"][0]["一"], 1)
        事务结果 = 事务执行(测试连接串, ["SELECT 1"], 超时秒=5)
        self.assertTrue(事务结果.成功, 事务结果.错误说明)
        关闭结果 = 关闭(测试连接串, 超时秒=5)
        self.assertTrue(关闭结果.成功, 关闭结果.错误说明)

    def test_注册能力与声明一致(self):
        """注册能力可获取且与包声明/能力定义能力清单一致。"""
        注册表 = 能力注册表()
        注册能力(注册表)
        声明数据 = json.loads((提供者目录 / "包声明.json").read_text(encoding="utf-8"))
        声明能力表 = [能力["能力id"] for 能力 in 声明数据["能力"]]
        定义数据 = json.loads((提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        定义能力表 = [能力["能力id"] for 能力 in 定义数据["能力列表"]]
        self.assertEqual(sorted(注册表.能力id列表), sorted(声明能力表))
        self.assertEqual(sorted(声明能力表), sorted(定义能力表))

    def test_完整性摘要一致(self):
        """完整性摘要与包声明一致（文件清单格式，门禁口径）。"""
        摘要数据 = json.loads((提供者目录 / "完整性摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要数据["包id"], "支持库.适配层.pg8000提供者")
        self.assertEqual(摘要数据["摘要算法"], "sha256")
        self.assertTrue(摘要数据["文件清单"], "文件清单不得为空")
        清单路径 = {项["路径"] for 项 in 摘要数据["文件清单"]}
        self.assertIn("__init__.py", 清单路径)
        self.assertIn("能力定义.json", 清单路径)
        self.assertIn("依赖契约/依赖契约.json", 清单路径)
        self.assertIn("权限契约/权限契约.json", 清单路径)
        self.assertIn("配置契约/配置契约.json", 清单路径)
        self.assertIn("资源预算.json", 清单路径)
        self.assertIn("复用决策.json", 清单路径)


if __name__ == "__main__":
    unittest.main()
