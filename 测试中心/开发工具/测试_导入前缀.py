"""导入前缀/取系统根共享判据测试（债务 #218）：锚目录判据 + 垫片不得再按层数取根。

被测对象是 `公共契约/运行时/导入前缀`（纯函数）。**为什么要锚目录判据**：后端腿的垫片
埋在 `支持库/后端/<支持库>/[<子包>/]实现/` 下，深度**不一致**（有的 `parents[4]`、
有的 `parents[5]`），照层数写就有一半是错的、且改目录结构时静默指错树；锚目录判据
（同时含 `支持库` 与 `模块库` 的最近祖先）与深度无关。

**自举段的形状**：有 5 个子进程入口 + 2 个模板生成器在**平台模块不可导入**的时刻取根，
只能内联标准库判据。重复不可消除，故改为**可被机器检出**（本文件钉住形状）——
哲学 1.2 的可校验形态，而不是靠记性。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时.导入前缀 import (  # noqa: E402
    根锚目录表,
    取根前缀,
    取系统根,
)

后端根 = 系统根 / "支持库" / "后端"
共享模块 = 系统根 / "公共契约" / "运行时" / "导入前缀.py"

#: 自举段唯一形状（模块级与函数内两式；逐字与各现场相同）。
自举生成器行 = "祖先 for 祖先 in Path(__file__).resolve().parents"
自举锚判据 = 'if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir()'
自举段豁免注释 = "自举前只能用标准库"


def _后端源码() -> list[Path]:
    return sorted(后端根.rglob("*.py"))


def _自举段文件() -> dict[str, str]:
    """**靠生成器行**认出自举段，不靠锚判据行。

    为什么不能用锚判据行认（实测踩到）：那样一来「把锚判据那行删掉」会让文件**退出population**
    而不是被判红 —— 判据从「检出分叉」退化成「数够几个就算过」，正是空判据的形态。
    生成器行 `祖先 for 祖先 in Path(__file__).resolve().parents` 是自举段不可省的骨架
    （删了它就取不到根），拿它认的population 才不会被「削弱判据」的操作躲过去。
    """
    出: dict[str, str] = {}
    for 文件 in _后端源码():
        文本 = 文件.read_text(encoding="utf-8", errors="replace")
        if 自举生成器行 in 文本:
            出[str(文件.relative_to(系统根))] = 文本
    return 出


class 导入前缀测试(unittest.TestCase):
    """取根前缀：源码树前缀为空串、制品为 `平台客户端.`。"""

    def test_源码树模块名取空前缀(self) -> None:
        self.assertEqual(取根前缀("支持库.后端.版本控制支持库.Git操作.实现.提交回滚"), "")
        self.assertEqual(取根前缀("模块库.自修复工具.实现.构建制品"), "")
        self.assertEqual(取根前缀("技能库.后端.技能库.实现.运行技能包"), "")
        self.assertEqual(取根前缀("平台控制面.包仓库.实现.制品保留"), "")

    def test_制品模块名取平台客户端前缀(self) -> None:
        for 名 in ("平台客户端.支持库.适配层.Git提供者.实现.提交回滚",
                  "平台客户端.模块库.自修复工具.实现.构建制品",
                  "平台客户端.技能库.后端.技能库.实现.运行技能包",
                  "平台客户端.平台控制面.包仓库.实现.制品保留"):
            self.assertEqual(取根前缀(名), "平台客户端.", 名)

    def test_非本仓模块名取空(self) -> None:
        """`__main__`、第三方模块名里没有正式根段，必须回空串而不是抛错。"""
        for 名 in ("", "__main__", "unittest.loader", "支持库x.某包", "os.path"):
            self.assertEqual(取根前缀(名), "", 名)

    def test_源码层名在前不算制品前缀(self) -> None:
        """`测试中心.支持库.…` 形状相似但**不是**制品：它的前缀不存在，回空串才对。"""
        self.assertEqual(取根前缀("测试中心.支持库.测试_某件"), "")
        self.assertEqual(取根前缀("示例项目.支持库.某件"), "")

    def test_拼接后能命中两种形态的唯一实现名(self) -> None:
        真身 = "支持库.适配层.某提供者.实现.真身"
        self.assertEqual(取根前缀("平台客户端.支持库.后端.某包.实现.垫片") + 真身,
                         "平台客户端." + 真身)
        self.assertEqual(取根前缀("支持库.后端.某包.实现.垫片") + 真身, 真身)


class 取系统根测试(unittest.TestCase):
    """取系统根：按锚目录判据，与文件所在深度无关。"""

    def test_深浅两种深度都取到同一个仓库根(self) -> None:
        深 = 系统根 / "支持库" / "后端" / "文档转换支持库" / "PDF渲染" / "实现" / "提供者.py"
        浅 = 系统根 / "支持库" / "后端" / "记忆支持库" / "实现" / "记忆.py"
        self.assertEqual(取系统根(深), 系统根)
        self.assertEqual(取系统根(浅), 系统根)
        # 两者按层数算分别是 parents[5] 与 parents[4] —— 这正是不能用层数的理由
        self.assertNotEqual(len(深.parents), len(浅.parents))

    def test_制品形态同样取到锚目录根(self) -> None:
        """制品里锚目录仍是 `支持库`＋`模块库`，故判据在制品形态下逐字成立。"""
        制品内 = (系统根 / "工程缓存" / "制品仓库" / "平台客户端环境" / "平台客户端"
                 / "平台客户端" / "支持库" / "后端" / "某支持库" / "实现" / "某件.py")
        self.assertEqual(取系统根(制品内).name, "平台客户端")

    def test_锚目录表就是支持库加模块库(self) -> None:
        self.assertEqual(set(根锚目录表), {"支持库", "模块库"})

    def test_找不到锚目录必须报错不许猜(self) -> None:
        """fail-closed：找不到锚就抛错，不许退回某个层数（那会静默指错树）。"""
        with self.assertRaises(ImportError):
            取系统根(Path("/tmp/不存在的树/某包/实现/某件.py"))


def _是按层数取根(值: ast.AST) -> bool:
    """该**表达式本身**是不是「按层数取根」（`…Path(__file__).resolve().parents[N]`）。

    必须是**结构判据**（走 AST 节点），不能拿 `ast.unparse` 的文本找子串：模板生成器会把
    `系统根 = Path(__file__).resolve().parents[2]` 当**字符串内容**写进它生成的测试骨架，
    那种字符串是 `Constant`、内部没有 `Name`/`Subscript` 节点 ⇒ 结构判据天然放过它
    （它在被生成的 `测试中心/模块库/*.py` 里是正确的：`parents[2]` 正是仓库根）。
    文本子串判据会把这条**合法内容**报成违规（实测踩到）。
    """
    有文件锚 = any(isinstance(节点, ast.Name) and 节点.id == "__file__"
                 for 节点 in ast.walk(值))
    if not 有文件锚:
        return False
    for 节点 in ast.walk(值):
        if not isinstance(节点, ast.Subscript):
            continue
        被切 = 节点.value
        if not (isinstance(被切, ast.Attribute) and 被切.attr == "parents"):
            continue
        下标 = 节点.slice
        数字 = 下标.value if isinstance(下标, ast.Constant) else None
        if isinstance(数字, int) and not isinstance(数字, bool) and 数字 >= 2:
            return True
    return False


class 垫片不得再按层数取根测试(unittest.TestCase):
    """判据（#218 处置栏原文）：只许调用共享判据，不许自带按层数推导。"""

    def test_扫描面非空(self) -> None:
        """空扫面会让下面几条断言**空判据通过**（假绿），故先钉住扫描面。"""
        文件表 = _后端源码()
        self.assertGreater(len(文件表), 50, f"扫描面只有 {len(文件表)} 个文件，判据不成立")

    def test_检测器本身能认出按层数取根(self) -> None:
        """先证明检测器不是恒假（否则下一条断言是空判据）。"""
        形状 = ast.parse("系统根 = Path(__file__).resolve().parents[5]").body[0]
        self.assertTrue(_是按层数取根(形状.value))
        浅 = ast.parse("根 = Path(__file__).resolve().parents[1]").body[0]
        self.assertFalse(_是按层数取根(浅.value), "parents[1] 不是「整棵系统根」，不判")
        模板 = ast.parse("文本 = '系统根 = Path(__file__).resolve().parents[5]'").body[0]
        self.assertFalse(_是按层数取根(模板.value), "字符串内容不是真推导，不许误报")
        无关 = ast.parse("系统根 = 取系统根(__file__)").body[0]
        self.assertFalse(_是按层数取根(无关.value))

    def test_无按层数取系统根的赋值(self) -> None:
        """`X = Path(__file__).resolve().parents[N]`（N≥2）不许再有 —— 按层数取根的形状。"""
        违规: list[str] = []
        for 文件 in _后端源码():
            try:
                树 = ast.parse(文件.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            for 节点 in ast.walk(树):
                if not isinstance(节点, (ast.Assign, ast.AnnAssign)):
                    continue
                if 节点.value is None or not _是按层数取根(节点.value):
                    continue
                名称 = ast.unparse(节点.targets[0] if isinstance(节点, ast.Assign)
                                 else 节点.target)
                if "包声明" in ast.unparse(节点.value) or 名称.endswith("包目录"):
                    continue  # 包内相对文件（如 包声明.json）：不是「取系统根」，不判
                违规.append(f"{文件.relative_to(系统根)}:{节点.lineno}: {名称} = "
                           f"{ast.unparse(节点.value)}")
        self.assertEqual(违规, [], "仍有按层数取系统根的赋值：\n  " + "\n  ".join(违规))

    def test_垫片真的调用了共享判据(self) -> None:
        """反向钉子：只断言「没有层数写法」不够 —— 全删掉也能过（空判据）。

        两个population分开钉，各自才是**承重**的：混在一起数总数的话，删掉一个垫片的调用
        会被「另一类够多」补上，判据就不承重了（实测：33 总数里少 1 仍是 32 ≥ 30 ⇒ 静默放过）。
        """
        前缀调用者 = [文件 for 文件 in _后端源码()
                   if "取根前缀(" in 文件.read_text(encoding="utf-8", errors="replace")]
        取根调用者 = [文件 for 文件 in _后端源码()
                   if "取系统根(" in 文件.read_text(encoding="utf-8", errors="replace")]
        self.assertGreaterEqual(len(前缀调用者), 30,
                                f"调用 取根前缀 的文件只有 {len(前缀调用者)} 个，垫片收口不完整")
        self.assertGreaterEqual(len(取根调用者), 3,
                                f"调用 取系统根 的文件只有 {len(取根调用者)} 个，收口不完整")

    def test_锚目录推导只剩共享模块与自举段(self) -> None:
        """判据本体只许在共享模块；其余出现锚目录推导的必须是**标注过的自举段**。

        「标注」= 同一文件里出现 `自举前只能用标准库` —— 这不是形式主义：它区分了
        「真的不能调共享判据」与「图省事又抄了一遍」。没有这个标注，本条会放过任何分叉。
        """
        for 路径, 文本 in sorted(_自举段文件().items()):
            self.assertIn(自举段豁免注释, 文本,
                          f"{路径} 自带锚目录推导却没标注是自举段")
            self.assertIn(自举锚判据, 文本,
                          f"{路径} 有自举骨架但锚判据那行不见了或被改弱（判据不许削弱）")

    def test_自举段形状逐字相同(self) -> None:
        """重复不可消除时，让它**可被机器检出**：自举段的两行判据必须逐字一致。

        改共享模块的口径（`根锚目录表`）却漏改自举段，会让「制品里子进程入口取到的根」
        与「垫片取到的根」悄悄分叉 —— 本断言就是那一次的报错点。
        """
        形状 = _自举段文件()
        self.assertGreaterEqual(len(形状), 5, f"自举段只找到 {len(形状)} 处，判据不成立")
        基准 = {自举锚判据, 自举生成器行}
        for 路径, 文本 in sorted(形状.items()):
            行集 = {行.strip() for 行 in 文本.splitlines()
                  if 自举锚判据 in 行 or 自举生成器行 in 行}
            self.assertEqual(行集, 基准,
                             f"{路径} 的自举段形状与共享模块口径不再逐字同形")

    def test_共享判据口径与自举段同源(self) -> None:
        """自举段写的锚目录字面量必须与共享模块的 `根锚目录表` 一致。"""
        共享文本 = 共享模块.read_text(encoding="utf-8")
        for 名 in 根锚目录表:
            self.assertIn(f'"{名}"', 共享文本, f"共享模块里没有锚目录 {名}")
        self.assertEqual(sorted(f'"{名}"' for 名 in 根锚目录表),
                         ['"支持库"', '"模块库"'])
        for 路径, 文本 in sorted(_自举段文件().items()):
            for 名 in 根锚目录表:
                self.assertIn(f'"{名}"', 文本, f"{路径} 的自举段缺锚 {名}")


def _载入块扫描面() -> list[Path]:
    """可能藏「垫片载入块」的源码面：支持库 + 公共契约（不碰生成物与缓存目录）。"""
    出: list[Path] = []
    for 名 in ("支持库", "公共契约"):
        根 = 系统根 / 名
        if 根.is_dir():
            出.extend(sorted(根.rglob("*.py")))
    return 出


class 垫片载入块收口测试(unittest.TestCase):
    """批 3 R1：转调垫片的 fail-closed 载入块只许在共享模块里存在一份。

    为什么要有它：验收判据「同一块全仓出现次数 = 1」若只靠人工读数，改回去没人拦得住 ——
    与 `自举段形状逐字相同` 同一条哲学：**能收成一处的必须收成一处**，收不掉的才退而
    「可被机器检出」。反向验证的「弄坏 ⇒ 红」就挂在本类上（把块抄回任一垫片即报红）。
    """

    载入块首行 = "if 唯一实现名 not in sys.modules:"
    载入调用 = "载入唯一实现("

    def test_载入块只剩共享模块一处(self) -> None:
        命中 = [文件 for 文件 in _载入块扫描面()
                if self.载入块首行 in 文件.read_text(encoding="utf-8", errors="replace")]
        相对 = [str(文件.relative_to(系统根)) for 文件 in 命中]
        self.assertEqual(相对, ["公共契约/运行时/导入前缀.py"],
                         f"垫片载入块不止共享模块一处（或一处都没有）：{相对}")

    def test_共享载入判据保留fail_closed(self) -> None:
        文本 = 共享模块.read_text(encoding="utf-8")
        self.assertIn("def 载入唯一实现(", 文本, "共享模块里没有 载入唯一实现")
        self.assertIn("raise ImportError", 文本, "共享载入判据丢了 fail-closed（缺失即明确报错）")

    def test_垫片都改调共享载入(self) -> None:
        调用者 = [文件 for 文件 in _后端源码()
                 if self.载入调用 in 文件.read_text(encoding="utf-8", errors="replace")]
        self.assertGreaterEqual(len(调用者), 30,
                                f"调用 载入唯一实现 的垫片只有 {len(调用者)} 个，收口不完整")


if __name__ == "__main__":
    unittest.main()
