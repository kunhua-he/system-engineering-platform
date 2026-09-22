"""工作区指纹「固定排除表」回归：本地产物不得算成「未跟踪正式文件」（假红）。

## 修前缺陷（现场证据，2026-09-23）

`开发工具/项目编译/工作区指纹.py` 的未跟踪腿用 `git ls-files --others -z`，
**不带 `--exclude-standard`**（该文件内注释明写「.gitignore 不是指纹语义的一部分」）
⇒ 排除项**只认** `固定排除目录` / `固定排除文件` 两张显式表 —— **靠 `.gitignore` 保不住工作区**。

实测（改前 `计算工作区字节指纹(仓库根)`）：`未跟踪正式文件数 = 301`、工作区状态恒判
「含未提交变更」、字节指纹随本机残留而变。301 = 300 个 `.tmp/**`（门禁/测试临时树）
+ 1 个 `.zcodeignore`（ZCode 客户端本地产物）。两类都**不是仓库源码**。

改后同一调用：`未跟踪正式文件数 = 0`、`未暂存正式文件数 = 2`（正是本轮改的两个源码文件）。

## 本测试钉住的判据

1. `.zcodeignore`（按基名判定 ⇒ 任意深度同名文件）不是正式路径；
2. `.tmp/` 下任何文件（任意深度）不是正式路径；
3. 对**现场真实 git 输出**核一遍（不是只核常量表）：这两类本地产物不得出现在
   未跟踪腿的正式文件候选里；
4. ★ 反向保护：**真源码仍然是正式路径** —— 排除表不许宽到把未提交的新源码也挡掉
   （那会把真改动藏进「干净」，与假红同等有害）。

跑法：python3.14 -m unittest 测试中心.开发工具.测试_工作区指纹排除表
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parents[2]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 开发工具.项目编译.工作区指纹 import _是正式路径


def _git未跟踪清单() -> list[str]:
    """现场未跟踪路径 —— **与指纹同一条腿**（`ls-files --others`，不带 `--exclude-standard`）。"""
    完成 = subprocess.run(["git", "ls-files", "--others", "-z"], cwd=str(仓库根),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return sorted({项.decode("utf-8", "surrogateescape")
                   for 项 in 完成.stdout.split(b"\0") if 项})


class 本地产物不得进指纹(unittest.TestCase):
    """两类本地产物都必须在排除表里，否则工作区恒判「含未提交变更」。"""

    def test_zcodeignore不是正式路径(self) -> None:
        self.assertFalse(_是正式路径(".zcodeignore"),
                         "ZCode 客户端本地产物 .zcodeignore 被算成「未跟踪正式文件」⇒ 假红")
        self.assertFalse(_是正式路径("开发工具/.zcodeignore"),
                         "固定排除文件按**基名**判定，任意深度的同名文件都要挡")

    def test_tmp目录下不是正式路径(self) -> None:
        for 路径 in (".tmp/反向破坏_abc/实现/能力.py",
                    ".tmp/门禁_备份恢复_abc/备份/快照_1/备份清单.json",
                    "开发工具/.tmp/临时.py"):
            self.assertFalse(_是正式路径(路径),
                             f"{路径} 是本地产物（仓库内临时根），不得算正式文件")

    def test_现场未跟踪表里这两类本地产物已被挡(self) -> None:
        """端到端：对现场真实 `git ls-files --others` 输出核，不是只核常量表。

        判据是「**过了 `_是正式路径` 之后**还剩不剩本地产物」—— 原始 git 清单里当然有
        `.tmp/**`（git 的未跟踪腿本就报它们），要核的是指纹会不会把它们算成正式文件。
        """
        泄漏 = [路径 for 路径 in _git未跟踪清单()
               if _是正式路径(路径)
               and (路径 == ".zcodeignore" or 路径.startswith(".tmp/"))]
        self.assertEqual(泄漏, [],
                         f"本地产物仍留在未跟踪腿的正式文件候选里（前 5 条）：{泄漏[:5]}")


class 排除表不得宽到挡真源码(unittest.TestCase):
    """★ 反向保护：把真源码也排除掉，会把真改动藏进「干净」——与假红同等有害。"""

    def test_真源码仍是正式路径(self) -> None:
        for 路径 in ("开发工具/项目编译/工作区指纹.py",
                    "开发工具/开发编译口/编译口.py",
                    "测试中心/开发工具/测试_工作区指纹排除表.py",
                    "支持库/后端/文件系统支持库/文本补丁/实现/文本补丁.py",
                    "新写的未提交源码.py"):
            self.assertTrue(_是正式路径(路径),
                            f"{路径} 是源码，必须仍算「正式文件」（不得被排除表误挡）")


if __name__ == "__main__":
    unittest.main()
