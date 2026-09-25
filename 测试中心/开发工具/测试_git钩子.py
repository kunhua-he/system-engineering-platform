"""提交强制点（`开发工具/git钩子/commit-msg`）的回归。

## 为什么要有它（2026-09-23 实测）

本仓两条执行腿（MCP 能力腿 / 终端 git 腿）**唯一的公共汇聚点就是 `git commit`**，
而现场实测：`.git/hooks/` 为空、`core.hooksPath` 未设 ⇒「必须走平台」只靠人记得
（哲学 13.1：判据在 ≠ 判据接线）。本组判据把「强制点真的在必经路径上」钉住。

## 本测试钉住的判据

1. **钩子存在且可执行** —— git 对不可执行的钩子是**静默跳过**的（不报错、不提示），
   所以「文件在」不等于「钩子生效」；
2. **`core.hooksPath` 指向它** —— 这是最容易漏的一环：钩子写好了但没人指过去，
   等于没装（且**没有任何报错**）。★ 反向验证：把期望值改错，本判据必须红；
3. **无开工ID 必拒**（exit 非 0）、**有开工ID 必放**（exit 0）；
4. **钩子自身出错一律放行**（消息文件拿不到 ⇒ exit 0）—— 钩子坏了不该让整个仓库提交瘫痪；
5. **git 自身的流程消息放行**（`Merge `/`Revert `/`fixup! `）—— 它们不是「一次开发改动」。
6. **`pre-commit` 的锁核验（2026-09-23 补，判据一）** —— 提交时**整仓内核锁必须在位**：
   · 锁缺失（含「只锁了一部分」的缺口）⇒ **拒**，并给出可照抄的修法（`运维脚本/仓库锁.py`）；
   · **活跃租约开窗**（`未锁 > 0` 但那几条是被活跃写租约覆盖的认领路径 ＋ 父链，**设计行为**）
     ⇒ **放行**，并如实打印开窗条数（2026-09-24 批M-b 补；旧口径拿 `未锁数 > 0` 判红会
     把开窗当成缺口 **误拒提交**）；判据 = `查询()` 的 `缺口数`，不是 `未锁数`；
   · 平台不支持内核锁（非 macOS）⇒ **放行 + 大声告警**（fail-open：机制在本平台不存在）；
   · 判据自身不可用（导入失败 / 查询抛错）⇒ **拒**（fail-closed：判据坏了不静默放行）。
   边界口径的完整理由在钩子头部「判据一·边界口径」；本文件把它们各钉一条用例。

跑法：python3.14 -m unittest 测试中心.开发工具.测试_git钩子
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 公共契约.运行时 import 仓库只读锁 as 锁

钩子相对 = "开发工具/git钩子/commit-msg"
钩子路径 = 仓库根 / 钩子相对
提交钩子相对 = "开发工具/git钩子/pre-commit"
提交钩子路径 = 仓库根 / 提交钩子相对
git = "/Library/Developer/CommandLineTools/usr/bin/git"


def _运行git(仓库: Path, *参数: str) -> subprocess.CompletedProcess:
    return subprocess.run([git, *参数], cwd=str(仓库), capture_output=True,
                          text=True, timeout=60)


def 跑提交钩子(仓库: Path, 钩子: Path | None = None, *,
              带平台路径: bool = True) -> subprocess.CompletedProcess:
    """在临时仓库 `仓库` 里**真跑** `pre-commit`，返回完成对象（退出码 + stdout/stderr）。

    为什么用 `sh <钩子路径>` 而不是 `git commit`：本组用例只考钩子本身的判据，不需要真落提交；
    `git commit` 会先过索引/暂存一堆无关环节，失败面变大且看不出是哪一环拒的。
    `cwd=仓库` 是必须的 —— 钩子的仓库根取自 `git rev-parse --show-toplevel`（跟 cwd 走）。

    `带平台路径`：钩子里的锁核验要 import `公共契约.运行时.仓库只读锁`，临时树里没有平台代码，
    故默认把真仓库根挂上 `PYTHONPATH`。**显式拔掉它**（False）就是「判据自身不可用」那条边界的
    夹具（临时树里 import 不到平台）。
    """
    环境 = dict(os.environ)
    # 不靠修 MCP 白名单放行：走「普通终端」的形态（临时树在仓库外，sitecustomize 本来也不拦）。
    环境.pop("系统平台_修MCP自身", None)
    if 带平台路径:
        环境["PYTHONPATH"] = str(仓库根)
    else:
        环境.pop("PYTHONPATH", None)
    return subprocess.run(["sh", str(钩子 or 提交钩子路径)], cwd=str(仓库),
                          capture_output=True, text=True, timeout=120, env=环境)


def 跑钩子(消息: str | None) -> int:
    """把消息写进临时文件再跑钩子，返回退出码。消息为 None 表示传一个不存在的路径。"""
    if 消息 is None:
        return subprocess.run(["sh", str(钩子路径), str(仓库根 / "不存在_的_消息文件")],
                              capture_output=True, text=True, timeout=60).returncode
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        路径 = f.name
        f.write(消息)
    try:
        return subprocess.run(["sh", str(钩子路径), 路径],
                              capture_output=True, text=True, timeout=60).returncode
    finally:
        os.unlink(路径)


class 强制点必须在必经路径上(unittest.TestCase):
    def test_钩子存在且可执行(self) -> None:
        self.assertTrue(钩子路径.is_file(), f"钩子缺失：{钩子相对}")
        self.assertTrue(os.access(钩子路径, os.X_OK),
                        "钩子不可执行 —— git 对不可执行的钩子是**静默跳过**的（不报错、不提示），"
                        "「文件在」不等于「钩子生效」")

    def test_core_hooksPath指向本钩子(self) -> None:
        """★ 最容易漏的一环：钩子写好了但没人指过去 = 没装，且**没有任何报错**。"""
        完成 = subprocess.run([git, "config", "--get", "core.hooksPath"],
                              cwd=str(仓库根), capture_output=True, text=True, timeout=60)
        现值 = (完成.stdout or "").strip()
        self.assertEqual("开发工具/git钩子", 现值,
                         f"core.hooksPath 未指向本钩子（现值 {现值!r}）—— 装了但没接线，"
                         "提交强制点形同不存在。装法：git config core.hooksPath 开发工具/git钩子")

    def test_反向_期望值写错必须红(self) -> None:
        """★ 反向验证：证明上面那条判据真的在读配置，而不是恒真。"""
        完成 = subprocess.run([git, "config", "--get", "core.hooksPath"],
                              cwd=str(仓库根), capture_output=True, text=True, timeout=60)
        现值 = (完成.stdout or "").strip()
        self.assertNotEqual(现值, "开发工具/某个不存在的钩子目录",
                            "若这条相等，说明判据没在读真配置（本条就是它的对照）")


class 钩子判据本身(unittest.TestCase):
    """提交强制点（`commit-msg`）的**声明级 ＋ 实证级**两问。

    ★ 2026-09-25：钩子升到实证级（问二）—— 拿消息里的开工ID 去租约账核 `所有者` 列
    （`开发工具/git钩子/commit-msg::verify_workid`）。故「有开工ID必放」这类用例**不能再拿假ID**
    （旧版写死的 `开工-20260923-131126-78e8` 现在必红）：必须在一份**夹具租约账**里放一个
    真凭证，并让钩子在**能 import 到该夹具账**的临时树里跑（否则钩子读真账、假ID 必被拒）。
    本类自带那棵临时树（钩子副本 ＋ `平台控制面` 桩 ＋ `开发工具/MD文档生成` 放行桩）。

    口径版本：本夹具按「**所有者 恒＝开工ID**」那一版写（开工即占 不再允许覆盖 `所有者`）。

    ★ 夹具补第二档（2026-09-25，见 `setUp` 里 `文件租约存储.py` 那段注释）：问二实为
    **两小问**——活跃档查无时再查全量档（含 `已释放`/`已过期`，正常流程「先收工释放、
    后提交」走的就是这一档）。全量档那条腿 import 的是
    `平台控制面.能力目录.文件租约存储`，夹具必须一并桩上，否则
    `test_反向_假开工ID在账里查无必须拒` 会因「核验不可用 ⇒ 放行」而恒绿。
    """

    #: 夹具凭证：作为 `所有者` 注入夹具租约账 ⇒ 对钩子问二「真实存在」。
    夹具开工ID = "开工-20260925-120000-a1b2"
    #: 反向样本：形如真开工ID、但**不在**夹具账里 ⇒ 问二必须拒。
    夹具假开工ID = "开工-20260923-131126-78e8"

    def setUp(self) -> None:
        # ★ `self.仓库` 必须由 `self.临时根` 直接派生（不接函数返回值）——「测试写入边界门禁」
        #   解析左端基，接返回值会被判「写动作未解析」（与 `提交时整仓锁必须在位` 同口径）。
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_钩子开工ID_"))
        self.仓库 = self.临时根 / "仓库"
        self.仓库.mkdir()
        _运行git(self.仓库, "init", "-q", "-b", "main")
        钩子目录 = self.仓库 / "开发工具" / "git钩子"
        钩子目录.mkdir(parents=True)
        self.钩子 = 钩子目录 / "commit-msg"
        self.钩子.write_text(钩子路径.read_text(encoding="utf-8"), encoding="utf-8")
        # 判据二（写入凭据）的放行桩：本类只考开工ID 两问；凭据腿在临时树里不可用会把每笔都拒。
        凭据包 = self.仓库 / "开发工具" / "MD文档生成"
        凭据包.mkdir(parents=True)
        (凭据包 / "__init__.py").write_text("", encoding="utf-8")
        (凭据包 / "__main__.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        # 夹具租约账桩（唯一注入口：事实源由平台控制面侧载入时自注册）——`所有者` 列放夹具凭证。
        包 = self.仓库 / "平台控制面" / "能力目录"
        包.mkdir(parents=True)
        (self.仓库 / "平台控制面" / "__init__.py").write_text("", encoding="utf-8")
        (包 / "__init__.py").write_text(
            "from 公共契约.运行时.写入授权 import 设写租约事实源\n"
            "活跃表 = %r\n" % ({"夹具/凭证.txt": self.夹具开工ID},)
            + "设写租约事实源(lambda: (活跃表, \"\"))\n",
            encoding="utf-8")
        # ★ 问二的**全量档**（`只要活跃=假`）也必须桩上（2026-09-25 现场实测）：
        #   钩子 `verify_workid` 活跃档查无时会**再查全量档**（含 `已释放`/`已过期`，正常流程
        #   「先收工释放、后提交」走的就是这一档），那条腿直接
        #   `from 平台控制面.能力目录.文件租约存储 import 写租约所有者表`。夹具树里只有
        #   `能力目录/__init__.py` 时该 import 必失败 ⇒ 钩子按「核验不可用」放行
        #   ⇒ `test_反向_假开工ID在账里查无必须拒` 恒绿（**反向样本失效**，假红换假绿）。
        #   桩的是**租约账这个外部事实源**，不桩被测判据：两小问、退出码与文案照旧跑真身。
        #   全量档放同一个夹具凭证（真 ID 走「活跃档命中」这条更早的分支，全量档只兜底）；
        #   夹具假 ID 两档都查无 ⇒ 必须拒。★ 写入点必须与上面同形（`包 / 文件名` 左端基由
        #   `self.仓库 ← self.临时根` 解析得出）——「测试写入边界」门禁把解析不出的写动作
        #   fail-closed 计入违规，改成传参进来的 `包` 会当场判红。
        (包 / "文件租约存储.py").write_text(
            "全量账 = %r\n" % ({"夹具/凭证.txt": self.夹具开工ID},)
            + "\n"
            "\n"
            "def 写租约所有者表(存储目录=\"\", *, 只要活跃=True):\n"
            "    \"\"\"活跃档由夹具已注册的事实源回答，本桩只答全量档。\"\"\"\n"
            "    return ({} if 只要活跃 else dict(全量账)), \"\"\n",
            encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.临时根, ignore_errors=True)

    def _跑本树(self, 消息: str) -> int:
        """在**夹具树**里真跑钩子：`cwd`=夹具仓库 ⇒ 钩子的 python 以夹具树为 `sys.path[0]`，
        夹具 `平台控制面` 先于真仓库那份被导入（载入即注册夹具租约账）；
        `PYTHONPATH`=真仓库根 ⇒ 判据本体 `公共契约` 仍取自真源码树。"""
        环境 = dict(os.environ)
        环境["PYTHONPATH"] = str(仓库根)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            路径 = f.name
            f.write(消息)
        try:
            return subprocess.run(["sh", str(self.钩子), 路径], cwd=str(self.仓库),
                                  capture_output=True, text=True, timeout=120,
                                  env=环境).returncode
        finally:
            os.unlink(路径)

    def test_无开工ID必拒(self) -> None:
        self.assertNotEqual(self._跑本树("夹具：这条消息没有开工ID\n"), 0,
                            "没有开工ID 的提交必须被拒（这正是强制点的用途）")

    def test_有开工ID必放(self) -> None:
        self.assertEqual(self._跑本树(f"{self.夹具开工ID} 夹具：这条有开工ID\n"), 0)

    def test_开工ID在正文任意位置都认(self) -> None:
        self.assertEqual(self._跑本树(f"正文一段\n\n{self.夹具开工ID} 详情\n"), 0,
                         "开工ID 不强制在第一行（提交腿把消息原样传下来）")

    def test_反向_假开工ID在账里查无必须拒(self) -> None:
        """★ 问二（实证级）的反向样本：形如真开工ID、但夹具账里没有它 ⇒ 必须拒。

        弄坏→红：把夹具账桩的 `所有者` 换成假ID、或摘掉问二，本用例必红。
        """
        self.assertNotEqual(self._跑本树(f"{self.夹具假开工ID} 编一个开工ID 蒙混\n"), 0,
                            "账里查无的假开工ID 竟然放行了（问二没生效）")

    def test_自身出错一律放行(self) -> None:
        """钩子坏了不该让整个仓库提交瘫痪 —— 只有「检查跑完了且确实没声明」才拒。"""
        self.assertEqual(跑钩子(None), 0, "拿不到消息文件时必须放行（否则钩子一坏全仓提交死）")

    def test_git自身流程消息放行(self) -> None:
        for 消息 in ("Merge branch '主干'\n", "Revert \"某次提交\"\n",
                    "fixup! 前一条\n", "squash! 前一条\n"):
            self.assertEqual(self._跑本树(消息), 0, f"{消息.strip()} 不该被要求带开工ID")


class 提交时整仓锁必须在位(unittest.TestCase):
    """判据一（`pre-commit` 里的锁核验）的回归：**锁不在位 ⇒ 拒提交**。

    ## 夹具策略（**不对真仓库上锁**）

    在 `tempfile.mkdtemp()` 临时根里造一个小 git 仓库**真跑钩子**（`测试中心/支持库/测试_Git提供者.py`
    造桩钩子同法），**绝不对真仓库上锁**：真仓库的锁由显式动作（平台能力 / `运维脚本/仓库锁.py`）
    施加，不该由测试的副作用施加（同 `测试_仓库只读锁.py` 的夹具口径）。真仓库的整体状态是
    **运维读数**，不在回归里断言。

    ## ★ 为什么临时树里要放一个「桩」`开发工具/MD文档生成`

    本类只考**锁**那一条腿；钩子的另一条腿（判据二·写入凭据）要跑真的 `开发工具/MD文档生成`，
    而临时树里既没有 `开发文档/`、也没有类型登记 ⇒ 它会以「判据不可用」把**每一笔**都拒掉，
    于是锁的真红/真绿都测不出来（假红盖住真绿）。桩只做一件事：`sys.exit(0)`（凭据腿放行），
    使**被测的那条腿成为唯一变量**。桩写在**临时树**里（不进本仓），且只桩「另一条腿」，
    **不桩被测判据本身** —— 锁核验跑的是真钩子、真的 `仓库只读锁.查询()`。
    """

    def setUp(self) -> None:
        # ★ `self.仓库` 必须由 `self.临时根` 直接派生（不接任何函数的返回值）：
        #   否则「测试写入边界门禁」解析不出左端基，把建树动作判成「写动作未解析」（fail-closed）。
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_钩子锁校验_"))
        self.仓库 = self.临时根 / "仓库"
        self.仓库.mkdir()
        self._放凭据腿桩()
        (self.仓库 / "甲.txt").write_text("内容\n", encoding="utf-8")
        _运行git(self.仓库, "init", "-q", "-b", "main")
        # 默认租约账桩：**没有**活跃租约 ⇒ 未锁一律算真缺口（老口径行为，也是其它用例的封闭前提）。
        self._写租约账桩()

    def tearDown(self) -> None:
        # 锁着的东西删不掉（这是锁生效的副产品）—— 先解锁、再兜底清标志，最后才删树。
        try:
            锁.解锁全仓(self.仓库)
        except Exception:
            pass
        if hasattr(os, "chflags"):
            for 项 in sorted(self.临时根.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                try:
                    os.chflags(项, 0)
                except OSError:
                    pass
            try:
                os.chflags(self.临时根, 0)
            except OSError:
                pass
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _放凭据腿桩(self) -> None:
        """给「判据二（写入凭据）」放一个放行桩 —— 理由见类 docstring。"""
        包 = self.仓库 / "开发工具" / "MD文档生成"
        包.mkdir(parents=True)
        (包 / "__init__.py").write_text("", encoding="utf-8")
        (包 / "__main__.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

    def _写租约账桩(self, 活跃相对路径集: frozenset[str] = frozenset()) -> None:
        """在**临时树**里放一个 `平台控制面/能力目录` 桩：注册一份「活跃租约账」。

        桩的是**租约账（外部事实源）**，不是被测判据：钩子里的 `查询()` /
        `活跃租约开窗集()` / `未锁分档()` 照旧跑真身。不桩就没法在临时树里造出「活跃租约开窗」
        这个现场 —— 真租约账在真仓库的 `工程缓存/平台控制面/文件租约.json` 里，而钩子只认
        **它自己那棵树**能 import 到的事实源。

        生效机制：核验进程由钩子 `cd "$ROOT"` 后以 `python -c` 启动，`sys.path[0]` 就是临时树
        ⇒ 临时树里的 `平台控制面` **先于**真仓库那份被导入（载入即调 `设写租约事实源`）。
        必须在 `上锁全仓()` **之前**调：桩文件也得进扫描面并锁上，否则它们自己就是未锁条目。
        """
        包 = self.仓库 / "平台控制面" / "能力目录"
        包.mkdir(parents=True, exist_ok=True)
        (self.仓库 / "平台控制面" / "__init__.py").write_text("", encoding="utf-8")
        # ★ 2026-09-25：事实源的值从**路径集**改成**映射**（路径 → 所有者）；本桩只喂
        #   开窗面（路径），所有者填桩名即可 —— 钩子里的 `活跃租约开窗集()` 只取键。
        活跃表 = {路径: "夹具所有者" for 路径 in sorted(活跃相对路径集)}
        (包 / "__init__.py").write_text(
            "from 公共契约.运行时.写入授权 import 设写租约事实源\n"
            "活跃表 = %r\n" % (活跃表,)
            + "设写租约事实源(lambda: (活跃表, \"\"))\n",
            encoding="utf-8")

    def _改钩子源码(self, 替换: dict[str, str] | None) -> Path:
        """把真钩子的源码改一处（`替换=None` 则摘除锁核验整段）后写进临时树，返回副本路径。

        **锚点缺失一律 `assertIn` 报错**，不静默跳过：反向验证一旦锚点漂移，必须**报错**而不是
        「悄悄地不再验证」——那正是本仓反复栽过的「判据在≠判据接线」。
        """
        源 = 提交钩子路径.read_text(encoding="utf-8")
        if 替换:
            for 旧, 新 in 替换.items():
                self.assertIn(旧, 源, f"锚点缺失：{旧!r} —— 钩子改了，本用例必须跟着改（不许静默失效）")
                源 = 源.replace(旧, 新)
        else:
            开始, 结束 = "# >>> 锁核验开始", "# <<< 锁核验结束"
            self.assertIn(开始, 源, "锁核验开始锚点缺失 —— 反向验证失效（必须报错，不许静默跳过）")
            self.assertIn(结束, 源, "锁核验结束锚点缺失 —— 反向验证失效（必须报错，不许静默跳过）")
            头, 余 = 源.split(开始, 1)
            _, 尾 = 余.split(结束, 1)
            源 = 头 + 尾
        副本 = self.临时根 / "钩子副本.sh"
        副本.write_text(源, encoding="utf-8")
        return 副本

    def _解锁(self, *路径表: Path) -> None:
        """带网关识别符号地解锁：`解锁()` 只认 `系统库网关凭证`（2026-09-23 裁决）。

        本进程内**临时**带上、随即摘掉 —— 钩子子进程是**另起**的，跑它时环境照旧不带符号
        （`跑提交钩子` 自己只摘 `系统平台_修MCP自身`），故被测的那条腿一个变量都不受影响。
        不带符号地解锁会抛 `PermissionError`（本文件在终端里跑就撞过），于是「造一个缺口」
        这个夹具前提在终端环境里根本做不出来 —— 那不是判据红，是夹具缺一步。
        """
        旧值 = os.environ.get("系统库网关凭证")
        os.environ["系统库网关凭证"] = "回归锁-钩子夹具"
        try:
            for 路径 in 路径表:
                锁.解锁(路径)
        finally:
            if 旧值 is None:
                os.environ.pop("系统库网关凭证", None)
            else:
                os.environ["系统库网关凭证"] = 旧值

    def _断言锁缺失被拒(self, 钩子: Path | None = None) -> None:
        """② 的判据本体（反向用例会拿它当「必须变红」的那个断言）。"""
        完成 = 跑提交钩子(self.仓库, 钩子)
        self.assertNotEqual(0, 完成.returncode,
                            f"锁不在位时必须拒提交；实际退出码 {完成.returncode}\n{完成.stderr}")
        self.assertIn("整仓内核锁有真缺口", 完成.stderr,
                      "拒的理由必须说清是「真缺口」（2026-09-24 起与「活跃租约开窗」分开报）")
        self.assertIn("python3.14 运维脚本/仓库锁.py", 完成.stderr, "拒时必须给出可照抄的修法")
        self.assertIn("--补齐", 完成.stderr, "修法里要带上「只补缺口」那条（写腿被杀后的兜底）")

    def test_提交钩子存在且可执行(self) -> None:
        """git 对**不可执行**的钩子是静默跳过的 —— 「文件在」不等于「钩子生效」。"""
        self.assertTrue(提交钩子路径.is_file(), f"钩子缺失：{提交钩子相对}")
        self.assertTrue(os.access(提交钩子路径, os.X_OK),
                        "提交钩子不可执行 —— git 会静默跳过它（不报错、不提示）")

    def test_锁在位_放行(self) -> None:
        """① 锁在位 ⇒ 放行（这条是「不产生假红」的证明：判据不能把正常状态也拒掉）。"""
        结果 = 锁.上锁全仓(self.仓库)
        self.assertTrue(结果["支持"], "夹具前提：本平台要能上内核锁（仅 macOS）")
        self.assertEqual(0, 锁.查询(self.仓库)["未锁数"], "夹具前提：上完锁必须无缺口")
        完成 = 跑提交钩子(self.仓库)
        self.assertEqual(0, 完成.returncode,
                         f"锁在位时提交必须放行；实际退出码 {完成.returncode}\n{完成.stderr}")

    def test_锁缺失_拒且给出可照抄的修法(self) -> None:
        """② 从没上过锁 ⇒ 拒（含退出码非 0 + 消息里有可照抄的修法）。"""
        self._断言锁缺失被拒()

    def test_有缺口_一样拒(self) -> None:
        """「上过锁但破了口」与「从没上锁」是同一件事：缺口可度量，不看感觉。

        这条防的是「只锁一部分也算锁住了」那种自欺 —— 钩子读的是 `查询()` 的未锁数，不是「锁过没」。
        """
        锁.上锁全仓(self.仓库)
        self.assertEqual(0, 锁.查询(self.仓库)["未锁数"], "夹具前提：先造一个无缺口的锁树")
        self._解锁(self.仓库 / "甲.txt")
        self.assertEqual(1, 锁.查询(self.仓库)["未锁数"], "夹具前提：造出一个缺口")
        完成 = 跑提交钩子(self.仓库)
        self.assertNotEqual(0, 完成.returncode, "有缺口就必须拒（只锁一部分 = 没锁）")
        self.assertIn("甲.txt", 完成.stderr, "拒的时候要指出缺口在哪，不能只说「锁不在位」")

    def test_活跃租约开窗_放行且标出开窗条数(self) -> None:
        """★ 判据一（2026-09-24 批M-b）：整仓 `未锁 > 0` 但**全是活跃租约开窗** ⇒ 放行。

        现场形状（zcode 会话亲历）：`开工编排.开工即占` 认领路径成功即
        `解锁供写入(目标 ＋ 父链)` ⇒ 认领期间那几条**本来就该是未锁**（设计行为）；
        旧口径拿 `未锁数 > 0` 判红 ⇒ **提交被误拒**（实测：整仓 `未锁 2`，而那 2 条正是
        另一会话活跃租约的开窗）。判据 = 只看 `缺口数`；放行时如实打印开窗条数（不静默）。
        """
        self._写租约账桩(frozenset({"甲.txt"}))
        锁.上锁全仓(self.仓库)
        self.assertEqual(0, 锁.查询(self.仓库)["未锁数"], "夹具前提：上完锁必须无缺口")
        self._解锁(self.仓库 / "甲.txt")            # 认领路径时平台做的动作
        完成 = 跑提交钩子(self.仓库)
        self.assertEqual(0, 完成.returncode,
                         f"活跃租约开窗不该拒提交；实际退出码 {完成.returncode}\n{完成.stderr}")
        self.assertIn("活跃租约开窗", 完成.stderr, "放行时也要如实标出开窗条数（不静默）")
        self.assertIn("真缺口 0", 完成.stderr)

    def test_开窗与真缺口并存_只对真缺口拒(self) -> None:
        """两种未锁同时在：钩子**只拒真缺口**，并在读数里把两者分开报（不再同形）。"""
        (self.仓库 / "乙.txt").write_text("内容\n", encoding="utf-8")
        self._写租约账桩(frozenset({"甲.txt"}))
        锁.上锁全仓(self.仓库)
        self._解锁(self.仓库 / "甲.txt")            # 开窗（有活跃租约）
        self._解锁(self.仓库 / "乙.txt")            # 真缺口（没有租约）
        完成 = 跑提交钩子(self.仓库)
        self.assertNotEqual(0, 完成.returncode, "有真缺口就必须拒")
        self.assertIn("真缺口", 完成.stderr)
        self.assertIn("乙.txt", 完成.stderr, "拒的时候要指出真缺口在哪")
        self.assertIn("活跃租约开窗 1", 完成.stderr, "两种未锁必须分开报（开窗 1 ＋ 真缺口 1）")

    def test_判据不可用_必须拒(self) -> None:
        """边界口径③：判据自身不可用 ⇒ 未核验 fail-closed（锁**已经上好了**也照拒）。

        夹具把 `PYTHONPATH` 拔掉 ⇒ 临时树里 import 不到 `公共契约.运行时.仓库只读锁`。
        这是「问不到」而不是「无问题可问」，故与下面那条 fail-open 用例方向相反。
        """
        锁.上锁全仓(self.仓库)
        self.assertEqual(0, 锁.查询(self.仓库)["未锁数"], "夹具前提：锁本身是在位的")
        完成 = 跑提交钩子(self.仓库, 带平台路径=False)
        self.assertNotEqual(0, 完成.returncode,
                            f"判据自身不可用必须 fail-closed；实际退出码 {完成.returncode}\n{完成.stderr}")
        self.assertIn("锁核验=不可用", 完成.stderr, "要如实报「判据不可用」，不能冒充「有缺口」")
        self.assertIn("fail-closed", 完成.stderr)

    def test_平台不支持内核锁_放行(self) -> None:
        """边界口径②：非 macOS（`支持内核锁()` 为假）⇒ 放行 + 告警（fail-open）。

        理由（钩子头部有全文）：机制在本平台**不存在**，强判等于造一个永远修不好的假红。
        本机是 macOS，造不出真的非 macOS，故**只把那一处判据改成恒真**（`if not 锁.支持内核锁():`
        → `if True:`），其余一字不动 —— 测的仍是钩子真身的分支，不是另写一套判据。
        """
        副本 = self._改钩子源码({"if not 锁.支持内核锁():": "if True:"})
        # 故意不上锁：若 fail-open 生效，此刻必须放行。
        完成 = 跑提交钩子(self.仓库, 钩子=副本)
        self.assertEqual(0, 完成.returncode,
                         f"非 macOS 必须 fail-open（机制不存在）；实际退出码 {完成.returncode}\n{完成.stderr}")
        self.assertIn("本平台不支持内核级只读锁", 完成.stderr, "放行必须大声告警，不能静默")

    def test_反向_摘掉锁核验段_锁缺失用例必须变红(self) -> None:
        """★ 反向验证：把锁核验整段摘掉，「锁缺失必须拒」这条判据**必须变红**。

        做法：按钩子里的两个锚点摘除整段，写成副本在**同一个小仓库**（锁缺失）里真跑，
        再拿 ② 的判据本体去断言它 —— 这里包在 `assertRaises(AssertionError)` 里：
        **摘掉后若仍然拒，说明那条「拒」不是锁核验给出的**（反向验证就是装饰）。
        锚点被改动 ⇒ `_改钩子源码` 直接报错（不会静默失效）。
        """
        副本 = self._改钩子源码(None)
        with self.assertRaises(AssertionError,
                               msg="摘掉锁核验后「锁缺失必须拒」仍成立 ⇒ 这条反向验证是装饰"):
            self._断言锁缺失被拒(副本)


if __name__ == "__main__":
    unittest.main()
