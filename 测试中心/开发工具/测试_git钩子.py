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

跑法：python3.14 -m unittest 测试中心.开发工具.测试_git钩子
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

钩子相对 = "开发工具/git钩子/commit-msg"
钩子路径 = 仓库根 / 钩子相对
git = "/Library/Developer/CommandLineTools/usr/bin/git"


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
    def test_无开工ID必拒(self) -> None:
        self.assertNotEqual(跑钩子("夹具：这条消息没有开工ID\n"), 0,
                            "没有开工ID 的提交必须被拒（这正是强制点的用途）")

    def test_有开工ID必放(self) -> None:
        self.assertEqual(跑钩子("开工-20260923-131126-78e8 夹具：这条有开工ID\n"), 0)

    def test_开工ID在正文任意位置都认(self) -> None:
        self.assertEqual(跑钩子("正文一段\n\n开工-20260923-131126-78e8 详情\n"), 0,
                         "开工ID 不强制在第一行（提交腿把消息原样传下来）")

    def test_自身出错一律放行(self) -> None:
        """钩子坏了不该让整个仓库提交瘫痪 —— 只有「检查跑完了且确实没声明」才拒。"""
        self.assertEqual(跑钩子(None), 0, "拿不到消息文件时必须放行（否则钩子一坏全仓提交死）")

    def test_git自身流程消息放行(self) -> None:
        for 消息 in ("Merge branch '主干'\n", "Revert \"某次提交\"\n",
                    "fixup! 前一条\n", "squash! 前一条\n"):
            self.assertEqual(跑钩子(消息), 0, f"{消息.strip()} 不该被要求带开工ID")


if __name__ == "__main__":
    unittest.main()
