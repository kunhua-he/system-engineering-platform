"""资源句柄网关测试：句柄是外部精准查询键，模块仍由自身完成能力逻辑。"""

from __future__ import annotations

import unittest
from pathlib import Path

from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心, 网关请求


class 资源句柄网关测试(unittest.TestCase):
    def setUp(self) -> None:
        self.后端 = 后端核心(Path(__file__).resolve().parents[2])
        self.assertTrue(self.后端.启动().成功)

        def 返回批次句柄() -> dict:
            return {"句柄": "批次-甲", "批次数": 2}

        def 读取批次(资源句柄: str) -> dict:
            return {"收到句柄": 资源句柄, "查询方式": "模块内部精准查询"}

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
            操作="调用能力", 能力id="测试.创建批次", 获取句柄=True,
            项目id="项目甲", 用户id="用户甲", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        self.assertEqual(返回["句柄"], "批次-甲")

        状态 = self.网关.处理(网关请求(
            操作="资源状态", 句柄="批次-甲", 项目id="项目甲", 用户id="用户甲",
            权限范围=["查询"],
        )).转字典()
        self.assertTrue(状态["成功"])
        self.assertEqual(状态["值"]["状态"], "有效")

        读取 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.读取批次",
            参数={"资源句柄": "批次-甲"}, 项目id="项目甲", 用户id="用户甲",
            权限范围=["调用"],
        )).转字典()
        self.assertTrue(读取["成功"])
        self.assertEqual(读取["值"]["收到句柄"], "批次-甲")

        关闭 = self.网关.处理(网关请求(
            操作="资源关闭", 句柄="批次-甲", 项目id="项目甲", 用户id="用户甲",
            权限范围=["调用"],
        )).转字典()
        self.assertTrue(关闭["成功"])
        self.assertEqual(关闭["值"]["状态"], "已失效")

    def test_跨项目查询拒绝(self) -> None:
        返回 = self.网关.处理(网关请求(
            操作="调用能力", 能力id="测试.创建批次", 获取句柄=True,
            项目id="项目甲", 用户id="用户甲", 权限范围=["调用"],
        )).转字典()
        self.assertTrue(返回["成功"])
        状态 = self.网关.处理(网关请求(
            操作="资源状态", 句柄="批次-甲", 项目id="项目乙", 用户id="用户甲",
            权限范围=["查询"],
        )).转字典()
        self.assertFalse(状态["成功"])
        self.assertEqual(状态["错误码"], "权限不足")


if __name__ == "__main__":
    unittest.main()
