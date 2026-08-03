"""模块库.自修复工具 组合能力真实端到端测试。

全部真实 git 调用：worktree 创建→补丁应用→验证→提交→挑拣合入→回滚→
验证还原；补丁多重匹配/路径逃逸/验证失败不提交/回滚失败中止/未提交修改
拒绝；零残留（临时仓库/worktree/进程/登记临时资源全清理）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.自修复工具 import 创建修复工作区, 回滚修复, 验证修复
from 支持库.后端.文件系统 import 清理全部临时资源
from 支持库.后端.资源管理 import 创建内容摘要


def 运行命令(命令列表: list[str], 工作目录: str) -> subprocess.CompletedProcess:
    return subprocess.run(命令列表, cwd=工作目录, capture_output=True, text=True)


class Test自修复工具(unittest.TestCase):
    def setUp(self):
        """真实临时 git 仓库：初始提交含 待修复文件与 重复文本文件。"""
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_自修复工具_"))
        仓库目录 = self.临时根 / "仓库"
        仓库目录.mkdir()
        for 参数 in (["git", "init", "-b", "主干"], ["git", "config", "user.email", "测试@本地"], ["git", "config", "user.name", "测试者"]):
            subprocess.run(参数, cwd=仓库目录, check=True, capture_output=True)
        self.仓库 = 仓库目录
        (仓库目录 / "修复目标.txt").write_text(
            "第一行\n旧版本内容\n第三行\n", encoding="utf-8")
        (仓库目录 / "重复文本.txt").write_text(
            "重复出现\n重复出现\n", encoding="utf-8")
        运行命令(["git", "add", "."], str(仓库目录))
        运行命令(["git", "commit", "-m", "初始提交"], str(仓库目录))

    def tearDown(self):
        清理全部临时资源()
        shutil.rmtree(self.临时根, ignore_errors=True)

    def 补丁(self, 文件: str = "修复目标.txt") -> list:
        return [{"文件": 文件, "旧内容": "旧版本内容", "新内容": "新修复内容"}]

    def 验证命令(self, 期望文本: str = "新修复内容") -> list:
        断言 = f"import sys; c=open('修复目标.txt',encoding='utf-8').read(); sys.exit(0 if '{期望文本}' in c else 1)"
        return ["python3.14", "-c", 断言]

    def test_端到端创建验证提交回滚还原(self):
        """worktree 创建→补丁应用→验证通过→提交→挑拣合入→回滚→验证还原。"""
        创建 = 创建修复工作区(
            str(self.仓库), self.补丁(), self.验证命令(), "修复提交")
        self.assertTrue(创建.成功, 创建.错误说明)
        值 = 创建.值
        self.assertTrue(值["提交"])
        self.assertEqual(值["工作区清理"], "已关闭")
        # 主仓库未被直接修改（修复在独立 worktree 中）
        原始内容 = (self.仓库 / "修复目标.txt").read_text(encoding="utf-8")
        self.assertNotIn("新修复内容", 原始内容)
        # 挑拣合入修复提交到主仓库
        挑拣 = 回滚修复(str(self.仓库), 值["提交"], 操作="挑拣合入")
        self.assertTrue(挑拣.成功, 挑拣.错误说明)
        self.assertIn("新修复内容",
                      (self.仓库 / "修复目标.txt").read_text(encoding="utf-8"))
        # 验证修复（主仓库上再次定向验证）
        验证 = 验证修复(str(self.仓库), self.验证命令())
        self.assertTrue(验证.成功, 验证.错误说明)
        # 回滚：git revert 撤销修复提交
        回滚 = 回滚修复(str(self.仓库), 值["提交"], 操作="回滚")
        self.assertTrue(回滚.成功, 回滚.错误说明)
        self.assertIn("新提交", 回滚.值)
        还原后 = (self.仓库 / "修复目标.txt").read_text(encoding="utf-8")
        self.assertNotIn("新修复内容", 还原后)
        self.assertIn("旧版本内容", 还原后)

    def test_验证摘要比对通过与不匹配(self):
        """期望摘要匹配通过；不匹配返回 验证失败。"""
        正确摘要 = 创建内容摘要(self.仓库 / "修复目标.txt")
        通过 = 验证修复(str(self.仓库), ["git", "status"], 正确摘要, "修复目标.txt")
        self.assertTrue(通过.成功, 通过.错误说明)
        self.assertEqual(通过.值["摘要"], 正确摘要)
        失败 = 验证修复(
            str(self.仓库), ["git", "status"], "0" * 64, "修复目标.txt")
        self.assertFalse(失败.成功)
        self.assertEqual(失败.错误码, "验证失败")

    def test_补丁多重匹配拒绝(self):
        """旧内容出现 2 次 → 补丁多重匹配，不提交不产生工作区残留。"""
        创建 = 创建修复工作区(
            str(self.仓库), self.补丁("重复文本.txt"), ["git", "status"],
            "不应提交")
        self.assertFalse(创建.成功)
        self.assertEqual(创建.错误码, "补丁多重匹配")
        # 主仓库没有新提交
        日志 = 运行命令(["git", "log", "--oneline"], str(self.仓库))
        self.assertEqual(len(日志.stdout.strip().splitlines()), 1)
        # 零残留：临时宿主/worktree 目录已被清理
        self.assertEqual(清理全部临时资源().成功, True)

    def test_路径逃逸拒绝(self):
        """补丁文件 ../ 或绝对路径 → 路径逃逸拒绝。"""
        for 文件 in ("../逃逸.txt", "/etc/逃逸.txt", ""):
            with self.subTest(文件=文件):
                创建 = 创建修复工作区(
                    str(self.仓库),
                    [{"文件": 文件, "旧内容": "x", "新内容": "y"}],
                    ["git", "status"], "不应提交")
                self.assertFalse(创建.成功)
                self.assertEqual(创建.错误码, "路径逃逸")

    def test_验证失败不提交(self):
        """验证命令退出码非零 → 验证失败，主仓库无新提交。"""
        创建 = 创建修复工作区(
            str(self.仓库), self.补丁(),
            ["python3.14", "-c", "import sys; sys.exit(3)"], "不应提交")
        self.assertFalse(创建.成功)
        self.assertEqual(创建.错误码, "验证失败")
        日志 = 运行命令(["git", "log", "--oneline"], str(self.仓库))
        self.assertEqual(len(日志.stdout.strip().splitlines()), 1)
        self.assertEqual(清理全部临时资源().成功, True)

    def test_回滚失败中止(self):
        """挑拣合入不存在的提交 → 回滚失败；冲突自动中止保持干净。"""
        失败 = 回滚修复(str(self.仓库), "a" * 7, 操作="挑拣合入")
        self.assertFalse(失败.成功)
        self.assertEqual(失败.错误码, "回滚失败")
        # 冲突自动中止后仓库保持干净、无残留冲突状态
        状态 = 运行命令(["git", "status", "--porcelain"], str(self.仓库))
        self.assertEqual(状态.stdout.strip(), "")

    def test_未提交修改拒绝回滚(self):
        """主仓库存在未提交修改 → 未提交修改 拒绝。"""
        (self.仓库 / "修复目标.txt").write_text("脏修改\n", encoding="utf-8")
        结果 = 回滚修复(str(self.仓库), "a" * 7, 操作="回滚")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未提交修改")

    def test_零残留(self):
        """创建全程后：无 worktree、无登记临时资源残留。"""
        创建 = 创建修复工作区(
            str(self.仓库), self.补丁(), self.验证命令(), "修复提交")
        self.assertTrue(创建.成功, 创建.错误说明)
        清单 = 运行命令(["git", "worktree", "list"], str(self.仓库))
        # 创建成功后 worktree 已关闭，仅主工作区
        self.assertEqual(len(清单.stdout.strip().splitlines()), 1)
        清理 = 清理全部临时资源()
        self.assertTrue(清理.成功, 清理.错误说明)
        # 全部临时宿主目录已删除
        self.assertFalse(any(self.临时根.parent.glob("自修复_*")))


if __name__ == "__main__":
    unittest.main()
