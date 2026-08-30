"""P2-01：简单窗口状态必须存入网关受管资源，不得使用模块全局字典。"""
from __future__ import annotations

import sys
import importlib
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 后端核心.后端核心 import 后端核心
窗口模块: Any = importlib.import_module("模块库.简单窗口")
from 运行核心.能力调用.HTTP连接器 import HTTP连接器
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.资源协调 import 资源句柄服务


class 测试简单窗口受管状态(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.临时对象 = tempfile.TemporaryDirectory(prefix="简单窗口受管状态_")
        cls.后端 = 后端核心(系统根)
        cls.后端.资源句柄服务.关闭服务()
        cls.后端.资源句柄服务 = 资源句柄服务(Path(cls.临时对象.name) / "状态")
        from 支持库.后端.系统核心支持库.资源管理 import 设置受管状态服务
        设置受管状态服务(cls.后端.资源句柄服务)
        启动 = cls.后端.启动()
        if not 启动.成功:
            raise RuntimeError(启动.错误说明)
        cls.网关 = 本地网关服务器.创建测试服务器(
            网关核心实例=网关核心(cls.后端), 端口=0)
        成功, 消息 = cls.网关.启动()
        if not 成功:
            raise RuntimeError(消息)
        窗口模块.设置HTTP连接器(HTTP连接器(网关端口=cls.网关.端口))

    @classmethod
    def tearDownClass(cls) -> None:
        窗口模块.设置HTTP连接器(None)
        cls.网关.优雅停止()
        cls.后端.优雅关闭()
        cls.临时对象.cleanup()

    def _创建(self, 名称: str) -> int:
        结果 = 窗口模块.创建窗口(名称, f"标题-{名称}", 320, 240)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIsInstance(结果.值, dict)
        值 = 结果.值
        assert isinstance(值, dict)
        self.assertIn("句柄", 值, "创建窗口必须返回网关状态机生成的受管句柄")
        句柄 = 值["句柄"]
        self.assertIsInstance(句柄, int)
        return 句柄

    def test_创建后跨调用打开和读取状态(self) -> None:
        句柄 = self._创建("跨调用窗")
        打开 = 窗口模块.打开窗口(句柄)
        self.assertTrue(打开.成功, 打开.错误说明)
        描述 = 窗口模块.获取窗口描述(句柄)
        self.assertTrue(描述.成功, 描述.错误说明)
        值 = 描述.值
        assert isinstance(值, dict)
        self.assertEqual(值["状态"], "打开")
        self.assertEqual(值["窗口id"], "跨调用窗")

    def test_不同句柄状态完全隔离(self) -> None:
        甲 = self._创建("隔离窗甲")
        乙 = self._创建("隔离窗乙")
        self.assertTrue(窗口模块.打开窗口(甲).成功)
        self.assertTrue(窗口模块.传递参数(乙, {"归属": "乙"}).成功)
        甲描述 = 窗口模块.获取窗口描述(甲).值
        乙描述 = 窗口模块.获取窗口描述(乙).值
        assert isinstance(甲描述, dict) and isinstance(乙描述, dict)
        self.assertEqual(甲描述["状态"], "打开")
        self.assertNotEqual(乙描述["状态"], "打开")
        self.assertNotEqual(甲描述.get("参数"), {"归属": "乙"})
        self.assertEqual(乙描述["参数"], {"归属": "乙"})

    def test_释放后句柄不可继续访问(self) -> None:
        句柄 = self._创建("释放窗")
        释放 = 窗口模块.释放窗口(句柄)
        self.assertTrue(释放.成功, 释放.错误说明)
        再读 = 窗口模块.获取窗口描述(句柄)
        self.assertFalse(再读.成功)
        self.assertIn(再读.错误码, {"句柄无效", "句柄已过期", "窗口不存在"})

    def test_并发不同窗口不串状态(self) -> None:
        句柄表 = [self._创建(f"并发窗-{序号}") for 序号 in range(6)]
        结果表: list[bool] = []

        def 更新(序号: int, 句柄: int) -> None:
            打开 = 窗口模块.打开窗口(句柄)
            传参 = 窗口模块.传递参数(句柄, {"序号": 序号})
            结果表.append(打开.成功 and 传参.成功)

        线程表 = [threading.Thread(target=更新, args=(序号, 句柄))
                   for 序号, 句柄 in enumerate(句柄表)]
        for 线程 in 线程表:
            线程.start()
        for 线程 in 线程表:
            线程.join(timeout=3)
            self.assertFalse(线程.is_alive())
        self.assertEqual(结果表, [True] * 6)
        for 序号, 句柄 in enumerate(句柄表):
            描述 = 窗口模块.获取窗口描述(句柄)
            self.assertTrue(描述.成功, 描述.错误说明)
            值 = 描述.值
            assert isinstance(值, dict)
            self.assertEqual(值["窗口id"], f"并发窗-{序号}")
            self.assertEqual(值["参数"], {"序号": 序号})


    def test_模块只通过统一调用能力接口(self) -> None:
        源码 = (系统根 / "模块库" / "简单窗口" / "实现" / "简单窗口.py").read_text(encoding="utf-8")
        self.assertIn("_连接器.调用能力", 源码)
        for 专用接口 in (
            "_连接器.创建受管状态", "_连接器.读取受管状态",
            "_连接器.更新受管状态", "_连接器.释放受管状态",
        ):
            self.assertNotIn(专用接口, 源码, f"禁止第二调用接口: {专用接口}")


if __name__ == "__main__":
    unittest.main()
