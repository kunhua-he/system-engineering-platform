"""工作区指纹定向测试：钉住排除判定与字节指纹的可复现绑定（2026-09-23 修「假红」）。

缺陷背景：`固定排除文件` 原先只做**基名全等**且只列 `.DS_Store`，不认 `.gitignore`
的**文件级**规则；而 `git ls-files --others` 会把 `.gitignore` 已挡、`git status`
看不见的本地残留（`*.db` / `*-wal` / `*-shm` / `*.bak_*` / `zcode.json` / `*.log`
等）照样报出来，被算成「正式文件」。后果有两层：
  ① 工作区恒判「含未提交变更」（本仓实测误计 7 个残留文件）；
  ② 这些残留的字节进了 `工作区字节指纹` —— 同一提交在不同机器 / 不同本地残留下
     指纹不同，**制品来源的可复现绑定是断的**（`制品来源.提交` 对，字节指纹不对）。

修法（已裁决）：保留「排除项只来自显式固定表」的既有设计，只把 `.gitignore` 的
文件级规则补进 `固定排除文件`，判定层用 `fnmatch` 支持通配（无通配字符时即全等，
现有语义不变）。本件锁两件事：
  ① 排除判定按基名通配 —— 应拦的全拦、**真源码一个都不误伤**；
  ② 真仓库夹具上：残留不进指纹/不改状态，真源码与已跟踪改动照进。

反向样本一律在**临时目录造夹具**，绝不改真源码再改回来。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.项目编译.工作区指纹 import (  # noqa: E402
    计算工作区字节指纹,
    指纹语义,
    _是正式路径,
)


class 排除判定反向验证(unittest.TestCase):
    """排除判定的正反样本：每条都自带「应被拦」与「不该误伤」两侧。

    只有「应被拦」一侧会漏掉**误伤**缺陷（把真源码也挡了，指纹就少算了东西，
    而且这种红是静默的）；只有「不该误伤」一侧会漏掉**漏网**缺陷（假红依旧）。
    """

    应排除 = (
        # `.gitignore` 文件级规则镜像（本次补的那批）
        "x.db",
        "权威状态.db",
        "权威状态.db-wal",
        "权威状态.db-shm",
        "x.sqlite3",
        "x.sqlite3-wal",
        "x.sqlite3-shm",
        "任意基名-wal",
        "任意基名-shm",
        "c.bak",
        "AGENTS.md.bak_20260922_拆分前",
        "能力定义.json.bak_20260922_体量门禁前",
        "c.bak-1",
        "d.orig",
        "e~",
        ".env",
        "f.log",
        "g.tmp",
        ".测试值.1.tmp",
        "zcode.json",
        ".DS_Store",
        # 嵌套路径按**基名**判定，与所在目录无关
        "子目录/嵌套.db",
        "子目录/更深/zcode.json",
        "支持库/后端/某库/某能力.json.bak_20260923",
    )

    不应排除 = (
        # 真源码/契约/文档：一个都不能被误伤
        "a.py",
        "基线.py",
        "模块库/公共模块/模块.py",
        "支持库/后端/文件系统支持库/文件操作/能力定义.json",
        "开发文档/项目说明.md",
        "README.md",
        "AGENTS.md",
        ".gitignore",
        # 名字里带关键词但**不匹配通配**的边界样本（防通配写宽了）
        "db.py",
        "log.py",
        "x.db.py",
        "zcode.jsonc",
        "备份.bakery",
        ".env.example",
        "a.wal",
    )

    def test_应排除样本全被拦(self):
        for 路径 in self.应排除:
            with self.subTest(路径=路径):
                self.assertFalse(_是正式路径(路径), f"{路径} 应被排除却放行了")

    def test_真源码一个都不误伤(self):
        for 路径 in self.不应排除:
            with self.subTest(路径=路径):
                self.assertTrue(_是正式路径(路径), f"{路径} 是真源码却被误排除")

    def test_目录排除仍生效(self):
        for 路径 in (
            "工程缓存/制品仓库/平台客户端制品/制品来源.json",
            ".git/config",
            "node_modules/a/b.js",
            "支持库/后端/文件系统支持库/__pycache__/x.py",
            "开发文档/项目证据/证据.json",
            ".venv/lib/python3.14/x.py",
            "某目录/.pytest_cache/v/cache/nodeids",
        ):
            with self.subTest(路径=路径):
                self.assertFalse(_是正式路径(路径), f"{路径} 属固定排除目录，应被拦")


class 真仓库夹具反向验证(unittest.TestCase):
    """在临时 git 仓库上验**指纹语义**（不依赖真仓库的当前状态，故恒可复现）。

    夹具自带一份基线提交，再按用例造残留或真改动 —— 正样本（残留）必须无痕，
    负样本（真源码/已跟踪改动）必须进指纹，两侧都有才说明这道闸门真在起作用。
    """

    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("环境无 git，跳过真仓库夹具")
        self._临时 = tempfile.TemporaryDirectory()
        self.addCleanup(self._临时.cleanup)
        self.根 = Path(self._临时.name).resolve()
        self._git("init", "-q")
        (self.根 / "基线.py").write_text("基线 = 1\n", encoding="utf-8")
        self._git("add", "基线.py")
        self._git(
            "-c", "user.name=测试", "-c", "user.email=测试@示例",
            "commit", "-q", "-m", "基线",
        )

    def _git(self, *参数: str) -> bytes:
        return subprocess.run(
            ["git", *参数], cwd=self.根, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True, timeout=30,
        ).stdout

    def _造残留(self, *文件名: str) -> None:
        for 名 in 文件名:
            目标 = self.根 / 名
            目标.parent.mkdir(parents=True, exist_ok=True)
            目标.write_text("本地残留\n", encoding="utf-8")

    def test_gitignore级残留不进指纹也不改状态(self):
        """缺陷现象的正样本：造出当年那 7 类的残留，状态必须仍是「干净」。"""
        self._造残留(
            "权威状态.db", "权威状态.db-wal", "权威状态.db-shm",
            "zcode.json", "AGENTS.md.bak_20260922_拆分前",
            "子目录/能力定义.json.bak_20260922_体量门禁前",
            "x.log", "y.tmp", ".env", ".DS_Store",
        )
        结果 = 计算工作区字节指纹(self.根)
        self.assertEqual(0, 结果["未跟踪正式文件数"],
                         f"残留被误计成正式文件：{结果}")
        self.assertEqual("干净", 结果["工作区状态"],
                         f"有残留却判成含变更（假红未除）：{结果}")

    def test_真源码进指纹且判含变更(self):
        """负样本一：新增真源码必须照进 —— 否则上面那条在任何实现下都绿。"""
        (self.根 / "新源码.py").write_text("新 = 1\n", encoding="utf-8")
        结果 = 计算工作区字节指纹(self.根)
        self.assertEqual(1, 结果["未跟踪正式文件数"], f"真源码漏算：{结果}")
        self.assertEqual("含未提交变更", 结果["工作区状态"], f"真改动应判含变更：{结果}")

    def test_已跟踪改动仍进指纹(self):
        """负样本二：改已跟踪文件走「未暂存」腿，与排除表无关，必须照进。"""
        (self.根 / "基线.py").write_text("基线 = 2\n", encoding="utf-8")
        结果 = 计算工作区字节指纹(self.根)
        self.assertEqual(1, 结果["未暂存正式文件数"], f"已跟踪改动漏算：{结果}")
        self.assertEqual("含未提交变更", 结果["工作区状态"], f"真改动应判含变更：{结果}")

    def test_本地残留不改变字节指纹(self):
        """可复现绑定：残留的**有无与内容**都不得影响字节指纹。"""
        基线指纹 = 计算工作区字节指纹(self.根)["工作区字节指纹"]
        self._造残留("x.db")
        A = 计算工作区字节指纹(self.根)["工作区字节指纹"]
        (self.根 / "x.db").write_text("B" * 100, encoding="utf-8")
        self._造残留("y.log", "z.tmp")
        B = 计算工作区字节指纹(self.根)["工作区字节指纹"]
        self.assertEqual(基线指纹, A, "新增残留改变了字节指纹（跨机不可复现）")
        self.assertEqual(A, B, "残留内容变化改变了字节指纹（跨机不可复现）")

    def test_对外契约键与语义冻结(self):
        """消费者（客户端构建、项目编译、发布门禁）依赖的键名与语义串不许变。"""
        结果 = 计算工作区字节指纹(self.根)
        self.assertEqual(
            {
                "提交", "工作区字节指纹", "工作区状态", "语义", "排除目录",
                "暂存差异字节数", "未暂存正式文件数", "未跟踪正式文件数",
            },
            set(结果),
            f"对外键集合变了：{sorted(结果)}",
        )
        self.assertEqual(指纹语义, 结果["语义"], "语义串是对外契约，不许改")
        self.assertIn(结果["工作区状态"], ("干净", "含未提交变更"))


if __name__ == "__main__":
    unittest.main()
