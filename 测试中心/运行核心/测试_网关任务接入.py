"""网关任务接入测试：提交/轮询/取消/超时/失败码回带 全链路（假后端，独立进程真跑）。"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from 运行核心.统一网关.网关核心 import 网关核心, 网关请求, 网关响应
from 运行核心.任务调度.任务接入 import 构造任务系统, 任务追踪键

终态 = {"成功", "失败", "已取消", "超时", "崩溃"}


class 假结果:
    def __init__(self, 成功: bool = True, 值=None, 错误码: str = "", 错误说明: str = "") -> None:
        self.成功 = 成功
        self.值 = 值
        self.错误码 = 错误码
        self.错误说明 = 错误说明


class 假实现:
    def __init__(self, 参数: list) -> None:
        self.参数 = 参数


class 假注册表:
    def __init__(self, 能力表: dict) -> None:
        self.能力表 = dict(能力表)

    @property
    def 能力id列表(self) -> list:
        return list(self.能力表)

    def 获取(self, 能力id: str):
        return self.能力表.get(能力id)


class 假后端:
    """只实现网关与执行器真正用到的面：注册表 + 调用。"""

    能力表 = {
        "示例.快": 假实现([{"名称": "文本", "类型": "文本型", "必填": True}]),
        "示例.慢": 假实现([]),
        "示例.失败": 假实现([]),
    }

    def __init__(self) -> None:
        self.注册表 = 假注册表(self.能力表)

    def 调用(self, 能力id: str, 参数: dict, *, 上下文=None, 超时秒: float = 10.0) -> 假结果:
        if 能力id == "示例.快":
            return 假结果(值={"回显": dict(参数), "上下文能力": 上下文.能力id if 上下文 else ""})
        if 能力id == "示例.慢":
            time.sleep(5)
            return 假结果(值={"睡醒": True})
        if 能力id == "示例.失败":
            return 假结果(成功=False, 错误码="外部依赖不可用", 错误说明="假上游 503")
        return 假结果(成功=False, 错误码="能力不存在", 错误说明=能力id)


class 网关任务接入测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._临时目录 = tempfile.TemporaryDirectory(prefix="任务接入测试_")
        cls.后端 = 假后端()
        cls.任务系统实例 = 构造任务系统(
            cls.后端, 存储目录=Path(cls._临时目录.name) / "任务")
        cls.网关 = 网关核心(cls.后端, 任务系统=cls.任务系统实例)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.任务系统实例.关闭全部()
        cls._临时目录.cleanup()

    def 处理(self, **字段) -> 网关响应:
        return self.网关.处理(网关请求(**字段))

    def 等到终态(self, 任务id: str, 超时秒: float = 15.0) -> dict:
        截止 = time.monotonic() + 超时秒
        while time.monotonic() < 截止:
            响应 = self.处理(操作="任务查询", 参数={"任务id": 任务id})
            self.assertTrue(响应.成功, 响应.错误说明)
            任务 = 响应.值
            if 任务.get("状态") in 终态:
                return 任务
            time.sleep(0.05)
        self.fail(f"任务 {任务id} 未在 {超时秒} 秒内进入终态")

    def test_每个正式能力都注册了执行器(self) -> None:
        self.assertEqual(
            sorted(self.任务系统实例.执行函数表),
            sorted(假后端.能力表),
        )

    def test_提交后轮询到成功且追踪键不下发能力(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.快",
                          参数={"文本": "你好"}, 超时秒=30)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务id = 响应.值["任务id"]
        任务 = self.等到终态(任务id)
        self.assertEqual(任务["状态"], "成功")
        self.assertEqual(任务["结果"]["回显"], {"文本": "你好"})
        self.assertEqual(任务["结果"]["上下文能力"], "示例.快")
        self.assertNotIn(任务追踪键, 任务["结果"]["回显"])

    def test_能力自身错误码原样回带(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.失败", 参数={}, 超时秒=30)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务 = self.等到终态(响应.值["任务id"])
        self.assertEqual(任务["状态"], "失败")
        self.assertEqual(任务["错误码"], "外部依赖不可用")
        self.assertEqual(任务["错误说明"], "假上游 503")

    def test_未知能力提交前就被拒绝(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.不存在", 参数={}, 超时秒=30)
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "能力不存在")

    def test_参数不合契约提交前就被拒绝(self) -> None:
        """兼容口径（哲学第 21 条）：未知字段被边界剔除后照常提交，只有强制参数不满足才拒。

        旧行为是「未知参数即 400」，已废止——上游多传一个字段不该让长任务提交失败。
        """
        未知参数 = self.处理(操作="任务提交", 能力id="示例.快",
                            参数={"文本": "你好", "不认识": 1}, 超时秒=30)
        self.assertTrue(未知参数.成功, 未知参数.错误说明)

        缺必填 = self.处理(操作="任务提交", 能力id="示例.快", 参数={}, 超时秒=30)
        self.assertFalse(缺必填.成功)
        self.assertEqual(缺必填.错误码, "参数不合法")
        self.assertIn("文本", 缺必填.错误说明)

        类型不符 = self.处理(操作="任务提交", 能力id="示例.快",
                            参数={"文本": 123}, 超时秒=30)
        self.assertFalse(类型不符.成功)
        self.assertEqual(类型不符.错误码, "参数不合法")

    def test_取消长任务进入已取消(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.慢", 参数={}, 超时秒=60)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务id = 响应.值["任务id"]
        取消 = self.处理(操作="任务取消", 参数={"任务id": 任务id})
        self.assertTrue(取消.成功, 取消.错误说明)
        任务 = self.等到终态(任务id)
        self.assertEqual(任务["状态"], "已取消")

    def test_超过任务超时秒判超时(self) -> None:
        响应 = self.处理(操作="任务提交", 能力id="示例.慢", 参数={}, 超时秒=0.4)
        self.assertTrue(响应.成功, 响应.错误说明)
        任务 = self.等到终态(响应.值["任务id"])
        self.assertEqual(任务["状态"], "超时")

    def test_未接入任务系统时不产生任务(self) -> None:
        # 网关把内部 ConnectionError 统一映射为公开错误码「提供者不可用」，
        # 处理() 不向外抛异常；这里锁住「没接任务系统就不会递交任务」。
        裸网关 = 网关核心(假后端)
        响应 = 裸网关.处理(网关请求(操作="任务提交", 能力id="示例.快",
                                   参数={"文本": "你好"}, 超时秒=30))
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "提供者不可用")


if __name__ == "__main__":
    unittest.main()
