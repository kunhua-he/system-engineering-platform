"""临时上下文的隔离、过期和清理测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from MCP工具箱.临时上下文 import 清理临时上下文, 读取临时上下文, 写入临时上下文, 核对修改范围


class 临时上下文测试(unittest.TestCase):

    def test_标识路径穿越和碰撞拒绝(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录)
            with self.assertRaises(ValueError):
                写入临时上下文(目录, 开工id="../逃逸", 父任务="甲", 角色="开发者",
                              允许目录=[], 记忆查询=[], 事实=[], 验证计划=[])
            with self.assertRaises(ValueError):
                写入临时上下文(目录, 开工id="a/b", 父任务="甲", 角色="开发者",
                              允许目录=[], 记忆查询=[], 事实=[], 验证计划=[])

    def test_范围核对拒绝绝对路径与父目录逃逸(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录)
            写入临时上下文(目录, 开工id="scope-a1", 父任务="甲", 角色="开发者",
                          允许目录=["MCP工具箱"], 记忆查询=[], 事实=[], 验证计划=[])
            self.assertFalse(核对修改范围(目录, "scope-a1", ["MCP工具箱/../运行核心/a.py"])["成功"])
            self.assertFalse(核对修改范围(目录, "scope-a1", ["/Users/evil.py"])["成功"])
    def test_写入读取只返回定向上下文(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录)
            写入临时上下文(目录, 开工id="work-a", 父任务="审计", 角色="模块开发者",
                          允许目录=["模块库"], 记忆查询=["摘要"], 事实=["只读"],
                          验证计划=[["python3.14", "测试.py"]])
            结果 = 读取临时上下文(目录, "work-a")
            self.assertTrue(结果["成功"])
            self.assertEqual(结果["允许目录"], ["模块库"])
            self.assertFalse((目录 / "work-a.md").exists())

    def test_不同开工id隔离(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录)
            写入临时上下文(目录, 开工id="work-a", 父任务="甲", 角色="开发者",
                          允许目录=[], 记忆查询=[], 事实=[], 验证计划=[])
            结果 = 读取临时上下文(目录, "work-b")
            self.assertFalse(结果["成功"])
            self.assertEqual(结果["错误码"], "TEMPORARY_CONTEXT_NOT_FOUND")

    def test_收工清理幂等(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录)
            写入临时上下文(目录, 开工id="work-a", 父任务="甲", 角色="开发者",
                          允许目录=[], 记忆查询=[], 事实=[], 验证计划=[])
            self.assertTrue(清理临时上下文(目录, "work-a")["已清理"])
            self.assertFalse(清理临时上下文(目录, "work-a")["已清理"])


if __name__ == "__main__":
    unittest.main()
