"""仓库只读锁（内核级封禁）回归锁：华哥裁决「纯粹电脑硬件权限管控」。

## 华哥裁决原文（2026-09-23）

> 「现在写和使用终端，还没有做强限制吗？……整个项目走**固定的封禁**。
>   不靠 agent 自觉，**纯粹电脑硬件权限管控**。」
> 「**仅限这个项目。**」

## 本文件锁什么（每条都对应一处实测形状）

1. **内核真的拒绝**（不是我们的代码在拒绝）：`chflags uchg` 之后，`echo >>`、`echo >`、
   `truncate`、`rm`、`mv`、`chmod`、`sed -i`、`tee`、Python `open(w)`、Python `open(a)`、
   `os.replace` —— **11 条全部**被内核以 `Operation not permitted` 拒。这是「不靠 agent 自觉」
   的机器根据：绕过者连我们的进程都不进入，所以只能由内核拒。
2. **父目录锁不保护子文件内容写**（边界，必须如实测出）：给父目录上锁后，子文件**内容照样
   能改** ⇒ 所以必须**逐文件**上锁，不能只锁目录。这条判据的存在是为了防后人「优化」成
   只锁目录（那会让整仓其实没锁）。
3. **写腿能穿过锁**（锁是门不是墙）：写入文件 / 应用精确替换 / 删除文件 在**目标已锁**时
   仍成功 —— 靠 `临时解锁()` 的「解锁→写→重锁」窗口。
4. **锁在写完之后自动恢复**：这是最容易被写坏的一条 —— 若重锁漏了，一次平台写入
   就把锁吃掉了，而**测试若只断言「写成功」会全绿**。故每条写腿都追加「写后仍锁着」。
5. **重锁不扩散**：本来没锁的新文件，经写腿写完**不该被凭空锁上**（锁的范围只由
   `上锁全仓()` 决定，不由谁碰过它决定）。
6. **查询能度量缺口**：`查询()` 的 `未锁数` 全仓为 0 才算「锁住了」；中途被杀留下的
   缺口靠 `重锁一遍()` 补齐（幂等）。
7. **解锁这条腿只认网关凭证**（2026-09-23 华哥裁决「只有 mcp 才能解锁，禁止用其他方式
   解锁」）：`解锁()` / `解锁全仓()` 无凭证即抛 `PermissionError`，且**不认**
   `系统平台_修MCP自身=1` 白名单（否则加一个环境变量前缀就能一行命令解开整仓锁）；
   而**写腿的瞬时窗口** `临时解锁()` / `临时解锁树()` 不受门槛影响（否则平台自己的落盘腿
   会被一起锁死）。★ 前 6 条都是「锁生效」的正向样本 —— 第 7 条必须配**反向样本**
   （`Test解锁只认网关凭证`）：少了它，把门槛整段删掉本文件照样全绿。

## 夹具策略（**不锁真仓库**）

本文件所有用例都在 `tempfile` 临时根里造小树，**绝不对真仓库上锁**：真仓库的锁由
「显式动作」（平台能力 / 脚本）施加，不该由测试的副作用施加 —— 否则跑一次测试就改了
全仓权限状态，属「测试有副作用」那一类缺陷。真仓库的整体状态由
`仓库只读锁.查询(<仓库根>)` 现场读数，不在测试里断言（那是运维读数，不是回归判据）。

夹具**假装自己是网关**（`setUp` 里设 `系统库网关凭证`），因为本文件大多数用例要测的正是
「经 MCP 那条路」的行为；**无凭证那几条在用例内把变量摘掉**再断言（`_设凭证(None)`），
验完由 `addCleanup` 还原。
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时 import 仓库只读锁 as 锁
from 公共契约.基础类型.逻辑类型 import 真, 假


class 锁夹具(unittest.TestCase):
    #: 夹具凭证：`解锁()` 只认网关凭证（2026-09-23 华哥裁决「只有 mcp 才能解锁」），
    #: 而本文件大多数用例要测的正是**经 MCP 那条路**的行为 ⇒ 夹具假装自己是网关。
    #: 「无凭证被拒」那几条另有专门用例（`Test解锁只认网关凭证`），用例内把变量摘掉再断言。
    夹具凭证 = "回归锁-夹具"

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="只读锁_")
        self.根 = Path(self._临时.name)
        self.文件 = self.根 / "目标.txt"
        self.文件.write_text("原始内容\n", encoding="utf-8")
        self._设凭证(self.夹具凭证)

    def _设凭证(self, 值: str | None) -> None:
        """设 / 摘网关凭证变量（摘 = 传 `None`），并登记恢复到用例前的值。"""
        旧 = os.environ.get("系统库网关凭证")
        if 值 is None:
            os.environ.pop("系统库网关凭证", None)
        else:
            os.environ["系统库网关凭证"] = 值

        def _还原() -> None:
            if 旧 is None:
                os.environ.pop("系统库网关凭证", None)
            else:
                os.environ["系统库网关凭证"] = 旧

        self.addCleanup(_还原)

    def tearDown(self) -> None:
        # 兜底解锁（否则 tmp 清理会失败 —— 锁着的东西删不掉，这是锁生效的副产品）
        for 项 in sorted(self.根.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            try:
                os.chflags(项, 0)
            except OSError:
                pass
        try:
            os.chflags(self.根, 0)
        except OSError:
            pass
        self._临时.cleanup()

    def 变体(self, 名: str) -> Path:
        路径 = self.根 / 名
        路径.write_text("原始内容\n", encoding="utf-8")
        return 路径


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test内核真的拒写(锁夹具):
    """① 11 条写入路径逐条实测 —— 这条是「不靠 agent 自觉」的机器根据。"""

    def _断言被拒(self, 名: str, 动作) -> None:
        目标 = self.变体(名)
        锁.上锁(目标)
        self.assertTrue(锁.是锁着的(目标), "前置：应已上锁")
        with self.assertRaises(Exception, msg=f"{名}：锁着的文件竟然能写"):
            动作(目标)
        self.assertEqual("原始内容\n", 目标.read_text(encoding="utf-8"),
                         f"{名}：被拒了但内容却变了（判据无效）")

    def test_shell写入类全部被拒(self) -> None:
        for 名, 前言 in (("追加", "echo x >>"), ("覆盖", "echo x >"),
                       ("截断", "truncate -s 0"), ("tee", "echo x | tee"),
                       ("sed-i", "sed -i '' s/原始/改/")):
            with self.subTest(命令=前言):
                self._断言被拒(
                    名,
                    lambda p, c=前言: subprocess.run(
                        ["sh", "-c", f"{c} {p}"], check=True, capture_output=True))

    def test_文件系统类全部被拒(self) -> None:
        # 一律走**子进程**（`sh -c`）而不是在本进程里 `p.unlink()`：
        # ① 更忠实 —— 要封禁的正是「agent / 人在终端里的动作」，那发生在**另一个进程**；
        # ② 本进程内直调会把写动作写进本文件、被 `测试写入边界门禁` 判成「写动作未解析」
        #    （目标表达式是夹具参数 `p`，静态解析不出）—— 那 4 条违规正是这么来的。
        for 名, 命令 in (("rm", "rm -f"), ("chmod", "chmod 666")):
            with self.subTest(命令=命令):
                self._断言被拒(名, lambda p, c=命令: subprocess.run(
                    ["sh", "-c", f"{c} {p}"], check=True, capture_output=True))
        self._断言被拒("mv", lambda p: subprocess.run(
            ["sh", "-c", f"mv {p} {p}.改名"], check=True, capture_output=True))

    def test_python写入类全部被拒(self) -> None:
        """Python 写动作也走**子进程**（`python -c`）—— 模拟「另一个 Python 进程直写」。

        为什么不用本进程的 `p.write_text`：一是上面那条「写动作未解析」的门禁，
        二是**本进程直写测不到真实场景** —— agent 落盘从不在我们的进程里做。
        """
        片段表 = (
            ("open-w", "open({p!r},'w').write('x')"),
            ("open-a", "open({p!r},'a').write('x')"),
            ("os-replace", "__import__('os').replace({p!r},{p!r})"),
        )
        for 名, 片段 in 片段表:
            with self.subTest(动作=名):
                def 动(p, f=片段):
                    subprocess.run([sys.executable, "-c", f.format(p=str(p))],
                                   check=True, capture_output=True)
                self._断言被拒(名, 动)


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test锁的边界(锁夹具):
    """② 父目录锁**不**保护子文件内容写 —— 防后人「优化」成只锁目录。"""

    def test_父目录上锁不挡子文件内容写(self) -> None:
        目录 = self.根 / "子目录"
        目录.mkdir()
        内 = 目录 / "在内.txt"
        内.write_text("原始\n", encoding="utf-8")
        锁.上锁(目录)
        self.assertTrue(锁.是锁着的(目录))
        # 边界事实：内容写**照样成功** ⇒ 所以必须逐文件上锁（子进程形态，同上面两条理由）
        subprocess.run(["sh", "-c", f"printf '改了\\n' > {内}"], check=True, capture_output=True)
        self.assertEqual("改了\n", 内.read_text(encoding="utf-8"),
                         "若这条变红，说明本平台行为变了 —— 请复核「只锁目录」是否已够用")

    def test_目录上锁挡住目录内增删条目(self) -> None:
        目录 = self.根 / "锁目录"
        目录.mkdir()
        (目录 / "在里.txt").write_text("x\n", encoding="utf-8")
        锁.上锁(目录)
        with self.assertRaises(Exception):
            subprocess.run(["sh", "-c", f"touch {目录}/新文件.txt"],
                           check=True, capture_output=True)


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test写腿穿过锁(锁夹具):
    """③④⑤ 三条写腿在**已锁**目标上必须成功，且写完锁自动恢复、不扩散。"""

    def _写腿环境(self):
        # 写腿要身份准入；本文件的用例在临时根里跑，故按「修 MCP 自身」白名单放行
        # （README 写明的唯一口子）。用例结束恢复原值。
        旧值 = os.environ.get(锁修MCP变量 := "系统平台_修MCP自身")
        os.environ[锁修MCP变量] = "1"
        self.addCleanup(lambda: (os.environ.__setitem__(锁修MCP变量, 旧值)
                              if 旧值 is not None
                              else os.environ.pop(锁修MCP变量, None)))

    def test_写入文件穿过锁且锁自动恢复(self) -> None:
        self._写腿环境()
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 写入文件
        目标 = self.变体("写腿.txt")
        锁.上锁(目标)
        结果对象 = 写入文件(str(目标), "写腿改过\n")
        self.assertTrue(结果对象.成功, f"写腿被锁挡住了：{结果对象.错误码} {结果对象.错误说明}")
        self.assertEqual("写腿改过\n", 目标.read_text(encoding="utf-8"))
        self.assertTrue(锁.是锁着的(目标),
                        "★ 写完之后锁没恢复 —— 一次平台写入就把锁吃掉了（最隐蔽的坏法）")

    def test_应用精确替换穿过锁且锁自动恢复(self) -> None:
        self._写腿环境()
        from 支持库.后端.文件系统支持库.文本补丁.实现.文本补丁 import 应用精确替换
        目标 = self.变体("补丁.txt")
        锁.上锁(目标)
        结果对象 = 应用精确替换(str(目标), "原始内容", "补丁改过", 根目录=str(self.根))
        self.assertTrue(结果对象.成功, f"补丁腿被锁挡住了：{结果对象.错误码} {结果对象.错误说明}")
        self.assertEqual("补丁改过\n", 目标.read_text(encoding="utf-8"))
        self.assertTrue(锁.是锁着的(目标), "★ 补丁腿写完之后锁没恢复")

    def test_删除文件穿过锁(self) -> None:
        self._写腿环境()
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 删除文件
        目标 = self.变体("待删.txt")
        锁.上锁(目标)
        结果对象 = 删除文件(str(目标))
        self.assertTrue(结果对象.成功, f"删除腿被锁挡住了：{结果对象.错误码} {结果对象.错误说明}")
        self.assertFalse(目标.exists(), "删除了但文件还在")

    def test_新文件继承父目录_锁着就锁上(self) -> None:
        """⑤ 锁的**范围**由父目录决定：父目录锁着 ⇒ 新文件也锁（不留洞）。

        这条修的是一个实测漏锁（2026-09-23 MCP 端到端验收发现）：初版只按「写前状态」
        恢复，而新文件写前不存在 ⇒ 恢复时判定「本来没锁」，于是**平台每写一个新文件，
        整仓锁就多一个洞**（实测：经 MCP 写一个 .md 后该文件 flags 为空、终端仍能改它）。
        """
        self._写腿环境()
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 写入文件
        锁.上锁(self.根)                      # 父目录锁上 ⇒ 模拟「整仓已锁」
        新件 = self.根 / "锁树里的新文件.txt"
        self.assertFalse(新件.exists())
        结果对象 = 写入文件(str(新件), "新内容\n")
        self.assertTrue(结果对象.成功, f"{结果对象.错误码} {结果对象.错误说明}")
        self.assertTrue(锁.是锁着的(新件),
                        "★ 在**已锁**目录里新建的文件没有继承锁 —— 每写一个新文件就多一个洞，"
                        "`查询()` 的未锁数永远回不到 0")

    def test_新文件在未锁目录里不被凭空锁上(self) -> None:
        """⑤ 反向：父目录**没锁**（正常开发期）⇒ 新文件也不该被锁（锁不扩散）。"""
        self._写腿环境()
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 写入文件
        self.assertFalse(锁.是锁着的(self.根), "前置：夹具根目录不该是锁着的")
        新件 = self.根 / "开发期新文件.txt"
        结果对象 = 写入文件(str(新件), "新内容\n")
        self.assertTrue(结果对象.成功, f"{结果对象.错误码} {结果对象.错误说明}")
        self.assertFalse(锁.是锁着的(新件),
                         "★ 未锁目录里的新文件被凭空锁上了 —— 那会让锁的范围随写入不断扩散")


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test扫描面三个漏径(锁夹具):
    """⑦ 扫描面的**三个漏径**（2026-09-23 复核逐条实测出来的，形状都是
    「锁有洞而 `查询()` 仍报全绿」——故每条都要**真跑一次写动作**来判，不看计数）。

    本类的价值在于把「探针结论」钉成判据：这三条早先都漏过，而漏的时候
    `查询()` 报的是「未锁数 0 · 全部上锁」——**读数全绿不等于没有洞**。
    """

    def _断言被拒(self, 名: str, 动作) -> None:
        with self.assertRaises(PermissionError, msg=f"{名}：本该被内核拒绝，实际放行了"):
            动作()

    def test_仓库根也必须进扫描面(self) -> None:
        """漏径 ①：根的父目录链循环把「相对目录为空」当终止条件 ⇒ 根从没被锁。

        实测后果：根下 `touch 顶层探针.txt` **成功**。故本用例**在根下真新建一次**，
        必须被拒 —— 只断言「根在 `_受管条目` 里」不够（那只是必要条件）。
        """
        (self.根 / "a.py").write_text("X=1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        根条目 = {p for p in 锁._受管条目(self.根) if p == self.根}
        self.assertEqual({self.根}, 根条目, "仓库根目录没进扫描面 —— 顶层凭空新建挡不住")
        锁.上锁全仓(self.根)
        self._断言被拒("根下新建顶层文件",
                     lambda: (self.根 / "顶层探针.txt").write_text("x", encoding="utf-8"))

    def test_豁免必须按路径段比不能按裸串比(self) -> None:
        """漏径 ②：父目录链那步用 `startswith(裸前缀)` ⇒ `.github` 命中 `.git` 被豁免。

        `.github` / `.gitattributes` / `.gitignore` **都是本仓跟踪的事实源**，必须上锁。
        故本用例真跑一次 `touch .github/workflows/探针.yml`（实测早先成功）。
        """
        工作流 = self.根 / ".github" / "workflows"
        工作流.mkdir(parents=True)
        (工作流 / "ci.yml").write_text("on: push\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        # 判据层：豁免函数对 .github 系列**不该**判豁免
        for 候选 in (".github", ".github/workflows", ".gitattributes", ".gitignore"):
            with self.subTest(路径=候选):
                self.assertFalse(锁._命中豁免(候选), f"{候选} 被误判为豁免（裸串前缀的典型后果）")
        # 但 .git 自己与工程缓存必须仍然豁免
        for 候选 in (".git", ".git/hooks", "工程缓存", "工程缓存/运行数据"):
            with self.subTest(路径=候选):
                self.assertTrue(锁._命中豁免(候选), f"{候选} 该豁免却没豁免（会锁死 git / 网关）")
        # 行为层：真跑一次写动作
        (self.根 / "a.py").write_text("X=1\n", encoding="utf-8")
        锁.上锁全仓(self.根)
        self._断言被拒("在 .github/workflows 下新建",
                     lambda: (工作流 / "探针.yml").write_text("x", encoding="utf-8"))

    def test_未跟踪空目录也要进扫描面(self) -> None:
        """漏径 ③：`git ls-files` 只列**文件**，空目录不出现 ⇒ 空目录里能凭空新建。

        实测：`开发工具/说明书生成/`、`底座浏览器会话/`、`测试中心/慢速层/` 等
        早先都能新建。这些恰是「本轮新建但还没落文件」的目录，最该锁。
        """
        空目录 = self.根 / "空目录探针"
        空目录.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        条目 = {p for p in 锁._受管条目(self.根) if p == 空目录}
        self.assertEqual({空目录}, 条目, "未跟踪的空目录没进扫描面（`--directory` 那一路没接上）")
        锁.上锁全仓(self.根)
        self._断言被拒("空目录内新建文件",
                     lambda: (空目录 / "探针.txt").write_text("x", encoding="utf-8"))

    def test_豁免以斜杠结尾且工程缓存X不被误豁免(self) -> None:
        """防「裸串前缀」复发：`工程缓存X/` 不该被 `工程缓存/` 豁免掉。

        这条是判据自身的边界样本 —— 早先的 `rstrip("/")` 写法会把它一起豁免。
        """
        self.assertFalse(锁._命中豁免("工程缓存X"),
                         "工程缓存X 被 工程缓存/ 豁免了 —— 又是裸串前缀")
        self.assertFalse(锁._命中豁免("工程缓存X/运行数据"))
        self.assertTrue(锁._命中豁免("工程缓存"))
        self.assertFalse(锁._命中豁免(""), "仓库根不该被判豁免 —— 根要锁")


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test全仓口径(锁夹具):
    """⑥ 扫描面与缺口度量：`git ls-files` 口径 + 豁免前缀 + 重锁幂等。"""

    def test_扫描面排豁免前缀(self) -> None:
        子 = self.根 / "工程缓存"
        子.mkdir()
        (子 / "数据.json").write_text("{}", encoding="utf-8")
        (self.根 / "源码.py").write_text("X=1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        受管 = {p.name for p in 锁._受管文件(self.根)}
        self.assertIn("源码.py", 受管)
        self.assertNotIn("数据.json", 受管, "豁免前缀（工程缓存/）必须排除在扫描面外")

    def test_上锁与查询与解锁形成闭环(self) -> None:
        (self.根 / "a.py").write_text("X=1\n", encoding="utf-8")
        (self.根 / "b.py").write_text("Y=2\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        上锁结果 = 锁.上锁全仓(self.根)
        self.assertGreaterEqual(上锁结果["文件数"], 2, "扫描面太小，构造前提失效")
        self.assertEqual([], 上锁结果["失败表"], f"上锁失败：{上锁结果['失败表']}")
        查询结果 = 锁.查询(self.根)
        self.assertEqual(0, 查询结果["未锁数"],
                         f"上锁后仍有未锁文件：{查询结果['未锁样本']}")
        # 重锁一遍幂等
        重锁结果 = 锁.重锁一遍(self.根)
        self.assertEqual(0, 重锁结果["新锁数"], "重锁一遍不幂等（还有文件被判为未锁）")
        解锁结果 = 锁.解锁全仓(self.根)
        self.assertEqual(0, 锁.查询(self.根)["已锁数"], f"解锁不彻底：{解锁结果}")

    def test_查询能报出缺口(self) -> None:
        (self.根 / "c.py").write_text("Z=3\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        锁.上锁全仓(self.根)
        # 人为制造缺口（模拟「写腿中途被杀」）
        锁.解锁(self.根 / "c.py")
        查询结果 = 锁.查询(self.根)
        self.assertEqual(1, 查询结果["未锁数"], "缺口没被报出来 —— 那锁的强度就不可度量了")
        self.assertIn("c.py", 查询结果["未锁样本"])
        # 兜底补齐
        锁.重锁一遍(self.根)
        self.assertEqual(0, 锁.查询(self.根)["未锁数"], "重锁一遍没把缺口补上")


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test新增条目腿要对齐锁态(锁夹具):
    """⑧ **洞 ④**：所有「会新建条目」的腿（复制/移动/建目录/压缩/解压/多层写入）
    必须按**目标位置**对齐锁态 —— 否则要么在锁树里留洞，要么把锁带出仓库。

    这条与写腿的「新建文件继承父目录」**同根**，但早先只修了写腿、漏了这一族
    （典型「同一根因只修一处、兄弟漏改」）。故本类逐腿真跑，判据是
    **目标位置的 flags 与能否被终端改**，不看返回值。
    """

    def _写腿环境(self):
        旧值 = os.environ.get("系统平台_修MCP自身")
        os.environ["系统平台_修MCP自身"] = "1"
        self.addCleanup(lambda: (os.environ.__setitem__("系统平台_修MCP自身", 旧值)
                              if 旧值 is not None
                              else os.environ.pop("系统平台_修MCP自身", None)))

    def setUp(self) -> None:
        super().setUp()
        self._写腿环境()
        # 仓外临时区（未锁）：用来放「搬进来的源」与「搬出去的落点」
        self._外部 = tempfile.TemporaryDirectory(prefix="锁外区_")
        self.外部 = Path(self._外部.name)
        self.addCleanup(self._外部.cleanup)

    def _锁树(self) -> Path:
        """把夹具根变成「已锁树」：文件与目录都上锁（与 `上锁全仓` 同口径）。"""
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        锁.上锁全仓(self.根)
        self.assertEqual(0, 锁.查询(self.根)["未锁数"], "前置：夹具根应已全锁")
        return self.根

    def test_复制进锁树副本要上锁(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 复制文件
        外部源 = self.外部 / "未锁源.txt"
        外部源.write_text("外来的\n", encoding="utf-8")
        锁树 = self._锁树()
        落点 = 锁树 / "复制进来.txt"
        结果对象 = 复制文件(str(外部源), str(落点))
        self.assertTrue(结果对象.成功, f"复制被挡：{结果对象.错误码} {结果对象.错误说明}")
        self.assertTrue(锁.是锁着的(落点),
                        "★ 复制进锁树的副本没上锁 —— 锁树里凭空多一个洞（洞 ④）")

    def test_复制出仓库副本要解锁(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 复制文件
        锁树 = self._锁树()
        落点 = self.外部 / "搬出去.txt"
        结果对象 = 复制文件(str(self.文件), str(落点))
        self.assertTrue(结果对象.成功, f"复制被挡：{结果对象.错误码}")
        self.assertFalse(锁.是锁着的(落点),
                         "★ 仓库外的副本带着一把解不开的锁 —— `copy2` 会把 `st_flags` 一起复制，"
                         "「复制到临时区再改」的既有流程会被内核拒")
        # 真改一次，证明「可写」不是靠 flags 读数的推断
        落点.write_text("改过了\n", encoding="utf-8")

    def test_锁树里建目录要上锁(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 创建目录
        锁树 = self._锁树()
        新目录 = 锁树 / "新目录"
        结果对象 = 创建目录(str(新目录))
        self.assertTrue(结果对象.成功, f"建目录被挡：{结果对象.错误码} {结果对象.错误说明}")
        self.assertTrue(锁.是锁着的(新目录),
                        "★ 锁树里新建的目录没上锁 —— 那是「锁树里的一块未锁区域」")

    def test_多层新建目录写入要成功且逐层上锁(self) -> None:
        """写入的落点在**两层新目录**里时：`mkdir(parents=True)` 要逐层在**已锁的父目录**
        里加条目 —— 解锁窗口必须走到「第一个已存在的祖先」，否则第一步就被拒。"""
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 写入文件
        锁树 = self._锁树()
        深 = 锁树 / "一层" / "两层" / "落点.md"
        结果对象 = 写入文件(str(深), "深写\n")
        self.assertTrue(结果对象.成功,
                        f"多层新建写入被挡（解锁窗口没走到已存在祖先）："
                        f"{结果对象.错误码} {结果对象.错误说明}")
        self.assertEqual("深写\n", 深.read_text(encoding="utf-8"))
        self.assertTrue(锁.是锁着的(深), "★ 深层的落点没上锁")
        self.assertTrue(锁.是锁着的(深.parent), "★ 中间新建的目录没上锁（继承要**传递**到最近已存在祖先）")
        self.assertTrue(锁.是锁着的(深.parent.parent), "★ 第一层新建的目录没上锁")

    def test_移动进锁树要上锁(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 移动文件
        外部源 = self.外部 / "待搬入.txt"
        外部源.write_text("搬进来的\n", encoding="utf-8")
        锁树 = self._锁树()
        落点 = 锁树 / "搬进来.txt"
        结果对象 = 移动文件(str(外部源), str(落点))
        self.assertTrue(结果对象.成功, f"移动被挡：{结果对象.错误码} {结果对象.错误说明}")
        self.assertTrue(锁.是锁着的(落点),
                        "★ 搬进锁树的条目没上锁 —— 移动腿与复制腿同族，必须一起对齐")

    def test_压缩产物要上锁(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统补充 import 压缩文件
        成员 = self.根 / "成员.txt"
        成员.write_text("内容\n", encoding="utf-8")
        锁树 = self._锁树()
        成品 = 锁树 / "成品.zip"
        结果对象 = 压缩文件(str(成员), str(成品))
        self.assertTrue(结果对象.成功, f"压缩被挡：{结果对象.错误码} {结果对象.错误说明}")
        self.assertTrue(锁.是锁着的(成品),
                        "★ `os.replace` 会把临时件的未锁状态带到成品上（洞 ④）")

    def test_对齐目标锁态单元行为(self) -> None:
        """判据本体：父目录锁着 ⇒ 目标（含整棵子树）都锁；父目录没锁 ⇒ 都解开。"""
        子 = self.根 / "子目录"
        子.mkdir()
        (子 / "里面.txt").write_text("x\n", encoding="utf-8")
        锁.上锁(self.根)
        改动 = 锁.对齐目标锁态(子)
        self.assertGreaterEqual(改动, 2, "父目录锁着时，子树应被整体锁上")
        self.assertTrue(锁.是锁着的(子) and 锁.是锁着的(子 / "里面.txt"))
        # 反向：父目录没锁 ⇒ 子树解开（不把锁带出仓库）
        锁.解锁(self.根)
        锁.对齐目标锁态(子)
        self.assertFalse(锁.是锁着的(子 / "里面.txt"), "父目录没锁时不该保留锁")
        # 仓库根/不存在的路径：不炸、如实返回 0
        self.assertEqual(0, 锁.对齐目标锁态(self.根 / "不存在的东西"))


class Test复核八处窗口缺口(锁夹具):
    """2026-09-23 复核（独立子代理逐腿审五条腿）抓出的**八处**「窗口位置错了」的缺口。

    共同形状：**动作本身是对的，但它在解锁窗口之外执行** —— 于是内核拒，而错误又被
    `忽略失败=真` / `contextlib.suppress` / `except OSError: continue` 吞掉 ⇒
    **静默留残或静默失效**（比报错难查得多）。

    每条都真跑（看现场实物与 flags，不看返回值），且每条都做过反向验证。
    ① 对齐目标锁态：目标为既有目录时剥掉整树锁（含仓库根⇒全仓）
    ② 递归候选未排豁免区：目标为仓库根时把 `.git`/`工程缓存` 全上锁
    ③ 临时解锁树未走祖辈链：多层新建在已锁祖父处被拒
    ④ 压缩：备份目录清理排在窗口外 ⇒ 锁树里永久留一个未锁目录
    ⑤ 解压：失败回滚整段排在窗口外 ⇒ 静默空转
    ⑥ 解压：备份盘「随用随删」排在窗口外 ⇒ 永久留已锁备份目录
    ⑦ 解压：目标根 mkdir 排在窗口外 ⇒ 目标目录不存在时恒失败
    ⑧ 写入流水：凭据落盘未开窗口 ⇒ **凭据静默不落盘**（编译口把工具写的 md 判成手写）
    """

    def _写腿环境(self):
        旧值 = os.environ.get("系统平台_修MCP自身")
        os.environ["系统平台_修MCP自身"] = "1"
        self.addCleanup(lambda: (os.environ.__setitem__("系统平台_修MCP自身", 旧值)
                              if 旧值 is not None
                              else os.environ.pop("系统平台_修MCP自身", None)))

    def setUp(self) -> None:
        super().setUp()
        self._写腿环境()
        self._外部 = tempfile.TemporaryDirectory(prefix="锁外区_")
        self.外部 = Path(self._外部.name)
        self.addCleanup(self._外部.cleanup)

    def _锁树(self) -> Path:
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        锁.上锁全仓(self.根)
        self.assertEqual(0, 锁.查询(self.根)["未锁数"], "前置：夹具根应已全锁")
        return self.根

    def _造压缩包(self, 成员表: dict) -> Path:
        import zipfile
        源 = self.外部 / "包.zip"
        with zipfile.ZipFile(源, "w") as 包:
            for 名, 内容 in 成员表.items():
                包.writestr(名, 内容)
        return 源

    # ① ——————————————————————————————————————————————
    def test_对齐既有锁目录不得剥掉整树锁(self) -> None:
        子 = self.根 / "既有子目录"
        子.mkdir()
        (子 / "里面.txt").write_text("x\n", encoding="utf-8")
        self._锁树()
        self.assertTrue(锁.是锁着的(子), "前置：既有目录应已上锁")
        改动 = 锁.对齐目标锁态(子)
        self.assertEqual(0, 改动,
                         "★ 目标本身就是既有锁目录时，参照锁态不能再往上看它的父目录"
                         "（父目录在受管面外、恒判未锁）⇒ 子树里原有的锁被逐条剥掉")
        self.assertTrue(锁.是锁着的(子) and 锁.是锁着的(子 / "里面.txt"))

    def test_对齐仓库根不得剥掉全仓锁(self) -> None:
        锁树 = self._锁树()
        锁.对齐目标锁态(锁树)
        self.assertEqual(0, 锁.查询(锁树)["未锁数"],
                         "★ `复制文件/移动文件(源, 目标路径=<既有目录>)` 与"
                         " `解压文件(源包, 目标目录=<既有目录>)` 三条调用都能把仓库根当目标；"
                         "参照取父目录时，一次调用就把全仓锁剥光")

    # ② ——————————————————————————————————————————————
    def test_递归候选必须排豁免区(self) -> None:
        """目标为仓库根时，`.git/` 与 `工程缓存/` 不能因「参照锁着」而被递归上锁。"""
        缓存 = self.根 / "工程缓存" / "运行数据"
        缓存.mkdir(parents=True)
        缓存文件 = 缓存 / "制品.bin"
        缓存文件.write_text("x", encoding="utf-8")
        锁树 = self._锁树()
        self.assertFalse(锁.是锁着的(缓存文件), "前置：豁免区不上锁")
        锁.对齐目标锁态(锁树)
        self.assertFalse(锁.是锁着的(缓存文件),
                         "★ 递归候选没排豁免区 ⇒ 一次对齐就把制品树锁死"
                         "（网关与构建双双写不了）")

    # ③ ——————————————————————————————————————————————
    def test_临时解锁树覆盖多层新建(self) -> None:
        # ★ 落点表达式必须**静态可解析**：`开发工具/测试写入边界门禁.py` 沿赋值链回溯左端基，
        #   `深 = 锁树 / …`（锁树来自 `self._锁树()` 函数返回值）会断链 ⇒ fail-closed 计违规。
        #   故这里只把 `self._锁树()` 当**前置动作**调一次，落点仍从 `self.根` 拼。
        self._锁树()
        深 = self.根 / "甲" / "乙" / "丙"
        with 锁.临时解锁树(深):
            try:
                深.mkdir(parents=True)
            except OSError as 错误:
                self.fail(f"★ 临时解锁树只解锁直接父目录 ⇒ 多层新建在已锁祖父处被拒：{错误}")
        self.assertTrue(深.is_dir())

    # ④ ——————————————————————————————————————————————
    def test_压缩覆盖既有目标不留未锁残留(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统补充 import 压缩文件
        成员 = self.根 / "成员.txt"
        成员.write_text("内容\n", encoding="utf-8")
        成品 = self.根 / "成品.zip"
        成品.write_text("旧内容\n", encoding="utf-8")   # 既有目标 ⇒ 走备份分支
        锁树 = self._锁树()
        结果对象 = 压缩文件(str(成员), str(成品))
        self.assertTrue(结果对象.成功, f"压缩被挡：{结果对象.错误码} {结果对象.错误说明}")
        残留 = sorted(p.name for p in 锁树.iterdir() if p.name.startswith(".__压缩备份_"))
        self.assertEqual([], 残留,
                         "★ 备份目录的清理排在解锁窗口之外 ⇒ rmtree 被内核拒、"
                         "又被 `忽略失败=真` 吞掉 ⇒ 锁树里永久留一个**未锁**目录"
                         "（可在其中凭空新建条目）")
        self.assertEqual(0, 锁.查询(锁树)["未锁数"], "★ 清理腿在窗口外 ⇒ 留未锁条目")
        self.assertTrue(锁.是锁着的(成品))

    # ⑤ ——————————————————————————————————————————————
    def test_解压失败回滚不留未锁残留(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统补充 import 解压文件
        # 首个成员写得进去，第二个成员的父路径被一个**文件**占着 ⇒ 落盘中途抛错
        源 = self._造压缩包({"首个.txt": "y", "a/b.txt": "z"})
        目标根 = self.根 / "解压到"
        目标根.mkdir()
        (目标根 / "a").write_text("挡路的文件\n", encoding="utf-8")
        锁树 = self._锁树()
        结果对象 = 解压文件(str(源), str(目标根))
        self.assertFalse(结果对象.成功, "前置：应因落盘中途出错而失败")
        self.assertFalse((目标根 / "首个.txt").exists(),
                         "★ 回滚整段排在解锁窗口之外 ⇒ unlink/rmdir 被内核拒、"
                         "又被 `except OSError: continue` 吞掉 ⇒ 静默空转，"
                         "本次新建的文件留在锁树里")
        self.assertEqual(0, 锁.查询(锁树)["未锁数"], "★ 回滚没清干净 ⇒ 锁树里留未锁条目")

    # ⑥ ——————————————————————————————————————————————
    def test_解压成功不留备份目录(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统补充 import 解压文件
        源 = self._造压缩包({"覆盖我.txt": "新内容\n"})
        目标根 = self.根 / "解压到"
        目标根.mkdir()
        (目标根 / "覆盖我.txt").write_text("旧内容\n", encoding="utf-8")
        锁树 = self._锁树()
        结果对象 = 解压文件(str(源), str(目标根))
        self.assertTrue(结果对象.成功, f"解压被挡：{结果对象.错误码} {结果对象.错误说明}")
        self.assertEqual("新内容\n", (目标根 / "覆盖我.txt").read_text(encoding="utf-8"))
        残留 = sorted(p.name for p in 目标根.iterdir() if p.name.startswith(".__解压备份_"))
        self.assertEqual([], 残留,
                         "★ 备份盘「随用随删」排在解锁窗口之外 ⇒ 它已被递归锁上 ⇒"
                         " rmtree 被拒 + `忽略失败=真` ⇒ 每次覆盖式解压都永久留下一个"
                         "已锁的 `.__解压备份_*`（内含调用方原件的完整副本）")
        self.assertEqual(0, 锁.查询(锁树)["未锁数"])

    # ⑦ ——————————————————————————————————————————————
    def test_解压到不存在的目标根在锁树里能建(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统补充 import 解压文件
        源 = self._造压缩包({"甲.txt": "内容\n"})
        锁树 = self._锁树()
        目标根 = 锁树 / "新目标目录"
        结果对象 = 解压文件(str(源), str(目标根))
        self.assertTrue(结果对象.成功,
                        f"★ 目标根的 mkdir 排在解锁窗口之外 ⇒ 在已锁父目录里建目录"
                        f"被内核拒：{结果对象.错误码} {结果对象.错误说明}")
        self.assertTrue((目标根 / "甲.txt").is_file())
        self.assertTrue(锁.是锁着的(目标根 / "甲.txt"), "★ 解压产物没对齐锁态")
        self.assertEqual(0, 锁.查询(锁树)["未锁数"])

    # ⑧ ——————————————————————————————————————————————
    def test_记一次写入在锁态下落盘(self) -> None:
        from 公共契约.诊断 import 写入流水
        写入流水.记一次写入(self.根, "预置.md", "预置\n")   # 先建出流水文件
        锁树 = self._锁树()
        流水 = 写入流水.流水路径(锁树)
        self.assertTrue(锁.是锁着的(流水), "前置：流水文件是受管条目，应已上锁")
        写入流水.记一次写入(锁树, "开发文档/未完成事项.md", "工具写的内容\n")
        self.assertTrue(
            写入流水.有写入凭据(锁树, "开发文档/未完成事项.md", "工具写的内容\n"),
            "★ 流水文件自己上了锁 ⇒ 不开窗口时 mkdir/open(a) 被内核拒，"
            "而两个调用方都 `except Exception` 静默兜底 ⇒ **凭据一声不响地不落盘**，"
            "编译口随即把「工具刚写的 md」判成「手写」（2026-09-23 实测真身）")

    # 豁免边界（与②同源，单独一条单元判据）————————————————
    def test_上下文锁态遇豁免前缀即停(self) -> None:
        缓存 = self.根 / "工程缓存" / "运行数据"
        缓存.mkdir(parents=True)
        self._锁树()
        self.assertFalse(锁.是锁着的(缓存), "前置：豁免区不上锁")
        锁.对齐目标锁态(缓存)
        self.assertFalse(锁.是锁着的(缓存),
                         "★ 豁免区的祖辈（仓库根）锁着也不能把锁带进去 ——"
                         "否则制品树被锁，网关与构建双双瘫痪")


def _写半截后抛(*实参, **关键字) -> None:
    """伪装 `shutil.copy2` / `shutil.move`：**先写出半截字节、再抛 `OSError`**（ENOSPC / EINTR 的真实形状）。

    为什么写半截走**子进程**（与本文件 `Test内核真的拒写` 同一姿势）：本进程内直调
    `open(目标, "wb")` 会往本文件写进一处「左端基解析不出」的写动作（目标是替身的形参名），
    被 `开发工具/测试写入边界门禁` 按 fail-closed 计入违规；`sh -c` 的重定向不在该门禁的
    写动作面内，且更忠实于「写动作发生在另一个进程里」这一事实。
    """
    subprocess.run(["sh", "-c", f"printf '半截' > {实参[-1]}"], check=True, capture_output=True)
    raise OSError(28, "No space left on device（伪装：写半截后失败）")


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test失败路径落点也要对齐锁态(锁夹具):
    """⑨ **洞 ⑤**：`复制文件` / `移动文件` 在**窗口内写半截后抛错**时，落点也要对齐锁态。

    形状（2026-09-23 复核）：`shutil.copy2` / 移动腿写了一半就抛（ENOSPC / EINTR）——
    落点**已经存在**，但它**进入窗口时不存在** ⇒ 不在 `临时解锁树` 的「原状态」表里
    ⇒ 窗口 `finally` 只重锁「进入时确实锁着的」条目 ⇒ **锁树里留下一个未锁的半截文件**
    （可在其中凭空新建/改写内容；`查询()` 的未锁数由 0 变 1）。

    为什么必须**真造出失败**：成功路径上的「对齐」是既有行为，漏了失败路径也全绿 ——
    只有失败路径能把这处漏对齐照出来。故本类用 `unittest.mock.patch` 把落盘点
    `shutil.copy2` / `shutil.move`（实现腿真正调用的那两个函数）换成
    「先写出半截字节、再抛 `OSError`」的替身 `_写半截后抛`：不动实现代码、不动环境变量，
    patch 面就是那两个库函数。

    判据两条缺一不可：① 失败**如实返回**（不把失败伪装成成功）；
    ② 现场**没有未锁的半截文件**（`锁.查询(树)["未锁数"] == 0`）。
    """

    def _写腿环境(self):
        旧值 = os.environ.get("系统平台_修MCP自身")
        os.environ["系统平台_修MCP自身"] = "1"
        self.addCleanup(lambda: (os.environ.__setitem__("系统平台_修MCP自身", 旧值)
                              if 旧值 is not None
                              else os.environ.pop("系统平台_修MCP自身", None)))

    def setUp(self) -> None:
        super().setUp()
        self._写腿环境()
        self._外部 = tempfile.TemporaryDirectory(prefix="锁外区_")
        self.外部 = Path(self._外部.name)
        self.addCleanup(self._外部.cleanup)

    def _锁树(self) -> Path:
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        锁.上锁全仓(self.根)
        self.assertEqual(0, 锁.查询(self.根)["未锁数"], "前置：夹具根应已全锁")
        return self.根

    def test_复制失败半截落点也必须上锁(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 复制文件
        源 = self.根 / "复制源.txt"
        源.write_text("源内容\n", encoding="utf-8")
        self._锁树()
        落点 = self.根 / "复制半截.txt"
        # `autospec=True` + `side_effect`（不用 `new=`）：本仓 `开发工具/测试伪装门禁.py`
        # 规则 2 要求一律 autospec（存量上限 213 只降不升，裸桩会把它顶上去）；
        # 且 autospec 后桩的签名与真 `shutil.copy2` 一致，「传错参数」也会被抛出来。
        with mock.patch("shutil.copy2", autospec=True, side_effect=_写半截后抛):
            结果对象 = 复制文件(str(源), str(落点))
        self.assertFalse(结果对象.成功, "★ 写半截抛错被伪装成了成功")
        self.assertEqual("文件复制失败", 结果对象.错误码,
                         f"失败如实返回的判据：{结果对象.错误说明}")
        self.assertTrue(落点.exists(),
                        "前置：替身应先写出半截落点（否则本用例没造出现场，判据空转）")
        self.assertEqual(0, 锁.查询(self.根)["未锁数"],
                         "★ 半截落点没对齐锁态 —— 它进入窗口时不存在，不在「原状态」表里，"
                         "窗口 finally 不会锁它 ⇒ 锁树里留一个未锁的半截文件（洞 ⑤）")

    def test_移动失败半截落点也必须上锁(self) -> None:
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 移动文件
        源 = self.外部 / "待搬入.txt"
        源.write_text("搬进来的\n", encoding="utf-8")
        self._锁树()
        落点 = self.根 / "搬入半截.txt"
        with mock.patch("shutil.move", autospec=True, side_effect=_写半截后抛):
            结果对象 = 移动文件(str(源), str(落点))
        self.assertFalse(结果对象.成功, "★ 写半截抛错被伪装成了成功")
        self.assertEqual("文件移动失败", 结果对象.错误码,
                         f"失败如实返回的判据：{结果对象.错误说明}")
        self.assertTrue(落点.exists(),
                        "前置：替身应先写出半截落点（否则本用例没造出现场，判据空转）")
        self.assertEqual(0, 锁.查询(self.根)["未锁数"],
                         "★ 半截落点没对齐锁态 —— 移动腿与复制腿同族，必须一起对齐（洞 ⑤）")

    def test_失败在建出中间层后中间层也必须上锁(self) -> None:
        """**第三形态**（2026-09-23 子代理真跑抓出）：`mkdir(parents=True)` 建出中间层
        之后、落点本身还没写出来时就抛错 —— 落点**不存在**。

        旧实现开头就 `if not 路径.exists(): return 0` 早退 ⇒ 那几层**刚建的中间目录**
        永久留在未锁态（可在其中凭空新建条目）。修法：目标不存在时不再早退，
        `_上下文锁态` 自动退化为「沿祖辈链找最近一个锁着的祖先」，祖辈链循环把
        刚建的中间层补进对齐候选。
        """
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import 复制文件
        源 = self.根 / "复制源.txt"
        源.write_text("源内容\n", encoding="utf-8")
        self._锁树()
        落点 = self.根 / "中间一" / "中间二" / "落点.txt"
        with mock.patch("shutil.copy2", autospec=True, side_effect=_不写就抛):
            结果对象 = 复制文件(str(源), str(落点))
        self.assertFalse(结果对象.成功, "前置：应因落盘失败而失败")
        self.assertTrue((self.根 / "中间一").is_dir(),
                        "前置：中间层应已建出（否则本用例没造出现场，判据空转）")
        self.assertTrue((self.根 / "中间一" / "中间二").is_dir(),
                        "前置：第二层中间目录也应已建出（它嵌在 中间一 里，不在根下）")
        self.assertFalse(落点.exists(), "前置：落点不该存在")
        self.assertEqual(0, 锁.查询(self.根)["未锁数"],
                         "★ 落点不存在时早退 return 0 ⇒ 刚建的中间目录永久留在未锁态；"
                         "同形状的还有 压缩文件/解压文件 等所有「先建目录后落盘」的腿")
        self.assertTrue(锁.是锁着的(self.根 / "中间一" / "中间二"),
                        "★ 第二层中间目录也必须锁上（它不在 查询() 的扫描面里，必须直读 flags）")


def _不写就抛(*实参, **关键字) -> None:
    """伪装写动作：**一个字节都不写**就抛 `OSError`。

    专用于照出「中间层已建出、落点还不存在」这一形态 —— 若替身先写半截，落点就存在了，
    那跑的是上面 `_写半截后抛` 那一条现场，照不出早退这一处。
    """
    raise OSError(28, "No space left on device（伪装：中间层建完就失败）")


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test解锁只认网关凭证(锁夹具):
    """⑦（行为层）解锁这条腿的**身份门槛**：只认网关凭证。

    2026-09-23 华哥裁决：

    > 「开工 ID 登记的时候解锁……提交之后就上锁回去……
    >   **只有 mcp 才能解锁，禁止用其他方式解锁。**」

    **为什么必须有反向样本**：本类里「有凭证放行」那两条是**正向样本** —— 把门槛整段
    删掉它们照样绿；只有「无凭证被拒」这两条会红。少了反向样本，门槛被删（或被人顺手
    改成「也认白名单」）时本文件会**全绿**，而整仓锁其实已经能一行命令解开
    —— 那正是「测试在替缺陷作证」。

    判据落在**行为**上（真调一次解锁 + 读 flags / 查询读数），不只看函数在不在：
    门槛属「删掉即全绿」的那一类判据，反向样本是它唯一的守卫。
    """

    def test_无凭证解锁被拒(self) -> None:
        self._设凭证(None)                      # 摘掉网关凭证 ⇒ 装成终端直跑
        锁.上锁(self.文件)
        self.assertTrue(锁.是锁着的(self.文件), "前置：应已上锁")
        with self.assertRaises(PermissionError, msg="无凭证竟然解开了锁"):
            锁.解锁(self.文件)
        self.assertTrue(锁.是锁着的(self.文件),
                        "★ 抛了错但锁却被解开了 —— 门槛必须抛在动手之前")

    def test_修MCP白名单前缀也不能解锁(self) -> None:
        """**关键反向样本**：`系统平台_修MCP自身=1` 是「修 MCP 自身」的万能后路，
        `MCP身份准入()` 认它 —— 但**解锁这条腿不认**（华哥裁决「禁止用其他方式解锁」）。

        为什么这条必须单独成立：白名单只是一个**环境变量前缀**（`env 系统平台_修MCP自身=1
        …` 就能带上）。解锁若认它，门槛等于没设 —— 任何人加一个前缀就能一行命令解开整仓锁。
        而写文件那条腿仍必须保留白名单（后路不能断），故两条腿判据不同是**有意的**，
        本用例就是这条「有意不同」的守卫：把 `_要求网关凭证` 改成转调 `MCP身份准入()`
        （或往白名单上开一道口）时，这条会红。
        """
        self._设凭证(None)
        旧值 = os.environ.get("系统平台_修MCP自身")
        os.environ["系统平台_修MCP自身"] = "1"
        self.addCleanup(lambda: (os.environ.__setitem__("系统平台_修MCP自身", 旧值)
                              if 旧值 is not None
                              else os.environ.pop("系统平台_修MCP自身", None)))
        锁.上锁(self.文件)
        with self.assertRaises(PermissionError,
                               msg="白名单竟然能解锁 —— 加一个环境变量前缀就能解全仓"):
            锁.解锁(self.文件)
        self.assertTrue(锁.是锁着的(self.文件), "★ 白名单这条路径上锁被解开了")

    def test_解锁全仓无凭证被拒(self) -> None:
        self._设凭证(None)
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        锁.上锁全仓(self.根)
        self.assertEqual(0, 锁.查询(self.根)["未锁数"], "前置：夹具根应已全锁")
        with self.assertRaises(PermissionError,
                               msg="无凭证竟然能解全仓（`--下锁` 一行命令那个缺口）"):
            锁.解锁全仓(self.根)
        self.assertEqual(0, 锁.查询(self.根)["未锁数"],
                         "★ 抛了错但全仓锁已被解开 —— 门槛必须抛在动手之前")

    def test_有凭证时解锁放行(self) -> None:
        """正向样本：**经 MCP 来的**（网关带凭证）必须能解锁 —— 否则门槛会变成一堵墙。"""
        锁.上锁(self.文件)
        self.assertTrue(锁.是锁着的(self.文件), "前置：应已上锁")
        锁.解锁(self.文件)
        self.assertFalse(锁.是锁着的(self.文件), "有凭证却被门槛挡住了")

    def test_有凭证时解锁全仓放行(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        锁.上锁全仓(self.根)
        self.assertGreaterEqual(锁.查询(self.根)["已锁数"], 2, "前置：扫描面太小")
        锁.解锁全仓(self.根)
        self.assertEqual(0, 锁.查询(self.根)["已锁数"], "有凭证却解不开全仓")

    def test_临时解锁不受门槛影响(self) -> None:
        """**写腿的瞬时窗口不许被门槛一起锁死**：`临时解锁()` / `临时解锁树()` 是平台
        自己落盘用的（写腿靠它们穿过锁）—— 它们若也认凭证，无凭证时平台连一个字节都写不进。
        """
        self._设凭证(None)
        锁.上锁(self.文件)
        with 锁.临时解锁(self.文件):
            self.文件.write_text("改过了\n", encoding="utf-8")
        self.assertEqual("改过了\n", self.文件.read_text(encoding="utf-8"),
                         "临时解锁窗口内写不进 —— 写腿会被门槛一起锁死")
        self.assertTrue(锁.是锁着的(self.文件),
                        "★ 临时解锁窗口退出后没恢复锁（写腿的窗口必须自还原）")


@unittest.skipUnless(锁.支持内核锁(), "本平台不支持内核级只读锁（仅 macOS）")
class Test租约解锁与回锁(锁夹具):
    """租约驱动的两条腿：**开工登记时解锁 / 提交（释放、过期回收）后上锁回去**。

    华哥 2026-09-23 裁决：「开工 ID 登记的时候解锁……提交之后就上锁回去。就完事了。」
    `解锁供写入` 与 `回锁` 是这条链路上**唯一**的两个动作。

    判据取**可写性**（真建一次文件、真写一次），不看返回值 —— `解锁供写入` 初版
    把循环条件写成「当前祖先还锁着」，而待建路径的父目录**往往也不存在**
    （`_取标志` 对不存在的路径回 0）⇒ 一个祖先都没放开、`mkdir` 照旧被内核拒，
    **返回值却看不出任何异常**。这就是「判据不能只看返回值」的又一例。
    """

    def _锁树(self) -> Path:
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        锁.上锁全仓(self.根)
        self.assertEqual(0, 锁.查询(self.根)["未锁数"], "前置：夹具根应已全锁")
        return self.根

    def test_解锁供写入要放开到第一个已存在祖先(self) -> None:
        """待建路径（父目录也不存在）认领后必须**真能建出来** —— 只解目标本身不够。

        路径一律从 `self.根` 拼（不接 `_锁树()` 的返回值）：`测试写入边界门禁` 对
        「写动作的目标表达式静态解析不出左端基」是 fail-closed 计违规的，接函数
        返回值会把它变成新增违规（正确修法是改测试写法，不是扩基线）。
        """
        self._锁树()
        新目录 = self.根 / "新目录"
        待建 = 新目录 / "新文件.md"
        锁.解锁供写入(待建)
        self.assertFalse(锁.是锁着的(self.根),
                         "待建路径的父链没被放开 ⇒ 新建动作会被内核拒（初版 bug）")
        新目录.mkdir(parents=True, exist_ok=True)
        待建.write_text("建出来了\n", encoding="utf-8")
        self.assertEqual("建出来了\n", 待建.read_text(encoding="utf-8"))

    def test_回锁默认不动父目录_连父链才收回(self) -> None:
        """默认只锁路径本身（父目录共享，别的活跃租约还要用）；`连父链=真` 才收回父目录。

        为什么必须有 `连父链` 这一支：认领时为了「新建文件」必然放开了父目录，
        释放时不收回 ⇒ 整仓锁逐次退化成「只有文件锁着、目录全开着」，而目录开着
        就能凭空新增条目（本锁要挡的最典型漂移路径）。
        """
        锁树 = self._锁树()
        self.assertIs(锁树, self.根)
        子目录 = self.根 / "子目录"
        待建 = 子目录 / "文件.md"
        锁.解锁供写入(待建)
        子目录.mkdir(parents=True, exist_ok=True)
        待建.write_text("x\n", encoding="utf-8")
        锁.回锁(待建)
        self.assertTrue(锁.是锁着的(待建))
        self.assertFalse(锁.是锁着的(子目录),
                         "默认不该动父目录 —— 顺手锁上会掐掉同目录下别人的开工窗口")
        锁.回锁(待建, 连父链=True)
        self.assertTrue(锁.是锁着的(子目录), "连父链=真 必须把父目录收回")
    def test_多级新建后释放要把整条链收回(self) -> None:
        """认领 `a/新目录/新文件.md`（`新目录` 当时不存在）⇒ 释放后 **`a` 也必须回到锁态**。

        ★ 这条是子代理真跑抓出来的（本函数初版只锁「目标 + 直接父目录」）：
        `解锁供写入` 放开的是「一路到第一个**已存在**祖先」整条链，而链长会随新建变化
        —— 建完 `新目录` 之后，直接父目录已经不是当初放开的终点了 ⇒ `a` 被永久留开
        （子代理实测 `未锁数=1`）。修法 = 「向上收到第一个本来就锁着的祖先为止」。
        """
        甲 = self.根 / "a"
        甲.mkdir(exist_ok=True)
        self._锁树()
        self.assertTrue(锁.是锁着的(甲), "前置：`a` 应在扫描面内且已锁")
        新目录 = 甲 / "新目录"
        待建 = 新目录 / "新文件.md"
        锁.解锁供写入(待建)
        self.assertFalse(锁.是锁着的(甲), "认领时为了新建，`a` 必然被放开")
        新目录.mkdir(parents=True, exist_ok=True)
        待建.write_text("x\n", encoding="utf-8")
        锁.回锁(待建, 连父链=True)
        self.assertTrue(锁.是锁着的(待建))
        self.assertTrue(锁.是锁着的(新目录), "新建的中间层没锁回去")
        self.assertTrue(锁.是锁着的(甲), "★ 链上更上一层的 `a` 被永久留开（初版 bug）")
        self.assertEqual(0, 锁.查询(self.根)["未锁数"], "整树必须回到未锁数 0")

    def test_收父链绝不出仓库(self) -> None:
        """`连父链=真` 的边界 = 「第一个本来就锁着的祖先」或 **仓库根（含）**，绝不出仓库。

        为什么必须有这一条：收链的规则是「向上收到锁着的为止」，若不加仓库根这道界，
        在「整仓开着」的情形下会一路锁到 `/`（把仓库外的任人目录锁掉）。
        判据 = 仓库根被收回，而**仓库根的上层（外面）没被动过**。
        """
        subprocess.run(["git", "init", "-q"], cwd=self.根, check=False, capture_output=True)
        锁.上锁全仓(self.根)
        锁.解锁全仓(self.根)
        外面 = self.根.parent
        外面原本锁着 = 锁.是锁着的(外面)
        待建 = self.根 / "文件.md"
        待建.write_text("x\n", encoding="utf-8")
        锁.回锁(待建, 连父链=True)
        self.assertTrue(锁.是锁着的(self.根), "整仓开着时，收链应收到仓库根为止")
        self.assertEqual(外面原本锁着, 锁.是锁着的(外面),
                         "★ 收链跑出仓库了（把仓库外的任人目录锁掉）")


if __name__ == "__main__":
    unittest.main()
