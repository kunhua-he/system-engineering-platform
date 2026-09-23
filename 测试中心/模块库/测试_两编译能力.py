"""两编译能力（静态编译 / 动态编译）的判据与反向验证测试（哲学 7.1）。

哲学 7.1（2026-09-23 华哥裁决）把整个项目的编译/测试面收成**两个公开能力**：
`静态编译`（不带实际数据）与 `动态编译`（静态面 + 实际测试脚本实测）。
本模块锁三件事：

1. **传参形制的 fail-closed**（华哥给的形制：`类型` 0=全仓 / 1=指定库或模块 + `模块ID`）：
   非法取值、全仓档给了 `模块ID`、指定档没给 `模块ID`、类型不是整数 —— **四条全部必须判参数不合法**。
   为什么每条都要单独判：只测一条的话，另三条各自退化成「静默忽略」也发现不了，
   而静默忽略正是华哥点名的病（「传了没反应」）。
2. **两个能力同构、差别只有一处**（哲学 1.2：一类事情只有一条腿）：
   静态档命令里**必须有** `--不跑点名`（只点名不跑测试），动态档**必须没有**（真跑测试）。
   这条锁的是「两个能力别漂成两套实现」。
3. **`缺乏什么导致无法自动自愈` 的归因表是唯一一条腿**：
   归因只在 `编译公共.归因` 一处；静态档与动态档共用它（各自再写一份即第二套判据）。

夹具一律只做**纯函数级**调用（不起编译口、不写仓库任何文件）：判据面在
`编译公共.归一传参` / `归因` / `解析输出` 三个纯函数上，真跑由 MCP 验收（见交付口径）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 模块库.自修复工具.实现 import 编译公共
from 模块库.自修复工具.实现.静态编译 import 静态编译, _分派模块ID
from 模块库.自修复工具.实现.动态编译 import 动态编译


class 传参形制测试(unittest.TestCase):
    """`类型` / `模块ID` 的 fail-closed 四拍（每条非法路径单独断言）。"""

    def test_类型非法取值判参数不合法(self) -> None:
        for 坏值 in (2, -1, 99):
            _, _, 失败 = 编译公共.归一传参(坏值, None)
            self.assertIsNotNone(失败, f"类型={坏值} 必须被拒")
            assert 失败 is not None
            self.assertEqual("参数不合法", 失败.错误码)
            self.assertIn("0（全仓）或 1", str(失败.错误说明))

    def test_类型非整数判参数不合法(self) -> None:
        for 坏值 in ("一", "1", None, 1.5 if False else "全仓"):
            _, _, 失败 = 编译公共.归一传参(坏值, None)
            self.assertIsNotNone(失败, f"类型={坏值!r} 必须被拒（不许猜、不许隐式转换）")
            assert 失败 is not None
            self.assertEqual("参数不合法", 失败.错误码)

    def test_全仓档给了模块ID判参数不合法(self) -> None:
        """★ 静默忽略的反面：`类型=0` 时给了 `模块ID` 必须报错，不许当没看见。

        静默忽略的实测后果：调用方想编 A，实际编了全仓，白跑一轮还看不出为什么。
        """
        _, _, 失败 = 编译公共.归一传参(编译公共.类型全仓, "模块库.自修复工具")
        self.assertIsNotNone(失败)
        assert 失败 is not None
        self.assertEqual("参数不合法", 失败.错误码)
        self.assertIn("模块ID 必须为空", str(失败.错误说明))

    def test_指定档没给模块ID判参数不合法(self) -> None:
        _, _, 失败 = 编译公共.归一传参(编译公共.类型指定, "")
        self.assertIsNotNone(失败)
        assert 失败 is not None
        self.assertEqual("参数不合法", 失败.错误码)
        self.assertIn("模块ID 必填", str(失败.错误说明))

    def test_两条合法路径放行(self) -> None:
        """反向的另一半：合法输入不得被拒（否则上面四条可能是恒拒）。"""
        类型, 条目, 失败 = 编译公共.归一传参(编译公共.类型全仓, None)
        self.assertIsNone(失败)
        self.assertEqual(编译公共.类型全仓, 类型)
        self.assertEqual([], 条目)
        类型, 条目, 失败 = 编译公共.归一传参(编译公共.类型指定, "模块库.自修复工具")
        self.assertIsNone(失败)
        self.assertEqual(编译公共.类型指定, 类型)
        self.assertEqual(["模块库.自修复工具"], 条目)

    def test_模块ID支持换行与列表两种形态(self) -> None:
        _, 条目, 失败 = 编译公共.归一传参(
            编译公共.类型指定, "模块库.自修复工具\n支持库/后端/系统核心支持库/进程管理")
        self.assertIsNone(失败)
        self.assertEqual(["模块库.自修复工具", "支持库/后端/系统核心支持库/进程管理"], 条目)
        _, 条目, 失败 = 编译公共.归一传参(编译公共.类型指定, ["模块库.自修复工具", "  "])
        self.assertIsNone(失败, "列表形态也要支持（空白项丢弃）")
        self.assertEqual(["模块库.自修复工具"], 条目)


class 模块ID分派测试(unittest.TestCase):
    """`模块ID` 逐条分派：含 `/` 走 `--文件`、点分走 `--库`；**混传即拒**。

    为什么混传必须拒：编译口的 `--文件` 与 `--库` 互斥（`add_mutually_exclusive_group`），
    一条命令只能走一种。混着传还放行的话，调用方以为两边都编了，实际只有一边生效。
    """

    def test_仅路径形态(self) -> None:
        文件, 库, 问题 = _分派模块ID(["支持库/后端/系统核心支持库/进程管理"])
        self.assertEqual("", 问题)
        self.assertEqual(["支持库/后端/系统核心支持库/进程管理"], 文件)
        self.assertEqual([], 库)

    def test_仅包id形态(self) -> None:
        文件, 库, 问题 = _分派模块ID(["模块库.自修复工具"])
        self.assertEqual("", 问题)
        self.assertEqual([], 文件)
        self.assertEqual(["模块库.自修复工具"], 库)

    def test_混传即拒(self) -> None:
        文件, 库, 问题 = _分派模块ID(["支持库/后端/系统核心支持库/进程管理",
                                 "模块库.自修复工具"])
        self.assertNotEqual("", 问题, "路径形态与包id 形态同时出现必须拒")
        self.assertIn("互斥", 问题)
        self.assertEqual([], 文件, "拒的时候不得回一半清单（那会被当成「编了这些」）")
        self.assertEqual([], 库)

    def test_多条同类形态放行(self) -> None:
        """反向：同一形态的多条**不得**被误判成混传。"""
        文件, 库, 问题 = _分派模块ID(["模块库/自修复工具", "模块库/能力目录"])
        self.assertEqual("", 问题)
        self.assertEqual(2, len(文件))
        文件, 库, 问题 = _分派模块ID(["模块库.自修复工具", "模块库.能力目录"])
        self.assertEqual("", 问题)
        self.assertEqual(2, len(库))


class 归因唯一腿测试(unittest.TestCase):
    """`缺乏什么导致无法自动自愈` 的归因只有一条腿（两个能力共用）。"""

    def test_归因表可枚举且非空(self) -> None:
        表 = 编译公共.缺乏判据表
        self.assertTrue(表, "归因表为空 ⇒ 归因恒为「未归因」，那一栏就是噪声")
        取值 = {说明 for _, 说明 in 表}
        self.assertIn(编译公共.缺乏_测试模块, 取值)
        self.assertIn(编译公共.缺乏_制品包, 取值)

    def test_认得的失败给出具体缺件(self) -> None:
        self.assertEqual(编译公共.缺乏_测试模块,
                         编译公共.归因("ModuleNotFoundError: 测试中心.某某"))
        self.assertEqual(编译公共.缺乏_制品包,
                         编译公共.归因("基线包缺失：激活制品内无同名包"))
        self.assertEqual(编译公共.缺乏_超时, 编译公共.归因("执行超时 TimeoutExpired"))

    def test_认不得的失败如实说未归因(self) -> None:
        """不许把归不出因的失败硬塞进某一类（那是编原因）。"""
        self.assertEqual(编译公共.缺乏_未归因, 编译公共.归因("某种没人见过的怪错误 abc"))

    def test_两个能力共用同一条归因腿(self) -> None:
        源码 = (系统根 / "模块库" / "自修复工具" / "实现" / "动态编译.py").read_text(encoding="utf-8")
        self.assertIn("编译公共", 源码, "动态编译 必须复用 编译公共 的装配，不得自建第二套")
        self.assertIn("归一传参", 源码)
        self.assertIn("归并结论", 源码)


class 两能力同构测试(unittest.TestCase):
    """静态档只点名、动态档真跑 —— 差别只有命令面那一处。

    判据用 **AST 读实际语句**，不匹配源码文本：源码里注释与 docstring 本来就会写到
    `--不跑点名`（它们解释这个差别），按文本匹配会把注释一起命中（实测教训：
    首版这样写当场假红 2 条 —— 注释里那句话每个字都对，但注释不是命令）。
    """

    @staticmethod
    def _命令列表(文件名: str) -> list[str]:
        """AST 取出该模块里拼 `参数` 列表时**字面量实参**（注释与 docstring 不进 AST）。

        两种赋值形态都要认：`参数 = [...]`（`ast.Assign`）与 `参数: list[str] = [...]`
        （`ast.AnnAssign`）。只认前一种的话，带类型注解的写法会被读成空表 ⇒
        「找不到 --不跑点名」的假红（实测：首版只认 Assign，当场红）。
        """
        import ast
        源码 = (系统根 / "模块库" / "自修复工具" / "实现" / 文件名).read_text(encoding="utf-8")
        字面量: list[str] = []
        for 节点 in ast.walk(ast.parse(源码)):
            if isinstance(节点, ast.Assign):
                目标 = [t.id for t in 节点.targets if isinstance(t, ast.Name)]
                值 = 节点.value
            elif isinstance(节点, ast.AnnAssign) and isinstance(节点.target, ast.Name):
                目标 = [节点.target.id]
                值 = 节点.value
            else:
                continue
            if 目标 != ["参数"] or 值 is None:
                continue
            for 子 in ast.walk(值):
                if isinstance(子, ast.Constant) and isinstance(子.value, str):
                    字面量.append(子.value)
        return 字面量

    def test_静态档固定加不跑点名(self) -> None:
        字面量 = self._命令列表("静态编译.py")
        self.assertIn("--不跑点名", 字面量,
                      "静态编译必须固定加 --不跑点名（不带实际数据跑测试）")

    def test_动态档不得加不跑点名(self) -> None:
        字面量 = self._命令列表("动态编译.py")
        self.assertNotIn("--不跑点名", 字面量,
                         "动态编译不得加 --不跑点名（它的语义就是真跑测试脚本）")

    def test_参数名与形制两能力一致(self) -> None:
        import inspect
        静 = list(inspect.signature(静态编译).parameters)
        动 = list(inspect.signature(动态编译).parameters)
        self.assertEqual(静, 动, "两个能力的参数面必须逐字一致（哲学 7.1：两类共用同一形制）")
        self.assertEqual(["类型", "模块ID", "超时秒", "源码根"], 静)

    def test_返回值形制含华哥要的三项(self) -> None:
        """`成功数量` / `失败数量` / `逐条明细`（每条含「缺乏什么导致无法自动自愈」）。"""
        假输出 = (
            "  [阻断] 摘要闭合 退出码=0 耗时=1.0s：ok\n"
            "  [阻断] 契约漂移 退出码=1 耗时=2.0s：基线包缺失：激活制品内无同名包\n"
            "五态结论：失败 —— 阻断类红项 1\n")
        归并 = 编译公共.归并结论(假输出, "", 1, "cmd", ["模块库/自修复工具"], "/tmp/根")
        self.assertEqual(1, 归并["成功数量"])
        self.assertEqual(1, 归并["失败数量"])
        条 = 归并["逐条明细"][1]
        self.assertEqual("契约漂移", 条["检查项"])
        self.assertEqual(编译公共.缺乏_制品包, 条["缺乏什么导致无法自动自愈"])
        self.assertFalse(条["能否自动自愈"], "缺件类失败不得标成可自愈")
        self.assertTrue(归并["逐条明细"][0]["能否自动自愈"])

    def test_未核验不当通过(self) -> None:
        """解析不出结论 ⇒ 失败数量 ≥ 1（fail-closed：解析不出 ≠ 通过）。"""
        归并 = 编译公共.归并结论("毫无结构的一段文字", "", 0, "cmd", [], "/tmp/根")
        self.assertEqual("未核验", 归并["五态结论"])
        self.assertEqual(0, 归并["成功数量"])
        self.assertGreaterEqual(归并["失败数量"], 1, "未核验必须计入失败，不许当 0 失败蒙过去")


if __name__ == "__main__":
    unittest.main()
