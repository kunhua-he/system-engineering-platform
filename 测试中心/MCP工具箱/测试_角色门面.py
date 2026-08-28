"""单网关模式：网关工具面、代码地图输出与子代理继承协议测试。

覆盖：网关直通（指南工具统一网关说明）；开工上下文携带单网关标记；
代码地图输出过滤（单网关不过滤源码）；子代理继承协议已文档化。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path

服务路径 = Path(__file__).resolve().parents[2] / "MCP工具箱" / "项目服务.py"
sys.path.insert(0, str(服务路径.parent))
规格 = importlib.util.spec_from_file_location("系统工程平台项目服务", 服务路径)
assert 规格 and 规格.loader
服务模块 = importlib.util.module_from_spec(规格)
规格.loader.exec_module(服务模块)

# 与服务模块共用同一角色权限实例，避免包/顶层双导入导致异常类不一致
角色权限模块 = sys.modules.get("MCP工具箱.角色权限") or sys.modules["角色权限"]
网关实例名 = 角色权限模块.网关实例名
网关角色名 = 角色权限模块.网关角色名


class 网关工具面测试(unittest.TestCase):
    """网关直通：指南统一、越权语义保留、开工上下文单网关标记。"""

    def _调用(self, 工具名: str, 参数: dict) -> dict:
        文本 = asyncio.run(服务模块.调用工具(工具名, 参数))
        return json.loads(文本[0].text)

    def test_指南工具统一返回网关说明(self) -> None:
        for 工具名 in ("core_development_guide", "release_guide",
                       "support_library_development_guide", "platform_maintenance_guide"):
            档案 = self._调用(工具名, {})
            self.assertEqual(档案["模式"], "单网关（无角色）")
            self.assertEqual(档案["实例"], 网关实例名)
            self.assertIn("工具", 档案)

    def test_role_profile返回网关档案(self) -> None:
        档案 = self._调用("role_profile", {})
        self.assertEqual(档案["模式"], "单网关（无角色）")
        self.assertGreater(档案["可用工具数"], 0)
        self.assertIn("tool_catalog", 档案["可用工具"])

    def test_开工上下文携带单网关标记与开工id(self) -> None:
        上下文 = 服务模块._开工上下文("角色门面测试", 1)
        self.assertEqual(上下文["项目"]["MCP实例"], 网关实例名)
        self.assertEqual(上下文["项目"]["角色门面"], "单网关（无角色）")
        self.assertGreater(len(上下文["项目"]["开工id"]), 0)

    def test_未知工具名拒绝(self) -> None:
        """S9：未知工具名经外层兜底返回 参数无效，不抛异常。"""
        结果 = self._调用("不存在的工具", {})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "参数无效")

    def test_工具列表为全部工具(self) -> None:
        工具名表 = {工具.name for 工具 in asyncio.run(服务模块.工具列表())}
        全部 = {定义.name for 定义 in 服务模块._工具定义列表}
        self.assertEqual(工具名表, 全部)
        self.assertIn("tool_catalog", 工具名表)


class 代码地图输出测试(unittest.TestCase):
    """单网关：代码地图输出不再按角色过滤，全部保留。"""

    def test_代码地图输出全部保留(self) -> None:
        标记 = chr(96)
        原文 = (
            f"**{标记}运行核心/加载器/加载器.py{标记}** — 加载\n加载内容\n\n"
            f"**{标记}平台控制面/包仓库/制品.py{标记}** — 秘密\n不应过滤\n\n"
            f"**{标记}项目适配层/依赖锁.py{标记}** — 锁\n锁内容\n"
        )
        结果 = 服务模块._过滤代码地图输出(原文, 服务模块.全部目录表)
        self.assertIn("运行核心/加载器/加载器.py", 结果)
        self.assertIn("平台控制面/包仓库/制品.py", 结果)
        self.assertIn("项目适配层/依赖锁.py", 结果)
        self.assertIn("锁内容", 结果)


class 子代理继承协议测试(unittest.TestCase):
    """子代理继承协议已文档化且要素齐全（文档归属其他维护面，只读断言存在性）。"""

    def test_子代理继承协议文档化且要素齐全(self) -> None:
        文档路径 = 服务模块.项目根目录 / "AGENTS.md"
        self.assertTrue(文档路径.is_file(), "子代理继承协议文档缺失")
        文本 = 文档路径.read_text(encoding="utf-8")
        for 要素 in ["project_context", "子代理", "递归继承", "mcp_feedback",
                      "反馈", "feedback_review", "开工id", "verify_and_record"]:
            self.assertIn(要素, 文本, f"协议文档缺少要素: {要素}")


if __name__ == "__main__":
    unittest.main()