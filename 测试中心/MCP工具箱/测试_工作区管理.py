"""工作区管理（worktree 合并流程）真实测试：临时目录自建 git 仓库，禁止桩。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MCP工具箱.工作区管理 import (
    创建工作区,
    查询工作区,
    关闭工作区,
    合并分支,
    工作区提交,
)


def _运行(根目录: Path, 命令: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(命令, cwd=根目录, capture_output=True, text=True, check=False)


class 工作区管理测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        根 = Path(self._临时.name)
        self.项目根 = 根 / "主仓库"
        self.工作区根 = self.项目根 / "工程缓存" / "任务工作区"
        self.项目根.mkdir()
        初始化 = _运行(self.项目根, ["git", "init", "-b", "main"])
        self.assertEqual(初始化.returncode, 0, 初始化.stderr)
        _运行(self.项目根, ["git", "config", "user.name", "测试用户"])
        _运行(self.项目根, ["git", "config", "user.email", "测试@示例.本地"])
        (self.项目根 / "初始.txt").write_text("初始内容\n", encoding="utf-8")
        _运行(self.项目根, ["git", "add", "."])
        提交 = _运行(self.项目根, ["git", "commit", "-m", "初始提交"])
        self.assertEqual(提交.returncode, 0, 提交.stderr)

    def tearDown(self) -> None:
        self._临时.cleanup()

    def test_创建工作区真实成功(self) -> None:
        结果 = 创建工作区(self.项目根, self.工作区根, 任务id="任务1")
        self.assertTrue(结果["成功"], 结果)
        目标 = Path(结果["路径"])
        self.assertTrue(目标.is_dir())
        self.assertTrue((目标 / "初始.txt").exists())
        列表 = 查询工作区(self.项目根, self.工作区根)
        self.assertTrue(列表["成功"])
        self.assertIn(str(目标), 列表["列表"])
        分支 = _运行(self.项目根, ["git", "branch", "--list", "codex/任务-任务1"])
        self.assertIn("codex/任务-任务1", 分支.stdout)

    def test_脏改动保护拒绝关闭且强制可关闭(self) -> None:
        创建 = 创建工作区(self.项目根, self.工作区根, 任务id="任务2")
        self.assertTrue(创建["成功"], 创建)
        目标 = Path(创建["路径"])
        (目标 / "未提交.txt").write_text("脏改动\n", encoding="utf-8")
        拒绝 = 关闭工作区(self.项目根, str(目标), 强制=False)
        self.assertFalse(拒绝["成功"])
        self.assertEqual(拒绝["错误码"], "WORKSPACE_DIRTY")
        self.assertTrue(拒绝["未提交修改"], 拒绝)
        self.assertTrue(any("未提交.txt" in 行 for 行 in 拒绝["未提交修改"]))
        self.assertIn("拒绝关闭", 拒绝["消息"])
        self.assertTrue(目标.exists())
        self.assertTrue((目标 / "未提交.txt").exists())
        强制 = 关闭工作区(self.项目根, str(目标), 强制=True)
        self.assertTrue(强制["成功"], 强制)
        self.assertTrue(强制["已强制"])
        self.assertFalse(目标.exists())

    def test_合并分支成功包含来源文件(self) -> None:
        _运行(self.项目根, ["git", "checkout", "-b", "功能1"])
        (self.项目根 / "功能1.txt").write_text("功能1\n", encoding="utf-8")
        _运行(self.项目根, ["git", "add", "功能1.txt"])
        提交1 = _运行(self.项目根, ["git", "commit", "-m", "功能1提交"])
        self.assertEqual(提交1.returncode, 0, 提交1.stderr)
        _运行(self.项目根, ["git", "checkout", "-b", "功能2", "功能1"])
        (self.项目根 / "功能2.txt").write_text("功能2\n", encoding="utf-8")
        _运行(self.项目根, ["git", "add", "功能2.txt"])
        提交2 = _运行(self.项目根, ["git", "commit", "-m", "功能2提交"])
        self.assertEqual(提交2.returncode, 0, 提交2.stderr)
        _运行(self.项目根, ["git", "checkout", "功能1"])
        结果 = 合并分支(self.项目根, "功能1", "功能2")
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["冲突列表"], [])
        文件列表 = _运行(self.项目根, ["git", "-c", "core.quotePath=false", "ls-tree", "-r", "--name-only", "功能1"])
        self.assertIn("功能2.txt", 文件列表.stdout)

    def test_合并冲突返回失败且冲突列表非空(self) -> None:
        (self.项目根 / "冲突.txt").write_text("基线\n", encoding="utf-8")
        _运行(self.项目根, ["git", "add", "冲突.txt"])
        基线提交 = _运行(self.项目根, ["git", "commit", "-m", "冲突基线"])
        self.assertEqual(基线提交.returncode, 0, 基线提交.stderr)
        _运行(self.项目根, ["git", "checkout", "-b", "功能1"])
        (self.项目根 / "冲突.txt").write_text("功能1修改\n", encoding="utf-8")
        _运行(self.项目根, ["git", "add", "冲突.txt"])
        _运行(self.项目根, ["git", "commit", "-m", "功能1改冲突"])
        _运行(self.项目根, ["git", "checkout", "-b", "功能2", "HEAD~1"])
        (self.项目根 / "冲突.txt").write_text("功能2修改\n", encoding="utf-8")
        _运行(self.项目根, ["git", "add", "冲突.txt"])
        _运行(self.项目根, ["git", "commit", "-m", "功能2改冲突"])
        _运行(self.项目根, ["git", "checkout", "功能1"])
        结果 = 合并分支(self.项目根, "功能1", "功能2")
        self.assertFalse(结果["成功"])
        self.assertTrue(结果["冲突列表"], 结果)
        self.assertIn("冲突.txt", 结果["输出"])

    def test_工作区提交新增文件并产生提交(self) -> None:
        创建 = 创建工作区(self.项目根, self.工作区根, 任务id="任务丙")
        self.assertTrue(创建["成功"], 创建)
        目标 = Path(创建["路径"])
        (目标 / "新文件.txt").write_text("新内容\n", encoding="utf-8")
        结果 = 工作区提交(目标, "工作包提交")
        self.assertTrue(结果["成功"], 结果)
        self.assertIn("工作包提交", 结果["提交摘要"])
        日志 = _运行(目标, ["git", "log", "-1", "--pretty=format:%s"])
        self.assertEqual(日志.stdout.strip(), "工作包提交")
        跟踪 = _运行(目标, ["git", "ls-files", "--error-unmatch", "新文件.txt"])
        self.assertEqual(跟踪.returncode, 0, 跟踪.stderr)

    def test_非法任务标识抛错(self) -> None:
        with self.assertRaises(ValueError):
            创建工作区(self.项目根, self.工作区根, 任务id="任务1!!!")
        with self.assertRaises(ValueError):
            创建工作区(self.项目根, self.工作区根, 任务id="超长" * 40)
        with self.assertRaises(ValueError):
            创建工作区(self.项目根, self.工作区根, 任务id="")

    def test_关闭越界路径拒绝(self) -> None:
        with self.assertRaises(ValueError):
            关闭工作区(self.项目根, str(self.项目根))
        越界 = Path(tempfile.gettempdir()) / "工作区越界旁路-不存在的路径"
        with self.assertRaises(ValueError):
            关闭工作区(self.项目根, str(越界))


if __name__ == "__main__":
    unittest.main()
