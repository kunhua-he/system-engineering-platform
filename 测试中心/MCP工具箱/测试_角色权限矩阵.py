"""单网关模式：角色权限收敛为统一网关测试（无角色白名单，网关直通）。

覆盖：网关常量与说明；未知工具名拒绝（S9 返回参数无效）；指南工具统一
返回网关说明；越权拒绝语义保留（供未授权开工id等复用）；工具列表与
工具目录返回全部工具。
"""

from __future__ import annotations

import asyncio
import sys
import unittest

from MCP工具箱 import 项目服务 as 服务模块
from MCP工具箱 import 角色权限 as 角色权限模块

网关实例名 = 角色权限模块.网关实例名
网关角色名 = 角色权限模块.网关角色名
网关说明 = 角色权限模块.网关说明
获取角色指南 = 角色权限模块.获取角色指南
越权拒绝 = 角色权限模块.越权拒绝


class 网关常量测试(unittest.TestCase):
    """单网关：实例名固定、角色名固定、无角色白名单。"""

    def test_网关常量固定(self) -> None:
        self.assertEqual(网关实例名, "system_engineering_toolkit")
        self.assertEqual(网关角色名, "平台维护者")

    def test_网关说明携带边界(self) -> None:
        说明 = 网关说明()
        self.assertEqual(说明["实例"], 网关实例名)
        self.assertEqual(说明["模式"], "单网关（无角色）")
        self.assertIn("权限模式", 说明)
        self.assertIn("边界", 说明)

    def test_指南工具统一返回网关说明(self) -> None:
        for 工具名 in [
            "support_library_development_guide", "module_development_guide",
            "core_development_guide", "project_development_guide",
            "platform_build_development_guide", "platform_maintenance_guide",
            "release_guide",
        ]:
            指南 = 获取角色指南(工具名)
            self.assertEqual(指南["模式"], "单网关（无角色）", f"{工具名} 应统一返回网关说明")
            self.assertEqual(指南["实例"], 网关实例名, f"{工具名}")
            self.assertEqual(指南["工具"], 工具名, f"{工具名}")

    def test_指南工具对任意名字返回网关说明(self) -> None:
        """无角色专属指南：任意工具名都返回统一网关说明，不抛异常。"""
        指南 = 获取角色指南("不存在的工具")
        self.assertEqual(指南["模式"], "单网关（无角色）")
        self.assertEqual(指南["工具"], "不存在的工具")

    def test_越权拒绝语义保留(self) -> None:
        异常 = 越权拒绝("未授权", "测试消息")
        self.assertEqual(异常.错误码, "未授权")
        self.assertIn("测试消息", 异常.消息)


class 网关工具面测试(unittest.TestCase):
    """网关直通：服务端工具列表与工具目录返回全部工具，可调用性全部为真。"""

    def setUp(self) -> None:
        self.工具表 = asyncio.run(服务模块.工具列表())
        self.全部名称 = {定义.name for 定义 in 服务模块._工具定义列表}

    def test_工具列表为全部工具(self) -> None:
        self.assertEqual(len(self.工具表), len(self.全部名称))
        self.assertTrue(self.全部名称.issubset({工具.name for 工具 in self.工具表}))

    def test_工具目录全部可调用(self) -> None:
        目录 = 服务模块._工具目录()
        self.assertEqual(目录["当前实例"], 网关实例名)
        self.assertEqual(目录["当前实例可用工具数"], len(self.全部名称))
        for 项 in 目录["工具清单"]:
            self.assertTrue(项["当前实例可调用"], f"{项['协议名']} 应网关直通")

    def test_未知分类返回空清单(self) -> None:
        数据 = 服务模块._工具目录("不存在的分类")
        self.assertEqual(数据["条目数"], 0)
        self.assertEqual(数据["工具清单"], [])

    def test_未知工具名调用返回参数无效(self) -> None:
        """S9：未知工具名经外层兜底返回 参数无效，不抛异常。"""
        文本 = asyncio.run(服务模块.调用工具("不存在的工具", {}))
        数据 = __import__("json").loads(文本[0].text)
        self.assertFalse(数据["成功"])
        self.assertEqual(数据["错误码"], "参数无效")


if __name__ == "__main__":
    unittest.main()