"""系统工程平台专属 MCP 的项目隔离与证据测试。"""

from __future__ import annotations

import importlib.util
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

服务路径 = Path(__file__).resolve().parents[2] / "MCP工具箱" / "项目服务.py"
sys.path.insert(0, str(服务路径.parent))
规格 = importlib.util.spec_from_file_location("系统工程平台项目服务", 服务路径)
assert 规格 and 规格.loader
服务模块 = importlib.util.module_from_spec(规格)
规格.loader.exec_module(服务模块)


class 项目服务测试(unittest.TestCase):
    def test_项目根固定为系统工程平台(self) -> None:
        self.assertEqual(服务模块.项目根目录, Path(__file__).resolve().parents[2])

    def test_上下文声明独立MCP实例(self) -> None:
        上下文 = 服务模块._开工上下文("测试任务", 3)
        self.assertEqual(上下文["项目"]["名称"], "系统工程平台")
        self.assertEqual(上下文["项目"]["MCP实例"], "system_engineering_toolkit")
        self.assertLessEqual(0, 上下文["证据可信度"]["分数"])
        self.assertGreaterEqual(100, 上下文["证据可信度"]["分数"])

    def test_失败验证不写成功证据(self) -> None:
        原路径 = 服务模块.证据路径
        with tempfile.TemporaryDirectory() as 临时目录:
            服务模块.证据路径 = Path(临时目录) / "验证历史.jsonl"
            try:
                记录 = 服务模块._运行验证(
                    "必然失败", ["python3.14", "-m", "py_compile", "不存在.py"], 10
                )
                self.assertNotEqual(记录["退出码"], 0)
                self.assertFalse(服务模块.证据路径.exists())
            finally:
                服务模块.证据路径 = 原路径

    def test_调用者只能使用只读工具(self) -> None:
        from 角色权限 import 调用者, 可用工具, 校验工具权限, 校验验证命令

        self.assertIn("capability_search", 可用工具(调用者))
        self.assertNotIn("codegraph_explore", 可用工具(调用者))
        with self.assertRaises(PermissionError):
            校验工具权限(调用者, "codegraph_explore")
        with self.assertRaises(PermissionError):
            校验验证命令(调用者, ["python3.14", "-c", "print(1)"])

    def test_角色代码地图范围相互隔离(self) -> None:
        from 角色权限 import 支持库开发者, 模块开发者, 代码地图范围, 可用工具

        self.assertIn("支持库", 代码地图范围(支持库开发者))
        self.assertNotIn("模块库", 代码地图范围(支持库开发者))
        self.assertEqual(代码地图范围(模块开发者)[0], "模块库")
        self.assertIn("module_development_guide", 可用工具(模块开发者))
        self.assertNotIn("support_library_development_guide", 可用工具(模块开发者))

    def test_公开能力搜索不加载实现(self) -> None:
        结果 = 服务模块.搜索公开能力(服务模块.项目根目录, "解析PDF", 10)
        self.assertGreater(len(结果), 0)
        for 能力 in 结果:
            self.assertIn("能力id", 能力)
            self.assertIn("包id", 能力)
            self.assertIn("参数", 能力)

    def test_验证计划按修改范围生成定向命令(self) -> None:
        计划 = 服务模块._验证计划(
            ["运行核心/运行环境管理器/强制校验.py"], "工作包"
        )
        self.assertEqual(计划["受影响测试目录"], ["测试中心/运行核心"])
        self.assertFalse(计划["是否需要全量"])
        self.assertIn("--测试文件", 计划["建议命令"][0])

    def test_阶段收口验证计划才建议全量(self) -> None:
        计划 = 服务模块._验证计划(["运行核心/能力调用"], "阶段收口")
        self.assertTrue(计划["是否需要全量"])
        self.assertEqual(计划["建议命令"], [["python3.14", "测试中心/运行测试.py"]])

    def test_统一开发入口一次返回上下文和计划(self) -> None:
        结果 = 服务模块._统一开发入口(
            "统一入口测试", ["运行核心/运行环境管理器/强制校验.py"], "工作包", 1
        )
        self.assertIn("开工上下文", 结果)
        self.assertIn("验证计划", 结果)
        self.assertEqual(结果["验证计划"]["受影响测试目录"], ["测试中心/运行核心"])
        self.assertIn("工作区快照", 结果["开工上下文"])
        self.assertIn("当前分支", 结果["开工上下文"]["工作区快照"])

    def test_工作区工具暴露提交与合并(self) -> None:
        工具表 = {工具.name: 工具 for 工具 in asyncio.run(服务模块.工具列表())}
        操作表 = 工具表["workspace"].inputSchema["properties"]["operation"]["enum"]
        self.assertIn("提交", 操作表)
        self.assertIn("合并", 操作表)
        self.assertIn("test_resource", 工具表)

    def test_普通开发角色不能合并分支(self) -> None:
        原角色 = 服务模块.当前角色
        服务模块.当前角色 = "模块开发者"
        try:
            with self.assertRaises(PermissionError):
                asyncio.run(服务模块.调用工具("workspace", {
                    "operation": "合并", "path": str(服务模块.项目根目录),
                    "target_branch": "main", "source_branch": "codex/test",
                }))
        finally:
            服务模块.当前角色 = 原角色

    def test_子任务反馈必须绑定有效临时上下文(self) -> None:
        原反馈 = 服务模块.反馈路径
        原上下文 = 服务模块.临时上下文目录
        with tempfile.TemporaryDirectory() as 临时目录:
            服务模块.反馈路径 = Path(临时目录) / "反馈.jsonl"
            服务模块.临时上下文目录 = Path(临时目录) / "上下文"
            参数 = {
                "work_id": "child-a1", "summary": "可用", "dissatisfaction": "无",
                "redundant": "无", "missing": "无", "upgrade_suggestion": "无",
            }
            try:
                with self.assertRaises(PermissionError):
                    asyncio.run(服务模块.调用工具("mcp_feedback", 参数))
                服务模块.写入临时上下文(
                    服务模块.临时上下文目录, 开工id="child-a1", 父任务="父任务",
                    角色=服务模块.当前角色, 允许目录=["MCP工具箱"], 记忆查询=[],
                    事实=[], 验证计划=[], 有效秒数=60,
                )
                结果 = asyncio.run(服务模块.调用工具("mcp_feedback", 参数))
                self.assertIn("child-a1", 结果[0].text)
            finally:
                服务模块.反馈路径 = 原反馈
                服务模块.临时上下文目录 = 原上下文

    def test_临时上下文核对修改范围(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录)
            服务模块.写入临时上下文(
                目录, 开工id="scope-a1", 父任务="父任务", 角色=服务模块.当前角色,
                允许目录=["./MCP工具箱"], 记忆查询=[], 事实=[], 验证计划=[], 有效秒数=60,
            )
            通过 = 服务模块.核对修改范围(目录, "scope-a1", ["MCP工具箱/项目服务.py"])
            越界 = 服务模块.核对修改范围(目录, "scope-a1", ["运行核心/越界.py"])
            self.assertTrue(通过["成功"])
            self.assertFalse(越界["成功"])
            self.assertEqual(越界["错误码"], "TEMPORARY_CONTEXT_SCOPE_MISMATCH")

    def test_子任务验证证据按真实开工id记录(self) -> None:
        原反馈 = 服务模块.反馈路径
        原证据 = 服务模块.证据路径
        原上下文 = 服务模块.临时上下文目录
        with tempfile.TemporaryDirectory() as 临时目录:
            根 = Path(临时目录)
            服务模块.反馈路径 = 根 / "反馈.jsonl"
            服务模块.证据路径 = 根 / "证据.jsonl"
            服务模块.临时上下文目录 = 根 / "上下文"
            try:
                服务模块.写入临时上下文(
                    服务模块.临时上下文目录, 开工id="child-evidence", 父任务="父任务",
                    角色=服务模块.当前角色, 允许目录=["MCP工具箱"], 记忆查询=[],
                    事实=[], 验证计划=[], 有效秒数=60,
                )
                服务模块.写入反馈(
                    服务模块.反馈路径, 开工id="child-evidence", 任务="子任务",
                    角色=服务模块.当前角色, 总结="可用", 不满意="无", 多余="无",
                    缺失="无", 升级建议="无",
                )
                结果 = asyncio.run(服务模块.调用工具("verify_and_record", {
                    "work_id": "child-evidence", "name": "子任务验证",
                    "command": ["python3.14", "-m", "pytest",
                                "测试中心/模块库/测试_OCR.py", "-q", "--timeout=600"],
                }))
                self.assertIn('"开工id": "child-evidence"', 结果[0].text)
                self.assertIn('"开工id": "child-evidence"', 服务模块.证据路径.read_text(encoding="utf-8"))
            finally:
                服务模块.反馈路径 = 原反馈
                服务模块.证据路径 = 原证据
                服务模块.临时上下文目录 = 原上下文

    def test_调用者工具列表和直接调用双重拒绝(self) -> None:
        原角色 = 服务模块.当前角色
        服务模块.当前角色 = "调用者"
        try:
            工具名表 = {工具.name for 工具 in asyncio.run(服务模块.工具列表())}
            self.assertIn("capability_search", 工具名表)
            self.assertNotIn("codegraph_explore", 工具名表)
            with self.assertRaises(PermissionError):
                asyncio.run(服务模块.调用工具("codegraph_explore", {"query": "实现"}))
        finally:
            服务模块.当前角色 = 原角色

    def test_MCP配置角色齐全(self) -> None:
        配置 = json.loads((服务模块.项目根目录 / ".mcp.json").read_text(encoding="utf-8"))
        服务器表 = 配置["mcpServers"]
        角色表 = {
            项["env"]["SYSTEM_ENGINEERING_MCP_ROLE"]
            for 项 in 服务器表.values()
        }
        self.assertEqual(
            角色表,
            {"调用者", "支持库开发者", "模块开发者", "核心开发者", "项目开发者", "平台构建开发者", "平台维护者", "发布者"},
        )

    def test_CodeGraph输出不泄漏范围外源码(self) -> None:
        标记 = chr(96)
        原文 = (
            f"**{标记}模块库/甲.py{标记}** — 甲\n\n模块内容\n\n"
            f"**{标记}支持库/秘密.py{标记}** — 秘密\n\n不应出现\n"
        )
        结果 = 服务模块._过滤代码地图输出(原文, ["模块库"])
        self.assertIn("模块库/甲.py", 结果)
        self.assertIn("模块内容", 结果)
        self.assertNotIn("支持库/秘密.py", 结果)
        self.assertNotIn("不应出现", 结果)

    def test_反馈是成功验证入账前置门禁(self) -> None:
        原路径 = 服务模块.反馈路径
        with tempfile.TemporaryDirectory() as 临时目录:
            服务模块.反馈路径 = Path(临时目录) / "反馈.jsonl"
            try:
                上下文 = 服务模块._开工上下文("反馈门禁测试", 1)
                self.assertFalse(
                    服务模块.查询反馈状态(
                        服务模块.反馈路径, 上下文["项目"]["开工id"],
                    )["已反馈"]
                )
                with self.assertRaises(PermissionError):
                    asyncio.run(服务模块.调用工具(
                        "verify_and_record",
                        {"name": "未反馈", "command": ["git", "diff", "--check"]},
                    ))
                服务模块.写入反馈(
                    服务模块.反馈路径, 开工id=上下文["项目"]["开工id"],
                    任务="反馈门禁测试", 角色=服务模块.当前角色,
                    总结="可用", 不满意="无",
                    多余="无", 缺失="无", 升级建议="增加批量审阅",
                )
                self.assertTrue(
                    服务模块.查询反馈状态(
                        服务模块.反馈路径, 上下文["项目"]["开工id"],
                    )["已反馈"]
                )
                审阅 = 服务模块.读取反馈列表(
                    服务模块.反馈路径, 开工id=上下文["项目"]["开工id"],
                )
                self.assertEqual(审阅["数量"], 1)
                self.assertEqual(len(审阅["升级候选"]), 1)
                self.assertEqual(审阅["升级候选"][0]["类别"], "升级建议")
            finally:
                服务模块.反馈路径 = 原路径


if __name__ == "__main__":
    unittest.main()
