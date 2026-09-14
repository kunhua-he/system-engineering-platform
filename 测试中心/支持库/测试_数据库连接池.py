"""PostgreSQL 唯一同步池回归测试：有界并发、异常隔离、句柄生命周期、契约一致。

覆盖要点（每条都对应一次真实缺陷或真实契约）：
1) 并发借出数任何时刻不得超过连接池大小（历史缺陷：并发新建不受上限约束，曾冲到 7）；
2) 查询失败连接只丢弃不回池，绝不污染后续借用；
3) 释放后旧句柄必须失效，重复关闭保持幂等成功；
4) 参数口径：句柄/参数非法一律 参数不合法，句柄不存在 句柄失效；
5) 池状态字段与实现一致，不泄露连接对象；
6) 注册能力与包声明/能力定义一致，旧连接串能力不得残留。

需要本机真实 PostgreSQL（127.0.0.1:5432）；无服务时 skipTest 明确跳过，不假装通过。
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.能力契约.契约 import 能力注册表
from 公共契约.版本规则.契约版本 import 契约版本
from 支持库.后端.数据库连接支持库.psycopg数据库 import (
    关闭数据库连接, 注册能力, 查询数据库, 事务执行数据库, 连接池状态, 连接数据库,
)

包目录 = (Path(__file__).resolve().parents[2]
        / "支持库" / "后端" / "数据库连接支持库" / "psycopg数据库")
连接串 = "postgresql://postgres@127.0.0.1:5432/postgres"
无服务连接串 = "postgresql://postgres@127.0.0.1:59999/nodb"
旧能力后缀 = (".连接", ".查询", ".事务执行", ".关闭")


def 取值(结果: Any) -> dict:
    """取出结果信封里的值字典；非字典一律返回空字典。"""
    return 结果.值 if isinstance(结果.值, dict) else {}


def 调用(函数: Callable[..., Any], *参数: Any) -> Any:
    """按任意参数调用（用于非法类型入参用例，避免静态类型前置拦截）。"""
    return 函数(*参数)


def _可用连接串() -> str:
    """返回可用的真实连接串；不可用时返回空串（调用方 skipTest）。"""
    探测 = 连接数据库(连接串, 2, 2)
    if not 探测.成功:
        return ""
    关闭数据库连接(取值(探测).get("数据库句柄", 0))
    return 连接串


class 池基类(unittest.TestCase):
    连接串: str = ""

    @classmethod
    def setUpClass(cls):
        cls.连接串 = _可用连接串()
        if not cls.连接串:
            raise unittest.SkipTest("本机无可用 PostgreSQL（127.0.0.1:5432），跳过真实池测试")


class 测试_参数校验(池基类):
    def test_非法参数一律参数不合法(self):
        for 结果 in (
            连接数据库(""),
            连接数据库("不是URL", 2, 2),
            连接数据库(连接串, 0, 2),
            连接数据库(连接串, 101, 2),
            连接数据库(连接串, 2, 0),
            连接数据库(连接串, True, 2),
            调用(查询数据库, "x", "SELECT 1"),
            调用(查询数据库, 1, ""),
            调用(事务执行数据库, 1, []),
            调用(关闭数据库连接, "x"),
        ):
            self.assertFalse(结果.成功, 结果.错误说明)
            self.assertEqual(结果.错误码, "参数不合法", 结果.错误说明)

    def test_句柄失效错误码(self):
        for 结果 in (
            查询数据库(999999, "SELECT 1"),
            事务执行数据库(999999, ["SELECT 1"]),
            连接池状态(999999),
        ):
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "句柄失效")

    def test_无服务端口明确失败(self):
        结果 = 连接数据库(无服务连接串, 2, 2)
        self.assertFalse(结果.成功, "无服务端口不得假装建池成功")
        self.assertIn(结果.错误码, ("连接失败", "超时", "查询失败"), 结果.错误说明)


class 测试_有界并发(池基类):
    def test_并发借出不超过池上限(self):
        """24 线程并发 6 轮：借出连接数任何时刻都不得超过池大小。"""
        创建 = 连接数据库(self.连接串, 4, 5)
        self.assertTrue(创建.成功, 创建.错误说明)
        句柄 = 取值(创建)["数据库句柄"]
        峰值借出 = 0
        峰值锁 = threading.Lock()
        失败: list[str] = []

        def 单线程(序号: int) -> None:
            nonlocal 峰值借出
            for 轮 in range(6):
                查 = 查询数据库(句柄, "SELECT %s::int AS 值", [序号 * 100 + 轮], 5)
                事务 = 事务执行数据库(句柄, ["SELECT 1"], 5)
                if not 查.成功 or not 事务.成功:
                    失败.append(f"{查.错误码}{查.错误说明}/{事务.错误码}{事务.错误说明}")
                状态 = 连接池状态(句柄)
                借出 = 取值(状态).get("借出连接数", 0)
                with 峰值锁:
                    峰值借出 = max(峰值借出, 借出)

        try:
            起点 = time.monotonic()
            with ThreadPoolExecutor(max_workers=24) as 池:
                list(池.map(单线程, range(24)))
            耗时 = time.monotonic() - 起点
            self.assertEqual(失败, [], f"并发调用出现失败: {失败[:3]}")
            self.assertLessEqual(峰值借出, 4, f"借出连接数 {峰值借出} 超过池上限 4（并发失控）")
            状态 = 取值(连接池状态(句柄))
            self.assertEqual(状态["借出连接数"], 0, "压测后仍有未归还连接")
            self.assertLessEqual(状态["已创建连接数"], 4)
            self.assertEqual(状态["空闲连接数"] + 状态["借出连接数"], 状态["已创建连接数"],
                             "空闲 + 借出 必须等于已创建")
            self.assertLess(耗时, 30, f"并发压测耗时异常: {耗时:.2f}s")
        finally:
            关闭数据库连接(句柄)

    def test_查询失败不清空池(self):
        """查询失败 → 该连接丢弃但池可继续服务；后续借用必须成功。"""
        创建 = 连接数据库(self.连接串, 2, 5)
        self.assertTrue(创建.成功, 创建.错误说明)
        句柄 = 取值(创建)["数据库句柄"]
        try:
            坏 = 查询数据库(句柄, "SELECT * FROM 绝对不存在的表_回归", [], 5)
            self.assertFalse(坏.成功)
            self.assertEqual(坏.错误码, "查询失败", 坏.错误说明)
            好 = 查询数据库(句柄, "SELECT 1 AS 一", [], 5)
            self.assertTrue(好.成功, 好.错误说明)
            self.assertEqual(取值(好)["行列表"][0]["一"], 1)
            状态 = 取值(连接池状态(句柄))
            self.assertFalse(状态["已关闭"])
            self.assertEqual(状态["借出连接数"], 0)
        finally:
            关闭数据库连接(句柄)

    def test_事务失败整体回滚(self):
        """事务含非法语句 → 失败并且已回滚，随后池仍可服务。"""
        创建 = 连接数据库(self.连接串, 2, 5)
        self.assertTrue(创建.成功, 创建.错误说明)
        句柄 = 取值(创建)["数据库句柄"]
        try:
            结果 = 事务执行数据库(句柄, ["SELECT 1", "SLECT 错误语法"], 5)
            self.assertFalse(结果.成功)
            self.assertIn("已回滚", 结果.错误说明)
            后续 = 查询数据库(句柄, "SELECT 2 AS 二", [], 5)
            self.assertTrue(后续.成功, 后续.错误说明)
        finally:
            关闭数据库连接(句柄)


class 测试_句柄生命周期(池基类):
    def test_释放后旧句柄失效且重复关闭幂等(self):
        创建 = 连接数据库(self.连接串, 2, 5)
        self.assertTrue(创建.成功, 创建.错误说明)
        句柄 = 取值(创建)["数据库句柄"]
        首次 = 关闭数据库连接(句柄)
        self.assertTrue(首次.成功)
        self.assertTrue(取值(首次)["已关闭"])
        失效 = 查询数据库(句柄, "SELECT 1", [], 5)
        self.assertFalse(失效.成功)
        self.assertEqual(失效.错误码, "句柄失效")
        再次 = 关闭数据库连接(句柄)
        self.assertTrue(再次.成功, "重复关闭必须保持幂等成功")
        self.assertTrue(取值(再次)["已关闭"])

    def test_池状态字段与实现一致(self):
        创建 = 连接数据库(self.连接串, 3, 5)
        self.assertTrue(创建.成功, 创建.错误说明)
        句柄 = 取值(创建)["数据库句柄"]
        try:
            状态 = 连接池状态(句柄)
            self.assertTrue(状态.成功, 状态.错误说明)
            值 = 取值(状态)
            self.assertEqual(sorted(值),
                             sorted(["最大连接数", "已创建连接数", "空闲连接数",
                                     "借出连接数", "已关闭"]))
            self.assertEqual(值["最大连接数"], 3)
            self.assertIs(type(值["已关闭"]), bool, "已关闭 必须是真正逻辑型")
        finally:
            关闭数据库连接(句柄)


class 测试_契约一致(unittest.TestCase):
    def test_注册能力与声明定义一致(self):
        注册表 = 能力注册表()
        注册能力(注册表)
        声明 = json.loads((包目录 / "包声明.json").read_text(encoding="utf-8"))
        定义 = json.loads((包目录 / "能力定义.json").read_text(encoding="utf-8"))
        声明能力 = sorted(能力["能力id"] for 能力 in 声明["能力"])
        定义能力 = sorted(能力["能力id"] for 能力 in 定义["能力列表"])
        self.assertEqual(sorted(注册表.能力id列表), 声明能力)
        self.assertEqual(声明能力, 定义能力)
        for 名称 in 声明能力 + 定义能力:
            self.assertFalse(名称.endswith(旧能力后缀), f"旧连接串能力残留: {名称}")

    def test_参数契约完整(self):
        契约 = json.loads((包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        # 契约版本恒等于唯一事实源（哲学第 20 条）——**断言事实源，不写死字面量**，
        # 否则每次平台版本变化都要回来改测试（「一改全改」的根源）。
        self.assertEqual(契约["契约版本"], 契约版本)
        for 条目 in 契约["能力契约"]:
            for 参数 in 条目["参数"]:
                self.assertIn("必填", 参数, f"{条目['能力id']} 参数 {参数['名称']} 缺 必填")
                self.assertIn("说明", 参数, f"{条目['能力id']} 参数 {参数['名称']} 缺 说明")


if __name__ == "__main__":
    unittest.main()
