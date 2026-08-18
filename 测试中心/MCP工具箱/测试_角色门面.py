"""工作包四：四类角色工具门面、代码地图范围与越权阻断测试。

覆盖：平台维护者 / 核心开发者 / 项目开发者（项目适配开发者）/ 平台构建开发者。
断言越权真实拒绝（错误码：权限不足 / 角色越权），并验证子代理继承协议已文档化。
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
核心开发者 = 角色权限模块.核心开发者
项目开发者 = 角色权限模块.项目开发者
平台构建开发者 = 角色权限模块.平台构建开发者
平台维护者 = 角色权限模块.平台维护者
调用者 = 角色权限模块.调用者
发布者 = 角色权限模块.发布者
支持库开发者 = 角色权限模块.支持库开发者
模块开发者 = 角色权限模块.模块开发者
可用工具 = 角色权限模块.可用工具
允许测试范围 = 角色权限模块.允许测试范围
校验工具权限 = 角色权限模块.校验工具权限
校验修改路径 = 角色权限模块.校验修改路径
校验验证命令 = 角色权限模块.校验验证命令
代码地图范围 = 角色权限模块.代码地图范围
越权拒绝 = 角色权限模块.越权拒绝

四角色 = [平台维护者, 核心开发者, 项目开发者, 平台构建开发者]
基础工具 = {"project_context", "role_profile", "capability_search", "capability_read", "mcp_feedback", "feedback_status"}


class 角色门面测试(unittest.TestCase):
    """四角色只暴露必要工具：合法可调、越权拒绝、范围生效。"""

    def setUp(self) -> None:
        self.原角色 = 服务模块.当前角色
        self.原实例 = 服务模块.当前实例
        self.原反馈路径 = 服务模块.反馈路径

    def tearDown(self) -> None:
        服务模块.当前角色 = self.原角色
        服务模块.当前实例 = self.原实例
        服务模块.反馈路径 = self.原反馈路径

    def _切换角色(self, 角色: str) -> None:
        """同步切换默认角色与所属实例（真实 .mcp.json 由环境变量同时初始化）。"""
        服务模块.当前角色 = 角色
        服务模块.当前实例 = 服务模块.角色所属实例(角色)

    def _调用(self, 工具名: str, 参数: dict) -> dict:
        文本 = asyncio.run(服务模块.调用工具(工具名, 参数))
        return json.loads(文本[0].text)

    # ---- 工具白名单 ----

    def test_四角色工具白名单精确(self) -> None:
        期望表 = {
            平台维护者: {"platform_maintenance_guide", "feedback_review"},
            核心开发者: {"core_development_guide"},
            项目开发者: {"project_development_guide"},
            平台构建开发者: {"platform_build_development_guide"},
        }
        越权表 = {
            平台维护者: {"release_guide"},
            核心开发者: {"feedback_review", "platform_maintenance_guide", "release_guide",
                          "project_development_guide", "platform_build_development_guide",
                          "support_library_development_guide", "module_development_guide"},
            项目开发者: {"feedback_review", "core_development_guide", "platform_maintenance_guide",
                          "release_guide", "platform_build_development_guide",
                          "support_library_development_guide", "module_development_guide"},
            平台构建开发者: {"feedback_review", "core_development_guide", "platform_maintenance_guide",
                              "release_guide", "project_development_guide",
                              "support_library_development_guide", "module_development_guide"},
        }
        for 角色 in 四角色:
            工具表 = 可用工具(角色)
            self.assertTrue(基础工具 <= 工具表, f"{角色} 缺少基础工具")
            self.assertTrue(期望表[角色] <= 工具表, f"{角色} 缺少专属工具")
            self.assertEqual(工具表 & 越权表[角色], set(), f"{角色} 暴露了越权工具")

    def test_工具列表按角色白名单过滤(self) -> None:
        for 角色 in 四角色:
            服务模块.当前角色 = 角色
            服务模块.当前实例 = 服务模块.角色所属实例(角色)
            工具名表 = {工具.name for 工具 in asyncio.run(服务模块.工具列表())}
            # 精简注入：工具列表 ⊆ 角色可用工具 ∪ 工具目录，且实例核心工具全部注入
            self.assertTrue(
                工具名表 <= 可用工具(角色) | {"tool_catalog"},
                f"{角色} 工具列表越出角色白名单: {工具名表 - 可用工具(角色)}",
            )
            self.assertIn("tool_catalog", 工具名表, f"{角色} 缺少工具目录")
            self.assertTrue(
                服务模块.实例核心工具(服务模块.当前实例) <= 工具名表,
                f"{角色} 实例核心工具未全部注入",
            )

    def test_调用者只读门面无开发工具(self) -> None:
        self.assertEqual(可用工具(调用者), 基础工具)

    # ---- 合法可调 + 越权拒绝（错误码） ----

    def test_四角色合法工具可调用(self) -> None:
        for 角色 in 四角色:
            服务模块.当前角色 = 角色
            服务模块.当前实例 = 服务模块.角色所属实例(角色)
            档案 = self._调用("role_profile", {})
            self.assertEqual(档案["角色"], 角色)
            self.assertIn("允许目录", 档案)
            搜索 = self._调用("capability_search", {"keyword": "能力", "limit": 3})
            self.assertIn("能力id", 搜索[0])
            self.assertEqual(校验工具权限(角色, "role_profile"), None)

    def test_四角色越权工具被拒且错误码为权限不足(self) -> None:
        # 实例级越权：工具必须不在该角色所属实例的角色集内（合并后同实例内合法）。
        越权调用表 = {
            平台维护者: "生成模块模板",  # 模块开发者专属，toolkit 无
            核心开发者: "feedback_review",  # 维护者专属，developer 无
            项目开发者: "release_guide",  # 发布者专属，developer 无
            平台构建开发者: "platform_maintenance_guide",  # 维护者专属，developer 无
        }
        for 角色, 越权工具 in 越权调用表.items():
            with self.assertRaises(越权拒绝) as 权限层:
                校验工具权限(角色, 越权工具)
            self.assertEqual(权限层.exception.错误码, "权限不足")
            self.assertIn("无权调用工具", 权限层.exception.消息)
            服务模块.当前角色 = 角色
            服务模块.当前实例 = 服务模块.角色所属实例(角色)
            with self.assertRaises(越权拒绝) as 工具面:
                asyncio.run(服务模块.调用工具(越权工具, {}))
            self.assertEqual(工具面.exception.错误码, "权限不足")

    def test_越权真实阻断非恒真(self) -> None:
        """同一角色：合法放行与越权拒绝成对出现，拒绝不是无差别拦截。"""
        for 角色, 合法工具, 越权工具 in [
            (核心开发者, "core_development_guide", "feedback_review"),
            (项目开发者, "project_development_guide", "release_guide"),
            (平台构建开发者, "platform_build_development_guide", "feedback_review"),
            (平台维护者, "feedback_review", "release_guide"),
        ]:
            self.assertIsNone(校验工具权限(角色, 合法工具))
            with self.assertRaises(越权拒绝):
                校验工具权限(角色, 越权工具)
            self.assertIn(合法工具, 可用工具(角色))
            self.assertNotIn(越权工具, 可用工具(角色))

    def test_指南工具按工具名返回对应角色(self) -> None:
        """合并开发实例下，指南工具按工具名返回对应角色指南（不再固定用默认角色）。"""
        服务模块.当前角色 = 核心开发者
        服务模块.当前实例 = 服务模块.角色所属实例(核心开发者)
        self.assertEqual(self._调用("core_development_guide", {})["角色"], 核心开发者)
        self.assertEqual(self._调用("support_library_development_guide", {})["角色"], 支持库开发者)
        self.assertEqual(self._调用("project_development_guide", {})["角色"], 项目开发者)

    def test_跨实例指南工具被拒(self) -> None:
        """合并开发实例不暴露发布者/维护者专属指南（实例级默认拒绝，错误码为权限不足）。"""
        服务模块.当前角色 = 核心开发者
        服务模块.当前实例 = 服务模块.角色所属实例(核心开发者)
        for 越权工具 in ("release_guide", "platform_maintenance_guide"):
            with self.assertRaises(越权拒绝) as 上下文:
                asyncio.run(服务模块.调用工具(越权工具, {}))
            self.assertEqual(上下文.exception.错误码, "权限不足")

    # ---- 代码地图范围 ----

    def test_四角色代码地图范围互斥(self) -> None:
        self.assertEqual(代码地图范围(核心开发者), ["运行核心", "前端核心", "后端核心", "启动监督器", "测试中心"])
        self.assertEqual(代码地图范围(项目开发者), ["项目适配层", "示例项目", "测试中心/项目适配层"])
        self.assertEqual(代码地图范围(平台构建开发者), ["客户端", "平台控制面/包仓库", "测试中心/客户端", "测试中心/平台控制面"])
        self.assertEqual(代码地图范围(平台维护者), ["平台控制面", "开发工具", "MCP工具箱", "测试中心"])
        self.assertEqual(代码地图范围(调用者), [])

    def test_核心开发者不可见平台控制面源码(self) -> None:
        标记 = chr(96)
        原文 = (
            f"**{标记}运行核心/加载器/加载器.py{标记}** — 加载\n加载内容\n\n"
            f"**{标记}平台控制面/包仓库/制品.py{标记}** — 秘密\n不应出现\n\n"
            f"**{标记}项目适配层/依赖锁.py{标记}** — 锁\n锁内容\n"
        )
        结果 = 服务模块._过滤代码地图输出(原文, 代码地图范围(核心开发者))
        self.assertIn("运行核心/加载器/加载器.py", 结果)
        self.assertIn("加载内容", 结果)
        self.assertNotIn("平台控制面/包仓库/制品.py", 结果)
        self.assertNotIn("不应出现", 结果)
        self.assertNotIn("项目适配层/依赖锁.py", 结果)

    def test_项目开发者不可见运行核心与客户端源码(self) -> None:
        标记 = chr(96)
        原文 = (
            f"**{标记}项目适配层/依赖锁.py{标记}** — 锁\n锁内容\n\n"
            f"**{标记}运行核心/加载器/加载器.py{标记}** — 核心\n不应出现核心\n\n"
            f"**{标记}客户端/构建器.py{标记}** — 构建\n不应出现构建\n"
        )
        结果 = 服务模块._过滤代码地图输出(原文, 代码地图范围(项目开发者))
        self.assertIn("项目适配层/依赖锁.py", 结果)
        self.assertIn("锁内容", 结果)
        self.assertNotIn("运行核心/加载器/加载器.py", 结果)
        self.assertNotIn("不应出现核心", 结果)
        self.assertNotIn("客户端/构建器.py", 结果)
        self.assertNotIn("不应出现构建", 结果)

    def test_无源码范围角色探索被拒(self) -> None:
        服务模块.当前角色 = 调用者
        服务模块.当前实例 = 服务模块.角色所属实例(调用者)
        with self.assertRaises(越权拒绝) as 上下文:
            asyncio.run(服务模块.调用工具("codegraph_explore", {"query": "加载器"}))
        self.assertEqual(上下文.exception.错误码, "权限不足")

    # ---- 修改路径越权 ----

    def test_修改路径按角色允许目录校验(self) -> None:
        self.assertIsNone(校验修改路径(核心开发者, ["运行核心/加载器/加载器.py"]))
        self.assertIsNone(校验修改路径(项目开发者, ["项目适配层/依赖锁.py"]))
        self.assertIsNone(校验修改路径(平台构建开发者, ["客户端/构建器.py", "平台控制面/包仓库/制品.py"]))
        self.assertIsNone(校验修改路径(平台维护者, ["MCP工具箱/项目服务.py", "开发工具/发布门禁"]))

    def test_越权修改路径被拒且错误码为角色越权(self) -> None:
        for 角色, 越权路径 in [
            (核心开发者, ["平台控制面/包仓库/制品.py"]),
            (项目开发者, ["运行核心/加载器/加载器.py"]),
            (平台构建开发者, ["项目适配层/依赖锁.py"]),
            (平台维护者, ["运行核心/加载器/加载器.py"]),
        ]:
            with self.assertRaises(越权拒绝) as 上下文:
                校验修改路径(角色, 越权路径)
            self.assertEqual(上下文.exception.错误码, "角色越权")
            self.assertIn("无权访问修改路径", 上下文.exception.消息)

    def test_规划工具面拒绝越权修改路径(self) -> None:
        # 核心开发者已并入 developer 实例：平台控制面/包仓库 属平台构建开发者目录，
        # 真正越权的是发布者专属目录（发布管理）。
        服务模块.当前角色 = 核心开发者
        服务模块.当前实例 = 服务模块.角色所属实例(核心开发者)
        with self.assertRaises(越权拒绝) as 上下文:
            asyncio.run(服务模块.调用工具(
                "verification_plan", {"modified_paths": ["平台控制面/发布管理/发布.py"]},
            ))
        self.assertEqual(上下文.exception.错误码, "角色越权")
        计划 = self._调用("verification_plan", {"modified_paths": ["运行核心/加载器/加载器.py"]})
        self.assertIn("受影响测试目录", 计划)

    # ---- 验证命令测试范围 ----

    def test_验证命令按角色测试范围放行与拒绝(self) -> None:
        # 项目开发者：只允许 测试中心/项目适配层
        校验验证命令(项目开发者, ["python3.14", "测试中心/运行测试.py",
                                  "--测试文件", "测试中心/项目适配层/测试_锁.py", "--并行数", "0"])
        with self.assertRaises(越权拒绝) as 上下文:
            校验验证命令(项目开发者, ["python3.14", "测试中心/运行测试.py",
                                    "--测试文件", "测试中心/支持库/测试_x.py"])
        self.assertEqual(上下文.exception.错误码, "角色越权")
        # 平台构建开发者：只允许 测试中心/客户端 与 测试中心/平台控制面
        校验验证命令(平台构建开发者, ["python3.14", "测试中心/运行测试.py",
                                    "--测试文件", "测试中心/客户端/测试_y.py"])
        with self.assertRaises(越权拒绝):
            校验验证命令(平台构建开发者, ["python3.14", "测试中心/运行测试.py",
                                      "--测试文件", "测试中心/项目适配层/测试_z.py"])
        # 核心开发者：测试中心 整体
        校验验证命令(核心开发者, ["python3.14", "测试中心/运行测试.py",
                                "--测试文件", "测试中心/支持库/测试_x.py"])
        # 调用者与发布者：无测试入口
        self.assertEqual(允许测试范围(调用者), [])
        self.assertEqual(允许测试范围(发布者), [])
        with self.assertRaises(越权拒绝) as 调用者拒绝:
            校验验证命令(调用者, ["python3.14", "测试中心/运行测试.py"])
        self.assertEqual(调用者拒绝.exception.错误码, "权限不足")

    # ---- 单一权威 ----

    def test_单一权威无第二套工具逻辑(self) -> None:
        配置 = json.loads((服务模块.项目根目录 / ".mcp.json").read_text(encoding="utf-8"))
        服务文件表 = {项["args"][0] for 项 in 配置["mcpServers"].values()}
        self.assertEqual(服务文件表, {"MCP工具箱/项目服务.py"})
        # 3 个实例共用同一服务文件，工具列表按实例角色集精简注入
        self.assertEqual(set(配置["mcpServers"]), {
            "system_engineering_toolkit", "system_engineering_developer", "system_engineering_caller",
        })
        for 角色 in 四角色:
            服务模块.当前角色 = 角色
            服务模块.当前实例 = 服务模块.角色所属实例(角色)
            工具名表 = {工具.name for 工具 in asyncio.run(服务模块.工具列表())}
            self.assertTrue(
                工具名表 <= 可用工具(角色) | {"tool_catalog"},
                f"{角色} 注入越出角色白名单: {工具名表 - 可用工具(角色)}",
            )
            self.assertIn("tool_catalog", 工具名表)

    # ---- 子代理继承 ----

    def test_子代理继承协议文档化且要素齐全(self) -> None:
        文档路径 = 服务模块.项目根目录 / "开发文档" / "项目记忆" / "分层MCP门面与子代理继承协议.md"
        self.assertTrue(文档路径.is_file(), "子代理继承协议文档缺失")
        文本 = 文档路径.read_text(encoding="utf-8")
        for 要素 in ["project_context", "角色门面", "子代理", "递归继承", "mcp_feedback",
                      "反馈", "feedback_review", "开工id", "verify_and_record"]:
            self.assertIn(要素, 文本, f"协议文档缺少要素: {要素}")

    def test_开工上下文携带角色门面与开工id(self) -> None:
        上下文 = 服务模块._开工上下文("角色门面测试", 1)
        self.assertEqual(上下文["项目"]["MCP实例"], "system_engineering_toolkit")
        self.assertEqual(上下文["项目"]["角色门面"], 服务模块.当前角色)
        self.assertGreater(len(上下文["项目"]["开工id"]), 0)


if __name__ == "__main__":
    unittest.main()
