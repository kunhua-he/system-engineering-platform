"""系统工程平台专属 MCP 的项目隔离与证据测试。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
from MCP工具箱 import 项目服务 as 服务模块


class 项目服务测试(unittest.TestCase):
    def test_MCP工具箱必须从项目根按包导入(self) -> None:
        环境 = os.environ.copy()
        环境.pop("PYTHONPATH", None)
        结果 = subprocess.run(
            [sys.executable, "-c", "import MCP工具箱.项目服务, MCP工具箱.能力网关"],
            cwd=系统根, env=环境, capture_output=True, text=True, check=False,
        )
        self.assertEqual(结果.returncode, 0, 结果.stderr)

    def test_启动脚本只使用包入口(self) -> None:
        for 文件名, 入口 in (
            ("启动HTTP服务.sh", "-m MCP工具箱.项目服务"),
            ("启动能力网关.sh", "-m MCP工具箱.能力网关"),
        ):
            内容 = (系统根 / "MCP工具箱" / 文件名).read_text(encoding="utf-8")
            self.assertIn(入口, 内容)
            self.assertNotIn("PYTHONPATH=", 内容)
            self.assertNotIn("MCP工具箱/项目服务.py", 内容)
            self.assertNotIn("MCP工具箱/能力网关.py", 内容)

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
        self.assertEqual(计划["建议命令"][0][:2], ["python3.14", "-m"])
        self.assertTrue(计划["建议命令"][0][2].startswith("测试中心.运行核心.测试_"))

    def test_阶段收口只验证指定编译制品(self) -> None:
        制品 = "工程缓存/编译制品/候选1"
        计划 = 服务模块._验证计划(["运行核心/能力调用"], "阶段收口", 制品=制品)
        self.assertFalse(计划["是否需要全量"])
        self.assertEqual(计划["建议命令"], [[
            "python3.14", "-m", "开发工具.HTML验证.验证器",
            "--制品", 制品, "--并发", "32",
        ]])

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

    def test_全量工具都有中文名且可中文调用(self) -> None:
        from MCP工具箱.工具名映射 import 中文名到协议名, 协议名到中文名
        工具表 = {工具.name for 工具 in asyncio.run(服务模块.工具列表())}
        缺失 = sorted(名称 for 名称 in 工具表 if 名称 not in 协议名到中文名)
        self.assertEqual(缺失, [], f"以下工具缺中文名映射: {缺失}")
        多余 = sorted(协议名 for 协议名 in 协议名到中文名 if 协议名 not in 工具表)
        self.assertEqual(多余, [], f"映射表存在已下线工具: {多余}")
        # 中文名必须唯一且不等于协议名（否则门面没有意义）
        中文名表 = list(中文名到协议名)
        self.assertEqual(len(中文名表), len(set(中文名表)), "中文名出现重复")
        for 中文名, 协议名 in 中文名到协议名.items():
            self.assertNotEqual(中文名, 协议名)
            self.assertEqual(协议名到中文名[协议名], 中文名)

    def test_工具目录展示中文名(self) -> None:
        目录 = 服务模块._工具目录()
        条目 = {项["协议名"]: 项 for 项 in 目录["工具清单"]}
        self.assertEqual(目录["条目数"], len(条目))
        self.assertEqual(条目["claim_capability"]["中文名"], "登记能力占用")
        self.assertEqual(条目["tool_catalog"]["中文名"], "工具目录")
        for 项 in 目录["工具清单"]:
            self.assertNotEqual(项["中文名"], 项["协议名"], f"{项['协议名']} 未展示中文名")

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
                    角色=服务模块.网关角色名, 允许目录=["MCP工具箱"], 记忆查询=[],
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
                目录, 开工id="scope-a1", 父任务="父任务", 角色=服务模块.网关角色名,
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
                    角色=服务模块.网关角色名, 允许目录=["MCP工具箱"], 记忆查询=[],
                    事实=[], 验证计划=[], 有效秒数=60,
                )
                服务模块.写入反馈(
                    服务模块.反馈路径, 开工id="child-evidence", 任务="子任务",
                    角色=服务模块.网关角色名, 总结="可用", 不满意="无", 多余="无",
                    缺失="无", 升级建议="无",
                )
                结果 = asyncio.run(服务模块.调用工具("verify_and_record", {
                    "work_id": "child-evidence", "name": "子任务验证",
                    "command": ["python3.14", "-m", "测试中心.公共契约.测试_数值类型契约"],
                }))
                self.assertIn('"开工id": "child-evidence"', 结果[0].text)
                self.assertIn('"开工id": "child-evidence"', 服务模块.证据路径.read_text(encoding="utf-8"))
            finally:
                服务模块.反馈路径 = 原反馈
                服务模块.证据路径 = 原证据
                服务模块.临时上下文目录 = 原上下文

    def test_CodeGraph输出不泄漏范围外源码(self) -> None:
        标记 = chr(96)
        原文 = (
            f"**{标记}模块库/示例模块.py{标记}** — 示例模块\n\n模块内容\n\n"
            f"**{标记}支持库/秘密.py{标记}** — 秘密\n\n不应出现\n"
        )
        结果 = 服务模块._过滤代码地图输出(原文, ["模块库"])
        self.assertIn("模块库/示例模块.py", 结果)
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
                    任务="反馈门禁测试", 角色=服务模块.网关角色名,
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
