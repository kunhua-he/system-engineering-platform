"""原子落盘「顶位失败后旧环境仍可启动」负路径断言（开工ID：20260918-负路径5类断言）。

对应外部审计报告①-8 第 ③ 类：`运行核心/运行环境管理器/远程镜像.py::原子落盘` 的
口径是「**任一时刻磁盘上至少有一个可用环境**」—— 旧环境不删除，只改名让位；新环境
`os.replace` 顶位失败时把让位目录改回原名。修复已在 `97ca5792` 入库，本文件是它的
**长期回归守护**（不是一次性反向验证）。

判定口径（不靠读注释，靠真实磁盘副作用）：
- 注入 `os.replace` 让「临时目录 → 目标目录」这一步抛 `OSError`（模拟磁盘满/只读）；
- 断言抛出的错误**点名了顶位失败与回滚结论**；
- 断言旧环境目录**仍存在**、哨兵文件**字节逐字可读**（这就是「旧环境可启」）；
- 断言无让位残留、临时目录已清理（失败不留半截）。

反向（必红）：把实现换成修复前的 git 基线，同一场景下旧环境**必然被 rmtree 删除**。
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.运行环境管理器.远程镜像 import 原子落盘  # noqa: E402

系统根 = Path(__file__).resolve().parents[2]
#: 修复前的实现（先 `rmtree(旧环境)` 再 `os.replace`）：顶位失败即旧环境已丢。
修复前基线 = "97ca5792^"

旧环境哨兵 = "#!/bin/sh\n# 旧环境 v1 哨兵：这段内容必须逐字活下来\nexit 0\n"
新环境哨兵 = "#!/bin/sh\n# 新环境 v2\nexit 0\n"
环境文件 = Path("bin") / "python3"
真replace = os.replace


def 加载修复前实现():
    """把修复前的 `远程镜像` 从 git 取出、落到 /tmp 并加载（只读历史，不动工作区）。"""
    源码 = subprocess.run(
        ["git", "show", f"{修复前基线}:运行核心/运行环境管理器/远程镜像.py"],
        cwd=str(系统根), capture_output=True, text=True, check=True).stdout
    临时 = Path(tempfile.mkdtemp(prefix="原子落盘反向验证_")) / "修复前远程镜像.py"
    临时.write_text(源码, encoding="utf-8")
    规格 = importlib.util.spec_from_file_location("修复前远程镜像", 临时)
    if 规格 is None or 规格.loader is None:
        raise RuntimeError("修复前实现无法构造导入规格")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules["修复前远程镜像"] = 模块
    规格.loader.exec_module(模块)
    return 模块


class 原子落盘夹具(unittest.TestCase):
    def setUp(self) -> None:
        self.根 = Path(tempfile.mkdtemp(prefix="原子落盘_"))
        self.目标 = self.根 / "运行环境"
        self.临时 = self.根 / "落盘临时"

    def tearDown(self) -> None:
        os.replace = 真replace  # 兜底还原，避免补丁跨用例泄漏
        shutil.rmtree(self.根, ignore_errors=True)

    def 造旧环境(self) -> None:
        (self.目标 / 环境文件).parent.mkdir(parents=True, exist_ok=True)
        (self.目标 / 环境文件).write_text(旧环境哨兵, encoding="utf-8")
        (self.目标 / "标记.txt").write_text("旧环境附加件", encoding="utf-8")

    def 造新环境(self) -> None:
        (self.临时 / 环境文件).parent.mkdir(parents=True, exist_ok=True)
        (self.临时 / 环境文件).write_text(新环境哨兵, encoding="utf-8")

    def 装顶位失败补丁(self):
        """只拦「临时目录 → 目标目录」这一步；让位与回滚都走真实实现。"""
        临时目录 = self.临时

        def 假replace(源, 目的, **参数):
            if pathlib.Path(源) == 临时目录:
                raise OSError(28, "模拟顶位失败 No space left on device")
            return 真replace(源, 目的, **参数)

        os.replace = 假replace

    def 让位残留(self) -> list[str]:
        return sorted(项.name for 项 in self.根.iterdir() if "让位" in 项.name)


class Test顶位失败旧环境仍可启(原子落盘夹具):
    def test_顶位失败_旧环境仍在且哨兵逐字可读(self) -> None:
        self.造旧环境()
        self.造新环境()
        self.装顶位失败补丁()
        try:
            with self.assertRaises(OSError) as 上下文:
                原子落盘(self.临时, self.目标)
        finally:
            os.replace = 真replace

        说明 = str(上下文.exception)
        # 结构：错误说明必须点名「顶位失败」与回滚结论，不许静默吞掉
        self.assertIn("顶位失败", 说明, f"未走到顶位失败分支（补丁打歪了）: {说明}")
        self.assertIn("已回滚", 说明, f"回滚未执行: {说明}")
        # 真实副作用：旧环境目录与哨兵逐字仍在 —— 这就是「旧环境可启动」
        self.assertTrue(self.目标.is_dir(), "顶位失败后旧环境目录不得消失")
        self.assertEqual((self.目标 / 环境文件).read_text(encoding="utf-8"), 旧环境哨兵,
                         "旧环境哨兵必须逐字可读（旧环境可启）")
        self.assertEqual((self.目标 / "标记.txt").read_text(encoding="utf-8"), "旧环境附加件",
                         "旧环境附加件必须一并保住")
        # 失败不留半截：让位目录已复位、临时目录已清理
        self.assertEqual(self.让位残留(), [], "回滚成功后不得残留让位目录")
        self.assertFalse(self.临时.exists(), "失败后临时目录必须清理")

    def test_顶位失败后旧环境仍能被当作解释器路径使用(self) -> None:
        """「可启」的落地口径：哨兵脚本仍可执行（真实跑一次，不是只看文件在不在）。"""
        self.造旧环境()
        脚本 = self.目标 / 环境文件
        脚本.chmod(0o755)
        self.造新环境()
        self.装顶位失败补丁()
        try:
            with self.assertRaises(OSError):
                原子落盘(self.临时, self.目标)
        finally:
            os.replace = 真replace

        进程 = subprocess.run([str(脚本)], capture_output=True, text=True,
                              timeout=10, check=False)
        self.assertEqual(进程.returncode, 0, f"旧环境脚本应仍可执行: {进程.stderr}")
        self.assertIn("旧环境 v1 哨兵", 脚本.read_text(encoding="utf-8"))

    def test_成功路径_新环境顶位且旧环境被清理(self) -> None:
        """反向边界：正常路径不得因为本次守护而退化成「旧环境永不替换」。"""
        self.造旧环境()
        self.造新环境()
        原子落盘(self.临时, self.目标)
        self.assertEqual((self.目标 / 环境文件).read_text(encoding="utf-8"), 新环境哨兵)
        self.assertFalse((self.目标 / "标记.txt").exists(), "顶位成功后旧环境残留应被清理")
        self.assertEqual(self.让位残留(), [])


class Test反向_修复前实现必红(原子落盘夹具):
    """反向验证：换成修复前实现，同场景下旧环境必然丢失（证明用例是「活」的）。"""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.修复前 = 加载修复前实现()
        except Exception as 错误:  # git 不可用/历史缺失 ⇒ 如实跳过，不伪装通过
            raise unittest.SkipTest(f"取不到修复前实现基线（{修复前基线}）：{错误}")

    def test_反向_修复前实现_顶位失败即丢旧环境(self) -> None:
        self.造旧环境()
        self.造新环境()
        self.装顶位失败补丁()
        try:
            with self.assertRaises(OSError):
                self.修复前.原子落盘(self.临时, self.目标)
        finally:
            os.replace = 真replace

        self.assertFalse(self.目标.exists(),
                         "修复前实现（先 rmtree 再 replace）应已删掉旧环境；"
                         "若这里为真，说明反向验证失效（用例不再能变红）")
        self.assertFalse((self.目标 / 环境文件).exists(), "旧环境哨兵不应还在")


if __name__ == "__main__":
    unittest.main()
