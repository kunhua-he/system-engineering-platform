"""解压「中途失败」的数据保持与可恢复负路径断言（开工ID：20260918-负路径5类断言）。

对应外部审计报告①-8 的两条负路径（JSON 验证场景表达不了「注入失败」，故落在 Python 测试）：

1. **目标文件失败后逐字不变**：目标位置已有文件 → 触发一次**必然中途失败**的解压
   （归档成员 CRC 与实际字节不符，落盘读到该成员时抛错）→ 断言原文件**字节逐字未变**。
2. **目录第二项失败可恢复**：多条目解压，让**第二项**失败 → 断言本次新建的第一项
   **已回滚**，且调用方既有内容既不被误删也不被留成半截。

失败注入手法：写一个合法 zip，再把某个成员的**内容字节**改掉而 CRC 不变 ——
`zipfile` 解码到该成员时必然 `Bad CRC-32`，属真实失败，不是假桩。

反向（必红）手法：把 `支持库/后端/文件系统支持库/文件操作/实现/文件系统补充.py` 从
**修复前的 git 基线**（`5bb174c0^`，即「数据丢失两件」立案时的实现）取出来加载，
同一场景下断言调用方原文件**必然丢失** —— 证明本文件的用例是「活」的：换回旧实现即红。
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.文件系统支持库.文件操作 import 解压文件  # noqa: E402

系统根 = Path(__file__).resolve().parents[2]
修复前基线 = "5bb174c0^"
占位符 = b"XXXXXX"
破坏后 = b"YYYYYY"


def 造中途失败包(包路径: Path, 成员列表: list[tuple[str, str]]) -> None:
    """写合法 zip 后破坏**最后一个成员**的字节 → 解压到它时 CRC 必失败。

    为什么按内容而非按 CRC 字段改：`zipfile` 解压时用归档里记录的 CRC 校验解出来的
    字节，内容变而 CRC 不变 ⇒ 必然 `Bad CRC-32`；这是真实解码失败，不需要任何桩。
    """
    with zipfile.ZipFile(包路径, "w") as 压缩包:
        for 名称, 内容 in 成员列表:
            压缩包.writestr(名称, 内容)
    数据 = bytearray(包路径.read_bytes())
    位置 = 数据.find(占位符)
    if 位置 < 0:
        raise AssertionError("夹具必须有 XXXXXX 占位符")
    数据[位置:位置 + len(占位符)] = 破坏后
    包路径.write_bytes(bytes(数据))


def 加载修复前实现():
    """把修复前的实现文件从 git 取出、落到 /tmp 并加载（只读历史，不改工作区）。"""
    源码 = subprocess.run(
        ["git", "show", f"{修复前基线}:支持库/后端/文件系统支持库/文件操作/实现/文件系统补充.py"],
        cwd=str(系统根), capture_output=True, text=True, check=True).stdout
    临时 = Path(tempfile.mkdtemp(prefix="解压反向验证_")) / "修复前文件系统补充.py"
    临时.write_text(源码, encoding="utf-8")
    规格 = importlib.util.spec_from_file_location("修复前文件系统补充", 临时)
    if 规格 is None or 规格.loader is None:
        raise RuntimeError("修复前实现无法构造导入规格")
    模块 = importlib.util.module_from_spec(规格)
    sys.modules["修复前文件系统补充"] = 模块
    规格.loader.exec_module(模块)
    return 模块


class 解压失败夹具(unittest.TestCase):
    """统一临时根；每个用例一个独立目录，互不干扰。"""

    def setUp(self) -> None:
        self.根 = Path(tempfile.mkdtemp(prefix="解压失败数据保持_"))

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.根, ignore_errors=True)

    def 中转件(self, 目标: Path) -> list[str]:
        return sorted(项.name for 项 in 目标.rglob("*.tmp"))

    def 备份残留(self, 起点: Path) -> list[str]:
        return sorted(项.name for 项 in 起点.rglob(".__解压备份_*"))


class Test目标文件失败后逐字不变(解压失败夹具):
    """① 目标文件已存在 + 解压中途失败 ⇒ 原文件字节逐字未变。"""

    def test_目标文件已存在_中途失败_哨兵字节逐字未变(self) -> None:
        目标 = self.根 / "产物"
        目标.mkdir()
        哨兵 = "调用方原始内容-不可丢-哨兵1"
        原件 = 目标 / "数据.txt"
        原件.write_text(哨兵, encoding="utf-8")
        写前字节 = 原件.read_bytes()

        包 = self.根 / "必然失败.zip"
        造中途失败包(包, [("数据.txt", "被解压覆盖的新内容"), ("坏.bin", "XXXXXX")])

        结果 = 解压文件(源路径=str(包), 目标目录=str(目标))

        # 结构：必须如实判失败且错误码明确（不是「成功但内容被换掉」）
        self.assertFalse(结果.成功, "归档 CRC 与实际不符 ⇒ 解压必须失败")
        self.assertEqual(结果.错误码, "解压失败", f"错误说明: {结果.错误说明}")
        # 真实副作用：逐字比对（不是「文件还在」这种弱断言）
        self.assertTrue(原件.is_file(), "调用方目标文件不得消失")
        self.assertEqual(原件.read_bytes(), 写前字节, "目标文件字节必须逐字未变")
        self.assertEqual(原件.read_text(encoding="utf-8"), 哨兵)
        # 失败不得留半截：不留中转件、不留备份目录
        self.assertEqual(self.中转件(目标), [], "失败后不得残留 .tmp 中转件")
        self.assertEqual(self.备份残留(self.根), [], "成功回滚后不得残留备份目录")
        self.assertEqual(sorted(项.name for 项 in 目标.iterdir()), ["数据.txt"],
                         "目标目录内容必须回到失败前（不新增半截产物）")

    def test_目标位置是既有文件且同级还有别的文件_只动自己碰过的(self) -> None:
        """同一目录里还有**本次归档没提到**的调用方文件 → 必须原样保留。"""
        目标 = self.根 / "产物"
        目标.mkdir()
        无关 = 目标 / "无关文件.txt"
        无关.write_text("本次归档不涉及我", encoding="utf-8")
        原件 = 目标 / "数据.txt"
        原件.write_text("既有内容", encoding="utf-8")

        包 = self.根 / "必然失败.zip"
        造中途失败包(包, [("数据.txt", "覆盖内容"), ("坏.bin", "XXXXXX")])
        结果 = 解压文件(源路径=str(包), 目标目录=str(目标))

        self.assertEqual(结果.错误码, "解压失败")
        self.assertEqual(无关.read_text(encoding="utf-8"), "本次归档不涉及我",
                         "本次归档未提到的调用方文件不得被动")
        self.assertEqual(原件.read_text(encoding="utf-8"), "既有内容")


class Test目录第二项失败可恢复(解压失败夹具):
    """② 多条目解压让第二项失败 ⇒ 第一项已写入的内容可回滚/不误删调用方内容。"""

    def test_第二项失败_本次新建的第一项已回滚(self) -> None:
        目标 = self.根 / "产物"
        目标.mkdir()
        调用方 = 目标 / "调用方.txt"
        调用方.write_text("调用方原内容", encoding="utf-8")

        包 = self.根 / "第二项失败.zip"
        造中途失败包(包, [("第一项.txt", "第一项已写入内容"), ("坏.bin", "XXXXXX")])

        结果 = 解压文件(源路径=str(包), 目标目录=str(目标))

        self.assertEqual(结果.错误码, "解压失败")
        # 第一项确实被写过 → 失败后必须回滚（本次新建的，可以删）
        self.assertFalse((目标 / "第一项.txt").exists(), "本次新建的第一项必须回滚，不留半截")
        # 调用方既有内容不得被误删
        self.assertEqual(调用方.read_text(encoding="utf-8"), "调用方原内容")
        self.assertEqual(sorted(项.name for 项 in 目标.iterdir()), ["调用方.txt"],
                         "目标目录应回到失败前状态")
        self.assertEqual(self.中转件(目标), [])

    def test_第二项失败_第一项覆盖过的既有文件按备份逐字还原(self) -> None:
        """第一项**覆盖**了调用方既有文件（这一步已成功），第二项失败 ⇒ 必须逐字还原。"""
        目标 = self.根 / "产物"
        目标.mkdir()
        原件 = 目标 / "既有.txt"
        写前 = "既有原件内容-不可丢-哨兵2"
        原件.write_text(写前, encoding="utf-8")

        包 = self.根 / "第二项失败.zip"
        造中途失败包(包, [("既有.txt", "归档里的新内容"), ("坏.bin", "XXXXXX")])

        结果 = 解压文件(源路径=str(包), 目标目录=str(目标))

        self.assertEqual(结果.错误码, "解压失败")
        self.assertTrue(原件.is_file(), "被覆盖过的调用方文件必须还原回原路径")
        self.assertEqual(原件.read_text(encoding="utf-8"), 写前, "还原必须逐字一致")
        self.assertEqual(self.备份残留(self.根), [], "还原后备份目录不得残留")

    def test_第二项失败_新建目标目录整棵回滚不留空壳(self) -> None:
        目标 = self.根 / "本次才建的目录"
        包 = self.根 / "第二项失败.zip"
        造中途失败包(包, [("第一项.txt", "第一项已写入内容"), ("坏.bin", "XXXXXX")])

        结果 = 解压文件(源路径=str(包), 目标目录=str(目标))

        self.assertEqual(结果.错误码, "解压失败")
        self.assertFalse(目标.exists(), "目标目录是本次新建的 ⇒ 失败必须整棵回滚，不留空壳")
        self.assertEqual(sorted(项.name for 项 in self.根.iterdir()), ["第二项失败.zip"])

    def test_第二项失败_先成功第一项再失败的顺序真实成立(self) -> None:
        """证明「第二项失败」不是「第一项根本没写」：单成员成功包先跑通同一条落盘链路。"""
        目标 = self.根 / "产物"
        目标.mkdir()
        成功包 = self.根 / "只有第一项.zip"
        with zipfile.ZipFile(成功包, "w") as 压缩包:
            压缩包.writestr("第一项.txt", "第一项已写入内容")
        成功结果 = 解压文件(源路径=str(成功包), 目标目录=str(目标))
        self.assertEqual(成功结果.错误码, "", f"同链路应能正常落盘: {成功结果.错误说明}")
        self.assertEqual((目标 / "第一项.txt").read_text(encoding="utf-8"), "第一项已写入内容")


class Test反向_修复前实现必红(解压失败夹具):
    """反向验证：把实现换成修复前基线，同场景必须丢数据（证明用例是「活」的）。"""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.修复前 = 加载修复前实现()
        except Exception as 错误:  # git 不可用/历史缺失 ⇒ 如实跳过，不伪装通过
            raise unittest.SkipTest(f"取不到修复前实现基线（{修复前基线}）：{错误}")

    def test_反向_修复前实现_目标文件被覆盖后失败即丢失(self) -> None:
        目标 = self.根 / "产物"
        目标.mkdir()
        原件 = 目标 / "数据.txt"
        原件.write_text("调用方原始内容-不可丢", encoding="utf-8")

        包 = self.根 / "必然失败.zip"
        造中途失败包(包, [("数据.txt", "新内容"), ("坏.bin", "XXXXXX")])

        结果 = self.修复前.解压文件(源路径=str(包), 目标目录=str(目标))

        # 旧实现的形态：回滚把自己覆盖过的调用方文件当「本次写入」删掉
        self.assertEqual(结果.错误码, "解压失败", "旧实现同样报失败——差别在数据")
        self.assertFalse(原件.exists(),
                         "旧实现应丢掉调用方原文件；若这里为真，说明反向验证失效（用例不再能变红）")

    def test_反向_修复前实现_第二项失败时既有文件同样丢失(self) -> None:
        目标 = self.根 / "产物"
        目标.mkdir()
        原件 = 目标 / "既有.txt"
        原件.write_text("既有原件内容-不可丢", encoding="utf-8")

        包 = self.根 / "第二项失败.zip"
        造中途失败包(包, [("既有.txt", "覆盖内容"), ("坏.bin", "XXXXXX")])

        结果 = self.修复前.解压文件(源路径=str(包), 目标目录=str(目标))

        self.assertEqual(结果.错误码, "解压失败")
        self.assertFalse(原件.exists(),
                         "旧实现应在第二项失败时丢掉被第一项覆盖的既有文件")


if __name__ == "__main__":
    unittest.main()
