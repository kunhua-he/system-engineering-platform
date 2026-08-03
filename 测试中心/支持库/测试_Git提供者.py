"""Git 提供者测试：临时目录自建 git 仓库真实调用（全部真实 git 执行）。

覆盖：检查提供者/创建工作区/查询工作区/提交/回滚/挑拣合入/当前状态/
关闭工作区；参数注入拒绝（分支名/路径/哈希 含 ;|& 换行 等元字符）；
未提交修改关闭拒绝（非强制）；冲突自动中止恢复干净状态；提供者不可用注入；
仓库不存在/路径越界/命令失败；临时仓库与 worktree 全部清理（零残留）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.Git提供者 import (
    检查提供者, 创建工作区, 查询工作区, 关闭工作区,
    提交, 回滚, 挑拣合入, 当前状态,
)


def _运行git(目录: str, *参数: str) -> subprocess.CompletedProcess:
    """测试辅助：真实 git 调用（测试侧允许直接使用 git 做场景搭建）。"""
    return subprocess.run(
        ["git", "-C", 目录, *参数], capture_output=True, text=True, timeout=60)


def _初始化仓库(根: Path, 分支: str = "main") -> Path:
    """真实 git init + 配置 + 首个提交（worktree add 需要已存在 HEAD）。"""
    根.mkdir(parents=True, exist_ok=True)
    _运行git(str(根), "init", "-b", 分支)
    _运行git(str(根), "config", "user.email", "测试@本机")
    _运行git(str(根), "config", "user.name", "测试者")
    (根 / "基线.txt").write_text("基线内容\n", encoding="utf-8")
    _运行git(str(根), "add", "基线.txt")
    _运行git(str(根), "commit", "-m", "基线提交")
    return 根


def _新建工作区(仓库: Path, 工作区: Path, 分支名: str | None = None) -> Path:
    结果 = 创建工作区(str(仓库), str(工作区), 分支名=分支名)
    assert 结果.成功, 结果.错误说明
    return 工作区


class TestGit提供者(unittest.TestCase):
    """Git 提供者真实调用测试。"""

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_Git提供者_"))
        self.仓库 = _初始化仓库(self.临时根 / "仓库")
        self.工作区 = self.临时根 / "工作区"

    def tearDown(self):
        """强制清残留工作区后整体删除，验证零残留。"""
        关闭 = _运行git(str(self.仓库), "worktree", "list", "--porcelain")
        残留 = [行.removeprefix("worktree ").strip()
                for 行 in 关闭.stdout.splitlines() if 行.startswith("worktree ")]
        for 路径 in 残留:
            if Path(路径).resolve() != self.仓库.resolve() and Path(路径).exists():
                _运行git(str(self.仓库), "worktree", "remove", "--force", 路径)
        shutil.rmtree(self.临时根, ignore_errors=True)
        self.assertFalse(self.临时根.exists())

    def test_检查提供者(self):
        结果 = 检查提供者()
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["git"], "可用")
        self.assertIn("git version", 结果.值["版本"])

    def test_参数注入拒绝(self):
        for 分支名 in ["正常;ls", "正常|ls", "正常&ls", "a\nb", "a`b", "a$b", "-开头"]:
            结果 = 创建工作区(str(self.仓库), str(self.临时根 / "注入"), 分支名=分支名)
            self.assertEqual(结果.错误码, "参数不合法", repr(分支名))
        for 哈希 in ["abc;def", "abc def", "abcdefg;", "短哈希"]:
            结果 = 回滚(str(self.仓库), 哈希)
            self.assertEqual(结果.错误码, "参数不合法", repr(哈希))
        for 路径 in ["相对路径/文件", "含 空格/文件", "含;分号/文件", "换\n行/文件"]:
            结果 = 提交(str(self.仓库), [路径], "消息")
            self.assertEqual(结果.错误码, "参数不合法", repr(路径))

    def test_创建工作区与查询工作区(self):
        _新建工作区(self.仓库, self.工作区, 分支名="开发分支")
        self.assertTrue(self.工作区.is_dir())
        查询 = 查询工作区(str(self.仓库))
        self.assertTrue(查询.成功, 查询.错误说明)
        路径列表 = [str(Path(条目["路径"]).resolve()) for 条目 in 查询.值["工作区列表"]]
        self.assertIn(str(self.仓库.resolve()), 路径列表)
        self.assertIn(str(self.工作区.resolve()), 路径列表)
        分支列表 = [条目.get("分支", "") for 条目 in 查询.值["工作区列表"]]
        self.assertIn("开发分支", 分支列表)
        self.assertEqual(当前状态(str(self.工作区)).值["分支"], "开发分支")

    def test_提交与当前状态(self):
        _新建工作区(self.仓库, self.工作区, 分支名="开发分支")
        文件 = self.工作区 / "新增.txt"
        文件.write_text("内容一\n", encoding="utf-8")
        结果 = 提交(str(self.工作区), [str(文件)], "新增文件")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(len(结果.值["提交"]) >= 7)
        状态 = 当前状态(str(self.工作区))
        self.assertTrue(状态.成功, 状态.错误说明)
        self.assertEqual(状态.值["分支"], "开发分支")
        self.assertEqual(状态.值["未提交修改"], [])
        self.assertTrue(状态.值["最近提交"])
        self.assertIn("新增文件", 状态.值["最近提交"][0])

    def test_回滚(self):
        _新建工作区(self.仓库, self.工作区, 分支名="开发分支")
        文件 = self.工作区 / "回滚.txt"
        文件.write_text("第一版\n", encoding="utf-8")
        结果一 = 提交(str(self.工作区), [str(文件)], "第一版")
        self.assertTrue(结果一.成功, 结果一.错误说明)
        文件.write_text("第二版\n", encoding="utf-8")
        结果二 = 提交(str(self.工作区), [str(文件)], "第二版")
        self.assertTrue(结果二.成功, 结果二.错误说明)
        回滚结果 = 回滚(str(self.工作区), 结果二.值["提交"])
        self.assertTrue(回滚结果.成功, 回滚结果.错误说明)
        self.assertIn("新提交", 回滚结果.值)
        self.assertEqual(文件.read_text(encoding="utf-8"), "第一版\n")
        状态 = 当前状态(str(self.工作区))
        self.assertEqual(状态.值["未提交修改"], [])

    def test_挑拣合入成功(self):
        _新建工作区(self.仓库, self.工作区, 分支名="挑拣分支")
        主线文件 = self.仓库 / "主线新增.txt"
        主线文件.write_text("主线内容\n", encoding="utf-8")
        主线提交 = 提交(str(self.仓库), [str(主线文件)], "主线新增")
        self.assertTrue(主线提交.成功, 主线提交.错误说明)
        结果 = 挑拣合入(str(self.工作区), 主线提交.值["提交"])
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue((self.工作区 / "主线新增.txt").is_file())
        self.assertEqual(
            (self.工作区 / "主线新增.txt").read_text(encoding="utf-8"), "主线内容\n")

    def test_冲突自动中止(self):
        _新建工作区(self.仓库, self.工作区, 分支名="冲突分支")
        (self.工作区 / "基线.txt").write_text("工作区改基线\n", encoding="utf-8")
        工作区提交 = 提交(str(self.工作区), [str(self.工作区 / "基线.txt")], "工作区改基线")
        self.assertTrue(工作区提交.成功, 工作区提交.错误说明)
        (self.仓库 / "基线.txt").write_text("主线改基线\n", encoding="utf-8")
        主线提交 = 提交(str(self.仓库), [str(self.仓库 / "基线.txt")], "主线改基线")
        self.assertTrue(主线提交.成功, 主线提交.错误说明)
        结果 = 挑拣合入(str(self.工作区), 主线提交.值["提交"])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "冲突")
        self.assertTrue(结果.详细信息["中止成功"])
        状态 = 当前状态(str(self.工作区))
        self.assertTrue(状态.成功, 状态.错误说明)
        self.assertEqual(状态.值["未提交修改"], [], "冲突中止后应恢复干净状态")
        self.assertEqual(状态.值["分支"], "冲突分支")
        self.assertEqual(
            (self.工作区 / "基线.txt").read_text(encoding="utf-8"), "工作区改基线\n")

    def test_未提交修改关闭拒绝(self):
        _新建工作区(self.仓库, self.工作区, 分支名="待关分支")
        文件 = self.工作区 / "未提交.txt"
        文件.write_text("未提交内容\n", encoding="utf-8")
        结果 = 关闭工作区(str(self.仓库), str(self.工作区))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未提交修改")
        self.assertTrue(self.工作区.is_dir(), "非强制拒绝后工作区必须保留")
        提交结果 = 提交(str(self.工作区), [str(文件)], "先提交再关闭")
        self.assertTrue(提交结果.成功, 提交结果.错误说明)
        关闭结果 = 关闭工作区(str(self.仓库), str(self.工作区))
        self.assertTrue(关闭结果.成功, 关闭结果.错误说明)
        self.assertFalse(self.工作区.exists(), "关闭后工作区目录必须删除")
        查询 = 查询工作区(str(self.仓库))
        路径列表 = [str(Path(条目["路径"]).resolve()) for 条目 in 查询.值["工作区列表"]]
        self.assertNotIn(str(self.工作区.resolve()), 路径列表, "零残留：工作区已注销")

    def test_仓库不存在与路径越界(self):
        结果 = 当前状态(str(self.临时根 / "不存在"))
        self.assertEqual(结果.错误码, "仓库不存在")
        结果 = 提交(str(self.临时根 / "不存在"), [str(self.仓库 / "基线.txt")], "消息")
        self.assertEqual(结果.错误码, "仓库不存在")
        结果 = 提交(str(self.仓库), [str(self.临时根 / "仓库外.txt")], "消息")
        self.assertEqual(结果.错误码, "路径越界")

    def test_命令失败与空消息(self):
        结果 = 回滚(str(self.仓库), "f" * 40)
        self.assertEqual(结果.错误码, "命令失败")
        结果 = 提交(str(self.仓库), [str(self.仓库 / "基线.txt")], "")
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 提交(str(self.仓库), [], "空路径列表")
        self.assertEqual(结果.错误码, "参数不合法")

    def test_提供者不可用注入(self):
        from 支持库.适配层.Git提供者.实现 import 受管执行 as 执行模块
        with mock.patch.object(执行模块.subprocess, "Popen",
                               side_effect=OSError("模拟 git 缺失")):
            结果 = 当前状态(str(self.仓库))
        self.assertEqual(结果.错误码, "提供者不可用")

    def test_注册能力(self):
        from 公共契约.能力契约.契约 import 能力注册表
        from 支持库.适配层.Git提供者 import 注册能力
        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in ["Git操作.检查提供者", "Git操作.创建工作区", "Git操作.查询工作区",
                       "Git操作.关闭工作区", "Git操作.提交", "Git操作.回滚",
                       "Git操作.挑拣合入", "Git操作.当前状态"]:
            实现 = 注册表.获取(能力id)
            self.assertIsNotNone(实现, 能力id)
            self.assertEqual(实现.包id, "支持库.适配层.Git提供者")


if __name__ == "__main__":
    unittest.main()
