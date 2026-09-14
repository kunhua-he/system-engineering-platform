"""资源句柄网关测试：真实网关生成整数句柄并维护生命周期账本。"""

from __future__ import annotations

import unittest
from pathlib import Path

from 后端核心.后端核心 import 后端核心
from 公共契约.基础类型.结果类型 import 结果
from 运行核心.统一网关.网关核心 import 网关核心, 网关请求


class 资源句柄网关测试(unittest.TestCase):
    def setUp(self) -> None:
        self.后端 = 后端核心(Path(__file__).resolve().parents[2])
        self.assertTrue(self.后端.启动().成功)

        def 返回批次句柄() -> 结果:
            return 结果.成功结果({"句柄": "提供者不得自造", "批次数": 2})

        def 读取批次(资源句柄: int) -> 结果:
            return 结果.成功结果({"收到句柄": 资源句柄, "查询方式": "模块内部精准查询"})

        self.后端.注册能力("测试.创建批次", 返回批次句柄)
        self.后端.注册能力(
            "测试.读取批次", 读取批次,
            参数=[{"名称": "资源句柄", "类型": "句柄型"}],
        )
        self.网关 = 网关核心(self.后端)

    def tearDown(self) -> None:
        self.后端.优雅关闭()

    def test_返回句柄后可查询并关闭(self) -> None:
        返回 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.创建批次",
            获取句柄=True,
            项目id="项目1", 用户id="用户1", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        self.assertIsInstance(返回["句柄"], int)
        句柄 = 返回["句柄"]

        状态 = self.网关.处理(网关请求(
            操作="资源状态", 句柄=句柄, 项目id="项目1", 用户id="用户1",
            权限范围=["查询"],
        )).转字典()
        self.assertTrue(状态["成功"])
        self.assertEqual(状态["值"]["状态"], "有效")

        读取 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.读取批次",
            参数={"资源句柄": 句柄}, 项目id="项目1", 用户id="用户1",
            权限范围=["调用"],
        )).转字典()
        self.assertTrue(读取["成功"])
        self.assertEqual(读取["值"]["收到句柄"], 句柄)

        关闭 = self.网关.处理(网关请求(
            操作="资源关闭", 句柄=句柄, 项目id="项目1", 用户id="用户1",
            权限范围=["调用"],
        )).转字典()
        self.assertTrue(关闭["成功"])
        self.assertEqual(关闭["值"]["状态"], "已失效")

    def test_资源未收敛时保留句柄并阻断最终失效(self) -> None:
        def 清理失败() -> None:
            raise RuntimeError("模拟连接仍在使用")

        资源服务 = self.后端.资源句柄服务
        公开 = 资源服务.创建(
            资源id="测试-未收敛资源", 项目id="项目1", 所有者="用户1",
        )
        句柄 = 公开["句柄"]
        绑定成功, _ = 资源服务.句柄体系.登记资源(
            句柄, 资源类型="连接", 清理函数=清理失败,
        )
        self.assertTrue(绑定成功)

        with self.assertRaisesRegex(RuntimeError, "资源未收敛"):
            资源服务.关闭(句柄, 项目id="项目1", 所有者="用户1")

        状态 = 资源服务.状态(句柄, 项目id="项目1", 所有者="用户1")
        self.assertIsNotNone(状态)
        self.assertEqual(状态["状态"], "有效")
        账本 = 资源服务.权威状态.读取句柄(句柄)
        self.assertIsNotNone(账本)
        self.assertEqual(账本["状态"], "有效")

    def test_跨项目查询拒绝(self) -> None:
        返回 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.创建批次",
            获取句柄=True,
            项目id="项目1", 用户id="用户1", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        状态 = self.网关.处理(网关请求(
            操作="资源状态", 句柄=返回["句柄"], 项目id="项目2", 用户id="用户1",
            权限范围=["查询"],
        )).转字典()
        self.assertFalse(状态["成功"])
        self.assertEqual(状态["错误码"], "权限不足")

    def test_省略身份不得查询或关闭他人句柄(self) -> None:
        公开 = self.后端.资源句柄服务.创建(
            资源id="测试-身份必填", 项目id="项目1", 所有者="用户1",
        )
        句柄 = 公开["句柄"]
        with self.assertRaises(PermissionError):
            self.后端.资源句柄服务.状态(句柄)
        with self.assertRaises(PermissionError):
            self.后端.资源句柄服务.关闭(句柄)

    def _句柄请求(self, 操作: str, 句柄: int, **额外) -> dict:
        请求 = {"操作": 操作, "句柄": 句柄, "项目id": "项目1", "用户id": "用户1",
                "权限范围": ["调用"] if 操作 != "资源状态" else ["查询"]}
        请求.update(额外)
        return self.网关.处理(网关请求(**请求)).转字典()

    def test_不存在句柄的资源三操作报句柄无效(self) -> None:
        """句柄缺失属句柄域：三操作都报「句柄无效」，不再误报「能力不存在」。"""
        for 操作 in ("资源状态", "资源续租", "资源关闭"):
            with self.subTest(操作=操作):
                结果 = self._句柄请求(操作, 999999)
                self.assertFalse(结果["成功"])
                self.assertEqual(结果["错误码"], "句柄无效")
                self.assertEqual(结果["错误说明"], "句柄不存在或格式错误")

    def test_资源续租已失效句柄报句柄已过期(self) -> None:
        返回 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.创建批次", 获取句柄=True,
            项目id="项目1", 用户id="用户1", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        句柄 = 返回["句柄"]
        关闭 = self._句柄请求("资源关闭", 句柄)
        self.assertTrue(关闭["成功"])

        续租 = self._句柄请求("资源续租", 句柄)
        self.assertFalse(续租["成功"])
        self.assertEqual(续租["错误码"], "句柄已过期")
        self.assertEqual(续租["错误说明"], "句柄已超时/释放/回收，不能复活")

    def test_资源关闭已失效句柄仍幂等成功(self) -> None:
        返回 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.创建批次", 获取句柄=True,
            项目id="项目1", 用户id="用户1", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        句柄 = 返回["句柄"]
        self.assertTrue(self._句柄请求("资源关闭", 句柄)["成功"])
        再次 = self._句柄请求("资源关闭", 句柄)
        self.assertTrue(再次["成功"], 再次)
        self.assertEqual(再次["值"]["状态"], "已失效")

    def test_资源续租跨项目仍报权限不足(self) -> None:
        返回 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.创建批次", 获取句柄=True,
            项目id="项目1", 用户id="用户1", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        续租 = self.网关.处理(网关请求(
            操作="资源续租", 句柄=返回["句柄"], 项目id="项目2", 用户id="用户1",
            权限范围=["调用"],
        )).转字典()
        self.assertFalse(续租["成功"])
        self.assertEqual(续租["错误码"], "权限不足")


if __name__ == "__main__":
    unittest.main()
