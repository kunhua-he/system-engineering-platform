"""句柄服务跨实例持久化回归：只通过公开服务和 SQLite 账本验证。"""

from __future__ import annotations

import tempfile
import time
import unittest
import json
import urllib.request
import urllib.parse
from pathlib import Path

from 运行核心.资源协调.句柄服务 import 资源句柄服务
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 公共契约.基础类型.逻辑类型 import 真, 假


class 句柄账本持久化测试(unittest.TestCase):
    def setUp(self) -> None:
        self.临时目录 = tempfile.TemporaryDirectory(prefix="句柄账本持久化_")
        self.状态目录 = Path(self.临时目录.name)

    def tearDown(self) -> None:
        self.临时目录.cleanup()

    def test_跨实例恢复并保留所有权和租约(self) -> None:
        第一实例 = 资源句柄服务(self.状态目录, 默认超时秒=30)
        首次 = 第一实例.创建(资源id="资源1", 项目id="项目1", 所有者="用户1")
        句柄id = 首次["句柄"]
        第二实例 = 资源句柄服务(self.状态目录, 默认超时秒=30)
        状态 = 第二实例.状态(句柄id, 项目id="项目1", 所有者="用户1")
        self.assertIsNotNone(状态)
        self.assertEqual(状态["状态"], "有效")
        self.assertEqual(状态["资源id"], "资源1")
        self.assertAlmostEqual(
            float(状态["元数据"]["租约截止"]),
            float(首次["元数据"]["租约截止"]),
            delta=1.0,
        )
        with self.assertRaises(PermissionError):
            第二实例.状态(句柄id, 项目id="项目2", 所有者="用户1")

    def test_续租同时持久化截止时间和心跳(self) -> None:
        第一实例 = 资源句柄服务(self.状态目录, 默认超时秒=30)
        首次 = 第一实例.创建(资源id="资源1")
        句柄id = 首次["句柄"]
        旧截止 = float(首次["元数据"]["租约截止"])
        time.sleep(0.01)
        续租后 = 第一实例.续租(句柄id, 租约秒=120)
        self.assertGreater(float(续租后["元数据"]["租约截止"]), 旧截止)
        第二实例 = 资源句柄服务(self.状态目录, 默认超时秒=30)
        恢复后 = 第二实例.状态(句柄id)
        self.assertIsNotNone(恢复后)
        self.assertAlmostEqual(
            float(恢复后["元数据"]["租约截止"]),
            float(续租后["元数据"]["租约截止"]),
            delta=1.0,
        )

    def test_已过期句柄不能续租复活(self) -> None:
        实例 = 资源句柄服务(self.状态目录, 默认超时秒=0.02)
        首次 = 实例.创建(资源id="资源1")
        句柄id = 首次["句柄"]
        time.sleep(0.05)
        with self.assertRaises((PermissionError, KeyError)):
            实例.续租(句柄id, 租约秒=30)
        self.assertEqual(实例.状态(句柄id)["状态"], "已失效")

    def test_登记字段类型漂移拒绝(self) -> None:
        实例 = 资源句柄服务(self.状态目录)
        首次 = 实例.创建(资源id="资源1")
        句柄id = 首次["句柄"]
        for 字段, 值 in (("资源id", 1), ("项目id", 1), ("所有者", 1),
                         ("句柄类型", 1), ("元数据", [])):
            参数 = {"句柄id": 句柄id, 字段: 值}
            with self.subTest(字段=字段), self.assertRaises(ValueError):
                实例.登记(**参数)

    def test_HTTP网关重启后跨实例查询句柄(self) -> None:
        """真实 HTTP 请求验证：服务重启后仍由 SQLite 提供句柄状态。"""
        class 后端:
            def __init__(self, 目录: Path) -> None:
                self.资源句柄服务 = 资源句柄服务(目录)

            def 资源状态(self, 句柄id, *, 项目id="", 所有者=""):
                return self.资源句柄服务.状态(句柄id, 项目id=项目id, 所有者=所有者)

            def 资源续租(self, 句柄id, *, 租约秒=300, 项目id="", 所有者=""):
                return self.资源句柄服务.续租(句柄id, 租约秒=租约秒, 项目id=项目id, 所有者=所有者)

            def 资源关闭(self, 句柄id, *, 项目id="", 所有者=""):
                return self.资源句柄服务.关闭(句柄id, 项目id=项目id, 所有者=所有者)

        第一个后端 = 后端(self.状态目录)
        句柄id = 第一个后端.资源句柄服务.创建(
            资源id="资源1", 项目id="项目1", 所有者="用户1")["句柄"]
        第一个网关 = 本地网关服务器(网关核心实例=网关核心(第一个后端), 端口=0,
                                   配置={"禁止客户端身份": 假, "要求凭证": 假})
        self.assertTrue(第一个网关.启动()[0])
        第一个网关.优雅停止()

        第二个后端 = 后端(self.状态目录)
        第二个网关 = 本地网关服务器(网关核心实例=网关核心(第二个后端), 端口=0,
                                    配置={"禁止客户端身份": 假, "要求凭证": 假})
        self.assertTrue(第二个网关.启动()[0])
        try:
            请求 = urllib.request.Request(
                urllib.parse.quote(
                    f"http://127.0.0.1:{第二个网关.端口}/网关/调用", safe=":/@._-"),
                data=json.dumps({"操作": "资源状态", "句柄": 句柄id,
                                 "项目id": "项目1", "用户id": "用户1"}).encode(),
                method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(请求, timeout=2) as 响应:
                返回 = json.loads(响应.read().decode())
            self.assertTrue(返回["成功"])
            self.assertEqual(返回["值"]["状态"], "有效")
        finally:
            第二个网关.优雅停止()


if __name__ == "__main__":
    unittest.main(verbosity=2)
