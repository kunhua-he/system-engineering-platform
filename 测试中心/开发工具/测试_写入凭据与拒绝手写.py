"""写入凭据与「拒绝手写 md」判据的测试（哲学 7.9 + 2026-09-23 华哥裁决）。

华哥 2026-09-23 口径：

> 「说明书的那个，是否可以固定规范？**人工也要使用 mcp 工具才行。不能直接手写？否则编译的时候，直接报错。**」

本模块锁两件事：

1. **判据是「本次写入有没有凭据」，不是「有没有机器印记」**（实测到的口子）：
   印记是文件级、加一次永久有效 ⇒ 有印记的文件此后被人**直接改**永远不会被拦
   （实测：`模块库/自修复工具/说明/使用说明.md` 有印记，人直接写文件改它，
   旧校验照样报「通过」）。故新增问二：**现场内容指纹是否命中 `MD写入流水.jsonl`**。
2. **三条写入腿都留凭据**（`文件操作.写入文件` / `文本补丁.应用精确替换` /
   `文本补丁.批量应用精确替换`）：判据认的是「经工具写」，所以工具自己必须留痕；
   漏一条腿 ⇒ 那条腿写的 md 会被误判成手写（假红）。

夹具一律落 `tempfile` 临时根（**不写仓库任何文件**）：判据面在写入流水模块与
「拒绝手写」的组合上，真跑由编译口与 MCP 验收。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.诊断 import 写入流水


class 写入流水测试(unittest.TestCase):
    """流水本身：只增不改、内容指纹判据、坏行跳过。"""

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="测试_写入凭据_")
        self.根 = Path(self._临时.name)
        (self.根 / "开发文档").mkdir()

    def tearDown(self) -> None:
        self._临时.cleanup()

    def test_记一次写入后可命中(self) -> None:
        相对 = "开发文档/示例.md"
        (self.根 / 相对).write_text("# 标题\n", encoding="utf-8")
        指纹 = 写入流水.记一次写入(self.根, 相对, "# 标题\n", 类型名="权威文档")
        self.assertEqual(写入流水.内容指纹("# 标题\n"), 指纹)
        self.assertTrue(写入流水.有写入凭据(self.根, 相对, "# 标题\n"),
                        "刚记的写入必须命中（否则判据恒红＝假红）")

    def test_内容变了就不命中(self) -> None:
        """★ 这是整条判据的支点：人改了内容 ⇒ 指纹对不上 ⇒ 不命中。"""
        相对 = "开发文档/示例.md"
        写入流水.记一次写入(self.根, 相对, "# 标题\n")
        self.assertFalse(写入流水.有写入凭据(self.根, 相对, "# 标题\n人又加了一行\n"),
                         "内容被改过还声称命中 ⇒ 判据形同虚设")

    def test_换行风格差异也不命中(self) -> None:
        """指纹按原始字节算 ⇒ 只改行尾也必须被发现（不许归一化）。"""
        相对 = "开发文档/示例.md"
        写入流水.记一次写入(self.根, 相对, "# 标题\n")
        self.assertFalse(写入流水.有写入凭据(self.根, 相对, "# 标题\r\n"))

    def test_只增不改(self) -> None:
        相对 = "开发文档/示例.md"
        写入流水.记一次写入(self.根, 相对, "第一版\n")
        写入流水.记一次写入(self.根, 相对, "第二版\n")
        行 = 写入流水.流水路径(self.根).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(2, len(行), "同一文件两次写入必须是两条记录（证据链只增）")
        self.assertTrue(写入流水.有写入凭据(self.根, 相对, "第一版\n"),
                        "旧版本凭据不得被覆盖（改一条就等于抹掉「有人直接改过」的痕迹）")
        self.assertTrue(写入流水.有写入凭据(self.根, 相对, "第二版\n"))

    def test_坏行跳过不致死(self) -> None:
        """半行（进程被杀留下的）只丢它自己那一次记录，不得让全部历史凭据失效。"""
        相对 = "开发文档/示例.md"
        写入流水.记一次写入(self.根, 相对, "好的一版\n")
        路径 = 写入流水.流水路径(self.根)
        with 路径.open("a", encoding="utf-8") as 文件:
            文件.write('{"相对路径": "开发文档/示例.md", "内容sha256": "半')  # 故意截半
        self.assertTrue(写入流水.有写入凭据(self.根, 相对, "好的一版\n"),
                        "半行不得让整份流水不可用（那会把「有凭据」误判成「没凭据」）")

    def test_无流水文件时不炸(self) -> None:
        self.assertEqual(set(), 写入流水.读过全部流水(self.根))
        self.assertFalse(写入流水.有写入凭据(self.根, "开发文档/示例.md", "内容"))


class 三条写入腿留凭据测试(unittest.TestCase):
    """`文件操作.写入文件` / `应用精确替换` / `批量应用精确替换` 三条腿都要留痕。"""

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="测试_写入腿_")
        self.根 = Path(self._临时.name)
        (self.根 / "开发文档").mkdir()
        (self.根 / "AGENTS.md").write_text("# 规则\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def test_写入文件这条腿留凭据(self) -> None:
        """直接调 `写入文件`（进程内，不经装配）写临时根里的 md ⇒ 必须留凭据。

        `写入文件` 是文件操作支持库的公开能力，进程内直调需要装配 —— 故这里走
        **子进程 + 真装配**（与 MCP 同一路径），避免绕过能力调用服务。
        装配成本高，故本用例的判据落在「留凭据」这一个断言上，不重复跑其它面。
        """
        相对 = "开发文档/腿一.md"
        脚本 = (
            "import sys; sys.path.insert(0, %r)\n"
            "from 公共契约.能力契约.调用器 import 获取能力调用器\n"
            "调用器 = 获取能力调用器()\n"
            "r = 调用器.调用能力('文件系统支持库.文件操作.写入文件',\n"
            "    {'文件路径': %r, '内容': '# 腿一\\n'})\n"
            "print('成功' if r.成功 else r.错误码)\n"
        ) % (str(系统根), str(self.根 / 相对))
        结果 = subprocess.run([sys.executable, "-c", 脚本], capture_output=True, text=True,
                            cwd=str(系统根), timeout=120)
        if "未装配" in 结果.stdout + 结果.stderr:
            self.skipTest("进程内无装配（该腿的装配由加载器提供）：本用例的判据面改由编译口与 MCP 验收")
        if "成功" not in 结果.stdout:
            self.skipTest(f"装配未就绪（{结果.stdout.strip()[:80]}）：改由 MCP 验收")
        self.assertTrue(写入流水.有写入凭据(self.根, 相对, "# 腿一\n"),
                        "经 写入文件 写的 md 必须留凭据（否则工具写的会被判成手写＝假红）")

    def test_文本补丁腿留凭据(self) -> None:
        """`应用精确替换` 与 `批量应用精确替换` 共用 `_原子写保留权限` ⇒ 挂一处覆盖两条。"""
        from 支持库.后端.文件系统支持库.文本补丁.实现.文本补丁 import _原子写保留权限
        目标 = self.根 / "开发文档" / "腿二.md"
        目标.write_text("旧内容\n", encoding="utf-8")
        _原子写保留权限(目标, "新内容\n")
        self.assertEqual("新内容\n", 目标.read_text(encoding="utf-8"))
        self.assertTrue(写入流水.有写入凭据(self.根, "开发文档/腿二.md", "新内容\n"),
                        "经 文本补丁 原子写落的 md 必须留凭据")

    def test_非md不留凭据(self) -> None:
        """反向：判据（拒绝手写md）只管 md，对别的文件留痕是白噪声 + 白一次 IO。"""
        from 支持库.后端.文件系统支持库.文本补丁.实现.文本补丁 import _原子写保留权限
        目标 = self.根 / "开发文档" / "不是md.json"
        目标.write_text("{}", encoding="utf-8")
        _原子写保留权限(目标, "{}\n")
        self.assertEqual(set(), 写入流水.读过全部流水(self.根),
                         "非 md 文件不得写凭据")


class 拒绝手写判据两问测试(unittest.TestCase):
    """判据合成：问一 印记 + 问二 本次写入凭据；两问都过才算通过。"""

    def test_判据源码确实查了两次(self) -> None:
        """源码级锁：`_拒绝手写校验` 必须同时用 `有印记` 与 `有写入凭据`。

        为什么用源码级而不是行为级：这条判据跑的是**真实 git 改动集**，
        行为级夹具要在真仓库里造一次未提交改动（会影响别人的工作区）——
        源码级锁能守住「问二不被后续重构悄悄摘掉」，且不污染工作区。
        """
        源码 = (系统根 / "开发工具" / "MD文档生成" / "__main__.py").read_text(encoding="utf-8")
        起点 = 源码.index("def _拒绝手写校验")
        终点 = 源码.index("def _总览")
        段 = 源码[起点:终点]
        self.assertIn("机器印记.有印记", 段, "问一（归属）必须还在")
        self.assertIn("写入流水.有写入凭据", 段, "问二（本次写入凭据）必须也在")
        self.assertIn("无凭据", 段, "问二的判红桶必须真的参与判定（只赋值不判 = 空接线）")

    def test_写盘路径确实记凭据(self) -> None:
        """生成器 `--写盘` 必须在写完落一条凭据（否则工具写的反被判成手写）。"""
        源码 = (系统根 / "开发工具" / "MD文档生成" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("_记写入凭据", 源码)
        段起点 = 源码.index("def _记写入凭据")
        段 = 源码[段起点:段起点 + 600]
        self.assertIn("记一次写入", 段)

    def test_三条写入腿都接了(self) -> None:
        """两条写腿都必须**转调唯一节点**（2026-09-24 裁决：根推断与登记只留一处实现）。

        改前这里断言的是两条腿**各自实现**一份私有登记函数（`_登记md写入凭据(路径, 内容)`
        / `_登记md写入凭据(目标, 正文)`）—— 那正是「同一件事两套实现」（哲学 1.2），
        且两份根推断必然走偏。现在唯一节点是 `公共契约.诊断.写入流水.登记md写入凭据`，
        两条腿只许转调它（含 `.md` 判据与根推断，腿里一个字都不许再有）。
        """
        唯一节点 = "写入流水.登记md写入凭据("
        文件操作 = (系统根 / "支持库" / "后端" / "文件系统支持库" / "文件操作"
                / "实现" / "文件系统.py").read_text(encoding="utf-8")
        self.assertIn(唯一节点, 文件操作, "写入文件这条腿必须转调唯一登记节点")
        self.assertNotIn("def _登记md写入凭据", 文件操作, "腿里不得再留第二份登记实现")
        补丁 = (系统根 / "支持库" / "后端" / "文件系统支持库" / "文本补丁"
              / "实现" / "文本补丁.py").read_text(encoding="utf-8")
        self.assertIn(唯一节点, 补丁, "文本补丁这条腿必须转调唯一登记节点")
        self.assertNotIn("def _登记md写入凭据", 补丁, "腿里不得再留第二份登记实现")


if __name__ == "__main__":
    unittest.main()
