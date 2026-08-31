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
            项目id="项目甲", 用户id="用户甲", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        self.assertIsInstance(返回["句柄"], int)
        句柄 = 返回["句柄"]

        状态 = self.网关.处理(网关请求(
            操作="资源状态", 句柄=句柄, 项目id="项目甲", 用户id="用户甲",
            权限范围=["查询"],
        )).转字典()
        self.assertTrue(状态["成功"])
        self.assertEqual(状态["值"]["状态"], "有效")

        读取 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.读取批次",
            参数={"资源句柄": 句柄}, 项目id="项目甲", 用户id="用户甲",
            权限范围=["调用"],
        )).转字典()
        self.assertTrue(读取["成功"])
        self.assertEqual(读取["值"]["收到句柄"], 句柄)

        关闭 = self.网关.处理(网关请求(
            操作="资源关闭", 句柄=句柄, 项目id="项目甲", 用户id="用户甲",
            权限范围=["调用"],
        )).转字典()
        self.assertTrue(关闭["成功"])
        self.assertEqual(关闭["值"]["状态"], "已失效")

    def test_资源未收敛时保留句柄并阻断最终失效(self) -> None:
        def 清理失败() -> None:
            raise RuntimeError("模拟连接仍在使用")

        资源服务 = self.后端.资源句柄服务
        公开 = 资源服务.创建(
            资源id="测试-未收敛资源", 项目id="项目甲", 所有者="用户甲",
        )
        句柄 = 公开["句柄"]
        绑定成功, _ = 资源服务.句柄体系.登记资源(
            句柄, 资源类型="连接", 清理函数=清理失败,
        )
        self.assertTrue(绑定成功)

        with self.assertRaisesRegex(RuntimeError, "资源未收敛"):
            资源服务.关闭(句柄, 项目id="项目甲", 所有者="用户甲")

        状态 = 资源服务.状态(句柄, 项目id="项目甲", 所有者="用户甲")
        self.assertIsNotNone(状态)
        self.assertEqual(状态["状态"], "有效")
        账本 = 资源服务.权威状态.读取句柄(句柄)
        self.assertIsNotNone(账本)
        self.assertEqual(账本["状态"], "有效")

    def test_跨项目查询拒绝(self) -> None:
        返回 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.创建批次",
            获取句柄=True,
            项目id="项目甲", 用户id="用户甲", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        状态 = self.网关.处理(网关请求(
            操作="资源状态", 句柄=返回["句柄"], 项目id="项目乙", 用户id="用户甲",
            权限范围=["查询"],
        )).转字典()
        self.assertFalse(状态["成功"])
        self.assertEqual(状态["错误码"], "权限不足")


if __name__ == "__main__":
    unittest.main()
