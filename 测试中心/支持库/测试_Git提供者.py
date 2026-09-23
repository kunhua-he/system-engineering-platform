"""Git 提供者测试：临时目录自建 git 仓库真实调用（全部真实 git 执行）。

覆盖：检查提供者/创建工作区/查询工作区/提交/回滚/挑拣合入/当前状态/
关闭工作区/获取当前提交哈希；参数注入拒绝（分支名/路径/哈希 含 ;|& 换行
等元字符）；未提交修改关闭拒绝（非强制）；冲突自动中止恢复干净状态；
提供者不可用注入；超时注入；仓库不存在/路径越界/命令失败；detached HEAD
分支为 HEAD；临时仓库与 worktree 全部清理（零残留）。
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
    提交, 回滚, 挑拣合入, 当前状态, 获取当前提交哈希, 推送,
)


def _运行git(目录: str, *参数: str) -> subprocess.CompletedProcess:
    """测试辅助：真实 git 调用（测试侧允许直接使用 git 做场景搭建）。"""
    return subprocess.run(
        ["git", "-C", 目录, *参数], capture_output=True, text=True, timeout=60)


def _建裸远端(路径: Path) -> Path:
    """真实 git init --bare 建裸远端（推送的落点）。"""
    subprocess.run(["git", "init", "--bare", "-b", "main", str(路径)],
                   capture_output=True, text=True, timeout=60, check=True)
    return 路径


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

    def test_命令失败与空消息与全量暂存语义(self):
        结果 = 回滚(str(self.仓库), "f" * 40)
        self.assertEqual(结果.错误码, "命令失败")
        结果 = 提交(str(self.仓库), [str(self.仓库 / "基线.txt")], "")
        self.assertEqual(结果.错误码, "参数不合法")
        # 空路径列表 = 全量 `git add -A`（2026-09-20 语义变更：原为「参数不合法」）
        (self.仓库 / "全量暂存探针.txt").write_text("新文件\n", encoding="utf-8")
        结果 = 提交(str(self.仓库), [], "全量暂存语义")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["全量暂存"], True)
        self.assertEqual(结果.值["路径列表"], [])
        self.assertEqual(结果.值["消息"], "全量暂存语义")
        self.assertEqual(_运行git(str(self.仓库), "status", "--porcelain").stdout.strip(), "")
        # 路径列表非列表（非法类型）仍必须是「参数不合法」
        结果 = 提交(str(self.仓库), "不是列表", "类型非法")
        self.assertEqual(结果.错误码, "参数不合法")

    def test_提供者不可用注入(self):
        with mock.patch("subprocess.Popen", autospec=True,
                        side_effect=OSError("模拟 git 缺失")):
            结果 = 当前状态(str(self.仓库))
        self.assertEqual(结果.错误码, "提供者不可用")

    def test_获取当前提交哈希_正常分支与真实git一致(self):
        结果 = 获取当前提交哈希(str(self.仓库))
        self.assertTrue(结果.成功, 结果.错误说明)
        真实哈希 = _运行git(str(self.仓库), "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(结果.值["提交哈希"], 真实哈希)
        self.assertEqual(结果.值["分支"], "main")

    def test_获取当前提交哈希_detached头分支为HEAD(self):
        detach = _运行git(str(self.仓库), "checkout", "--detach")
        self.assertEqual(detach.returncode, 0, detach.stderr)
        结果 = 获取当前提交哈希(str(self.仓库))
        self.assertTrue(结果.成功, 结果.错误说明)
        真实哈希 = _运行git(str(self.仓库), "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(结果.值["提交哈希"], 真实哈希)
        self.assertEqual(结果.值["分支"], "HEAD")

    def test_获取当前提交哈希_非仓库命令失败(self):
        空目录 = self.临时根 / "空目录"
        空目录.mkdir()
        结果 = 获取当前提交哈希(str(空目录))
        self.assertEqual(结果.错误码, "命令失败")
        结果 = 获取当前提交哈希(str(self.临时根 / "不存在"))
        self.assertEqual(结果.错误码, "命令失败")

    def test_获取当前提交哈希_提供者不可用注入(self):
        with mock.patch("subprocess.Popen", autospec=True,
                        side_effect=OSError("模拟 git 缺失")):
            结果 = 获取当前提交哈希(str(self.仓库))
        self.assertEqual(结果.错误码, "提供者不可用")

    def test_获取当前提交哈希_超时注入(self):
        class _挂起进程:
            """模拟 git 卡死：受限通信需 poll() 返回 None 触发超时。"""

            pid = 2147483000
            stdin = stdout = stderr = None

            def poll(self):
                return None

            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired("git", timeout)

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("git", timeout)

        with mock.patch("subprocess.Popen", autospec=True,
                        return_value=_挂起进程()):
            结果 = 获取当前提交哈希(str(self.仓库), 超时秒=1)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)

    def test_获取当前提交哈希_参数注入拒绝(self):
        结果 = 获取当前提交哈希("")
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 获取当前提交哈希(str(self.仓库), 超时秒=0)
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 获取当前提交哈希(str(self.仓库), 超时秒=-1)
        self.assertEqual(结果.错误码, "参数不合法")
        结果 = 获取当前提交哈希(str(self.仓库), 超时秒="60")
        self.assertEqual(结果.错误码, "参数不合法")

    def test_注册能力(self):
        from 公共契约.能力契约.契约 import 能力注册表
        from 支持库.适配层.Git提供者 import 注册能力
        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in ["Git操作.检查提供者", "Git操作.创建工作区", "Git操作.查询工作区",
                       "Git操作.关闭工作区", "Git操作.提交", "Git操作.推送",
                       "Git操作.回滚",
                       "Git操作.挑拣合入", "Git操作.当前状态",
                       "Git操作.获取当前提交哈希"]:
            实现 = 注册表.获取(能力id)
            self.assertIsNotNone(实现, 能力id)
            self.assertEqual(实现.包id, "支持库.适配层.Git提供者")


class Test推送(unittest.TestCase):
    """`Git操作.推送` 真实推送测试（本地裸仓当远端，全部真实 git 执行）。

    为什么单开一类：推送是**唯一会改变仓库之外状态的**能力（本地提交只动自己，
    推送动远端），因此除正向链外必须逐条证否安全边界 —— 远端名参数注入、
    仓库根白名单、detached HEAD 推不出分支、超时参数。
    """

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_Git推送_"))
        self.仓库 = _初始化仓库(self.临时根 / "仓库")
        self.远端 = _建裸远端(self.临时根 / "远端.git")

    def tearDown(self):
        shutil.rmtree(self.临时根, ignore_errors=True)
        self.assertFalse(self.临时根.exists())

    def test_推送_显式远端路径与分支_远端真的收到提交(self):
        """正向链：断言**远端真的有了这条提交**，而不是只看「成功」两个字。"""
        本地头 = _运行git(str(self.仓库), "rev-parse", "HEAD").stdout.strip()
        结果 = 推送(str(self.仓库), 远端=str(self.远端), 分支="main")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["分支"], "main")
        self.assertEqual(结果.值["提交哈希"], 本地头)
        远端头 = subprocess.run(
            ["git", "-C", str(self.远端), "rev-parse", "main"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(远端头.returncode, 0, 远端头.stderr)
        self.assertEqual(远端头.stdout.strip(), 本地头)

    def test_推送_远端名走配置_缺省origin且分支缺省当前分支(self):
        _运行git(str(self.仓库), "remote", "add", "origin", str(self.远端))
        结果 = 推送(str(self.仓库))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["远端"], "origin")
        self.assertEqual(结果.值["分支"], "main")

    def test_推送_重复推送幂等(self):
        """同一提交推两次：第二次是 Everything up-to-date，仍判成功（网络重试安全）。"""
        第一次 = 推送(str(self.仓库), 远端=str(self.远端), 分支="main")
        self.assertTrue(第一次.成功, 第一次.错误说明)
        第二次 = 推送(str(self.仓库), 远端=str(self.远端), 分支="main")
        self.assertTrue(第二次.成功, 第二次.错误说明)
        self.assertEqual(第二次.值["提交哈希"], 第一次.值["提交哈希"])

    def test_推送_远端名参数注入拒绝(self):
        """反向验证：`-` 开头的远端名会被 git 当**选项**解析（`--upload-pack=…`
        可挂任意命令），必须在**碰 git 之前**就拒。"""
        for 远端 in ["--upload-pack=touch /tmp/被注入",
                     "-u", "--exec=谁", "含 空格", "含;分号", "含\n换行", "含`反引号"]:
            结果 = 推送(str(self.仓库), 远端=远端, 分支="main")
            self.assertEqual(结果.错误码, "参数不合法", repr(远端))
            self.assertIn("远端名", 结果.错误说明, repr(远端))
        self.assertFalse(Path("/tmp/被注入").exists(), "注入面必须完全没被执行")

    def test_推送_分支名参数注入拒绝(self):
        for 分支 in ["-f", "--force", "含 空格", "含;分号", "含`反引号"]:
            结果 = 推送(str(self.仓库), 远端=str(self.远端), 分支=分支)
            self.assertEqual(结果.错误码, "参数不合法", repr(分支))

    def test_推送_仓库根白名单外拒绝(self):
        """`/tmp` 解析为 `/private/tmp`，不在白名单（底座仓根 / 系统临时目录）内。"""
        结果 = 推送("/tmp", 远端=str(self.远端), 分支="main")
        self.assertEqual(结果.错误码, "路径越界")
        self.assertIn("白名单", 结果.错误说明)

    def test_推送_仓库不存在(self):
        结果 = 推送(str(self.临时根 / "没有这个目录"), 远端=str(self.远端), 分支="main")
        self.assertEqual(结果.错误码, "仓库不存在")

    def test_推送_detached头未给分支拒绝(self):
        """detached HEAD 下推不出「当前分支」，不许猜。"""
        _运行git(str(self.仓库), "checkout", "--detach", "HEAD")
        结果 = 推送(str(self.仓库), 远端=str(self.远端))
        self.assertEqual(结果.错误码, "参数不合法")
        self.assertIn("detached", 结果.错误说明)

    def test_推送_远端不存在时命令失败(self):
        结果 = 推送(str(self.仓库), 远端=str(self.临时根 / "没有这个远端.git"), 分支="main")
        self.assertEqual(结果.错误码, "命令失败")
        self.assertTrue(结果.错误说明)

    def test_推送_超时参数校验(self):
        for 超时 in [0, -1, "60", True]:
            结果 = 推送(str(self.仓库), 远端=str(self.远端), 分支="main", 超时秒=超时)
            self.assertEqual(结果.错误码, "参数不合法", repr(超时))

    def test_推送_提供者不可用注入(self):
        with mock.patch("subprocess.Popen", autospec=True,
                        side_effect=OSError("模拟 git 缺失")):
            结果 = 推送(str(self.仓库), 远端=str(self.远端), 分支="main")
        self.assertEqual(结果.错误码, "提供者不可用")


class Test提交多行与文件清单(unittest.TestCase):
    """`Git操作.提交` 的多行消息与回带文件清单（2026-09-21）。

    为什么单开一类：提交纪律要求「提交后核对文件数，防把别人的半成品带进来」，
    此前只能回终端 `git show --stat HEAD` 核对。这条腿收进返回值后必须证明两件事——
    ① 多行消息真的落进 commit（换行从「禁止」放开为「允许」，`\\r`/NUL 仍拒）；
    ② 提交文件/文件数 与真实 git 输出逐条一致，且**中文路径不许被转义**：本仓文件名
    全中文，而 `git show --name-only` 缺省把非 ASCII 路径转义成 `"\\346\\226\\207…"`，
    不关 quotePath 回带的就是一堆转义串，比对根本无从谈起。
    """

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_Git提交清单_"))
        self.仓库 = _初始化仓库(self.临时根 / "仓库")
        # **必须显式把转义开关打开**：本机全局 gitconfig 恰好是 quotePath=false（实测），
        # 不显式打开则「不转义」的断言在没修的环境里也照样绿 —— 那就是假绿（实测踩过：
        # 摘掉生产代码里的开关，三条中文路径断言全部照绿）。仓库级 true 复现 git 的
        # 出厂缺省，而命令行 `-c` 优先级高于任何配置文件，所以生产代码里的开关仍能压住它。
        _运行git(str(self.仓库), "config", "core.quotePath", "true")

    def tearDown(self):
        shutil.rmtree(self.临时根, ignore_errors=True)
        self.assertFalse(self.临时根.exists())

    def test_提交_多行消息真的落进commit(self):
        (self.仓库 / "多行消息探针.txt").write_text("内容\n", encoding="utf-8")
        消息 = "开工ID 标题行\n\n为什么：说明\n逐条改动：一、二"
        结果 = 提交(str(self.仓库), [], 消息)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["消息"], 消息)
        真实 = _运行git(str(self.仓库), "log", "-1", "--pretty=%B").stdout
        self.assertEqual(真实.rstrip("\n"), 消息)

    def test_提交_回车与NUL仍拒绝(self):
        for 坏消息 in ["标题\r正文", "标题\x00正文"]:
            结果 = 提交(str(self.仓库), [], 坏消息)
            self.assertEqual(结果.错误码, "参数不合法", repr(坏消息))

    def test_提交_文件清单与真实git一致_中文路径不转义(self):
        (self.仓库 / "中文新增文件.txt").write_text("内容\n", encoding="utf-8")
        (self.仓库 / "另一个中文文件.txt").write_text("内容\n", encoding="utf-8")
        结果 = 提交(str(self.仓库), [
            str(self.仓库 / "中文新增文件.txt"),
            str(self.仓库 / "另一个中文文件.txt")], "只提交这两个")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["文件数"], 2)
        self.assertEqual(sorted(结果.值["提交文件"]),
                         ["中文新增文件.txt", "另一个中文文件.txt"])
        真实 = _运行git(str(self.仓库), "-c", "core.quotePath=false",
                        "show", "--name-only", "--pretty=format:", "HEAD").stdout
        self.assertEqual(结果.值["提交文件"],
                         [行.strip() for 行 in 真实.splitlines() if 行.strip()])
        # 未显式暂存的改动不在清单里（清单是「本次 commit 真正带走的」，不是「工作区改动」）
        (self.仓库 / "未暂存.txt").write_text("内容\n", encoding="utf-8")
        (self.仓库 / "中文新增文件.txt").write_text("改过了\n", encoding="utf-8")
        再提交 = 提交(str(self.仓库), [str(self.仓库 / "中文新增文件.txt")], "只改一个")
        self.assertTrue(再提交.成功, 再提交.错误说明)
        self.assertEqual(再提交.值["提交文件"], ["中文新增文件.txt"])

    def test_当前状态与查询工作区_中文路径不转义(self):
        """同一口径的第二、三处：`当前状态.未提交修改` 与 `查询工作区.工作区列表.路径`。

        转义开关放在 执行git（所有 git 输出的共同口径）而不是 提交 一个调用点，所以
        这两处必须一并验证 —— 只验提交，等于只验了三分之一。
        """
        (self.仓库 / "中文改动.txt").write_text("内容\n", encoding="utf-8")
        状态 = 当前状态(str(self.仓库))
        self.assertTrue(状态.成功, 状态.错误说明)
        未提交 = " ".join(状态.值["未提交修改"])
        self.assertIn("中文改动.txt", 未提交, 状态.值["未提交修改"])
        self.assertNotIn("\\", 未提交, 状态.值["未提交修改"])

        工作区 = _新建工作区(self.仓库, self.临时根 / "中文工作区")
        查询 = 查询工作区(str(self.仓库))
        self.assertTrue(查询.成功, 查询.错误说明)
        路径表 = [项["路径"] for 项 in 查询.值["工作区列表"]]
        self.assertTrue(any("中文工作区" in 路径 for 路径 in 路径表), 路径表)
        self.assertFalse([路径 for 路径 in 路径表 if "\\" in 路径], 路径表)

    def test_反向验证_摘掉转义开关时中文路径确实被转义(self):
        """反向样本：**裸 git 调用**（继承仓库级 quotePath=true）必须回带转义串。

        这一条是「生产代码里那个开关真在起作用」的证明：setUp 已把仓库级开关置 true，
        裸调用就是「没有修复时的世界」，它转义、而能力返回值不转义，差异只可能来自
        `-c core.quotePath=false`。本机全局 gitconfig 恰好关了转义，若不在夹具里显式
        打开，这个反向样本同样会假绿。
        """
        (self.仓库 / "中文新增文件.txt").write_text("内容\n", encoding="utf-8")
        结果 = 提交(str(self.仓库), [str(self.仓库 / "中文新增文件.txt")], "反向样本")
        self.assertTrue(结果.成功, 结果.错误说明)
        转义 = _运行git(str(self.仓库), "show", "--name-only",
                        "--pretty=format:", "HEAD").stdout
        self.assertIn("\\", 转义, f"预期裸调用回带转义串，实际：{转义!r}")
        self.assertEqual(结果.值["提交文件"], ["中文新增文件.txt"])


class Test提交强制点第2层(unittest.TestCase):
    """提交腿自判「开工ID + 钩子接线」（2026-09-23，强制点第 2 层）。

    为什么要有第 2 层：第 1 层的 `开发工具/git钩子/commit-msg` 有一个**可达上限** ——
    `core.hooksPath` 是仓库本地配置，一条 `git config --unset core.hooksPath` 就把它
    **静默关掉**，此后提交再无拦截、且没有任何东西会报出来。故同一条规则必须**也**判在
    提交腿上（必经路径），两处各自独立生效。

    本类全部走**公开入口 `提交`**（不 import `实现/`，避免与「跨包禁止导入 实现/」
    及测试白名单计数纠缠）；临时仓库里造一个钩子文件即可构造出「本仓」形态。
    ★ 真仓库的 `core.hooksPath` 接线断言不在这里重复 —— 它在
    `测试中心/开发工具/测试_git钩子.py`（同一件事不留第二套判据）。
    """

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_提交强制点_"))
        self.仓库 = _初始化仓库(self.临时根 / "仓库")
        self.钩子目录 = self.仓库 / "开发工具" / "git钩子"
        self.钩子目录.mkdir(parents=True)
        (self.钩子目录 / "commit-msg").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _接线(self):
        _运行git(str(self.仓库), "config", "core.hooksPath", "开发工具/git钩子")

    def _改一个文件(self, 名: str) -> Path:
        文件 = self.仓库 / 名
        文件.write_text("内容\n", encoding="utf-8")
        return 文件

    def test_接线且消息带开工ID_放行并回带强制点(self):
        self._接线()
        文件 = self._改一个文件("甲.txt")
        结果 = 提交(str(self.仓库), [str(文件)],
                   "开工-20260923-131126-78e8 甲：新增一个文件并验证")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["提交文件"], ["甲.txt"])
        self.assertEqual("开发工具/git钩子", 结果.值["强制点"]["hooksPath"],
                         "放行时必须在回包里写明强制点落在哪 —— 否则调用方不知道它被谁放的行")

    def test_反向_钩子在但消息没有开工ID_必须拒且不落提交(self):
        """这是第 2 层的**存在理由**：钩子被关掉时，这条判据必须还拦得住。

        故本用例**故意不接线**（`core.hooksPath` 未设）：此刻第 1 层已经失效，
        拦截只可能来自本腿 —— 拦不住就说明第 2 层是装饰。
        """
        self.assertNotEqual(
            "开发工具/git钩子",
            _运行git(str(self.仓库), "config", "--get", "core.hooksPath").stdout.strip(),
            "夹具前提：本用例必须在不接线的仓库里跑，否则测不出第 2 层")
        文件 = self._改一个文件("乙.txt")
        结果 = 提交(str(self.仓库), [str(文件)], "随手提交一句，没有开工ID")
        self.assertFalse(结果.成功, "钩子已失效时提交腿必须自己拦住无开工ID 的提交")
        self.assertEqual("提交被拒", 结果.错误码, 结果.错误说明)
        现存 = _运行git(str(self.仓库), "log", "--oneline").stdout
        self.assertNotIn("随手提交", 现存, "被拒的提交不得留痕")

    def test_反向_钩子在但hooksPath没接线_必须拒(self):
        """「钩子文件在」不等于「git 会调用它」—— 这个差别正是静默失效的入口。"""
        文件 = self._改一个文件("丙.txt")
        结果 = 提交(str(self.仓库), [str(文件)],
                   "开工-20260923-131126-78e8 丙：消息合规，但钩子没接线")
        self.assertFalse(结果.成功, "钩子文件在而 hooksPath 没指它 ⇒ 终端腿无人拦，必须拒")
        self.assertEqual("强制点未接线", 结果.错误码, 结果.错误说明)
        self.assertIn("git config core.hooksPath 开发工具/git钩子", 结果.错误说明,
                      "拒绝时必须给出可直接照抄的修法")

    def test_豁免前缀_回退消息不要求开工ID(self):
        """`Revert ` 开头是 git 自身的流程消息，不是「一次开发改动」—— 与钩子同口径。"""
        self._接线()
        文件 = self._改一个文件("丁.txt")
        结果 = 提交(str(self.仓库), [str(文件)],
                   'Revert "某次改动"\n\nThis reverts commit 0123456789abcdef.')
        self.assertTrue(结果.成功, 结果.错误说明)

    def test_钩子文件不在时不拦_别的仓库不受影响(self):
        """误报守卫：没有这道强制点的仓库（或本仓尚未装钩子时）必须照常提交。

        在此处判它是**误报**，而误报会挡死与本题无关的仓库 —— 比不判更糟。
        """
        shutil.rmtree(self.钩子目录)
        文件 = self._改一个文件("戊.txt")
        结果 = 提交(str(self.仓库), [str(文件)], "没有钩子的仓库里，普通消息照常提交")
        self.assertTrue(结果.成功, 结果.错误说明)


if __name__ == "__main__":
    unittest.main()
