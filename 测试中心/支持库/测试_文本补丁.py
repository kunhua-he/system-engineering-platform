"""文本补丁支持库：声明根目录路径边界（正向合法 + 越界反向）真实返回值测试。

全部用例在临时目录里造真实文件、真实符号链接，落盘走真实实现（不 mock）：
正向必须真的改到文件；越界必须返回 `路径越界` 且磁盘上原文件一字未动。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 支持库.后端.文件系统支持库.文本补丁 import (  # noqa: E402
    应用精确替换,
    批量应用精确替换,
    计算文本摘要,
    解析代码补丁,
)
from 支持库.后端.文件系统支持库.文本补丁.实现.文本补丁 import (  # noqa: E402
    批量差异上限字符,
    批量编辑上限条数,
)

原文 = "第一行\n旧值在这里\n第三行\n"
替换后 = "第一行\n新值已就位\n第三行\n"


def 取值(结果对象: Any) -> dict[str, Any]:
    """取成功结果的值字典（失败时为空字典，让断言先报失败原因）。"""
    值 = 结果对象.值
    return 值 if isinstance(值, dict) else {}


class 文本补丁路径边界测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="测试_文本补丁_")
        self.临时根 = Path(self._临时.name)
        self.补丁根 = self.临时根 / "补丁根"
        self.补丁根.mkdir(parents=True)
        self.根内文件 = self.补丁根 / "根内目标.txt"
        self.根内文件.write_text(原文, encoding="utf-8")
        self.根外目录 = self.临时根 / "根外目录"
        self.根外目录.mkdir(parents=True)
        self.根外文件 = self.根外目录 / "根外目标.txt"
        self.根外文件.write_text(原文, encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _替换(
        self,
        文件路径: object,
        根目录: str | None = None,
        写入: bool = 真,
        旧文本: str = "旧值在这里",
        预期文件摘要: str = "",
    ):
        return 应用精确替换(
            文件路径=str(文件路径),
            旧文本=旧文本,
            新文本="新值已就位",
            根目录=str(self.补丁根) if 根目录 is None else 根目录,
            预期文件摘要=预期文件摘要,
            写入=写入,
        )

    # ---------- 正向：声明根目录内合法调用 ----------

    def test_根目录内正向替换真实落盘(self) -> None:
        结果 = self._替换(self.根内文件)
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 取值(结果)
        self.assertTrue(值["已写入"])
        self.assertEqual(值["相对路径"], "根内目标.txt")
        self.assertEqual(值["新增行数"], 1)
        self.assertEqual(值["删除行数"], 1)
        self.assertEqual(self.根内文件.read_text(encoding="utf-8"), 替换后)

    def test_根目录内子目录正向替换且相对路径带层级(self) -> None:
        子目录 = self.补丁根 / "二级目录"
        子目录.mkdir()
        目标 = 子目录 / "深层目标.txt"
        目标.write_text(原文, encoding="utf-8")
        结果 = self._替换(目标)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(取值(结果)["相对路径"], "二级目录/深层目标.txt")
        self.assertEqual(目标.read_text(encoding="utf-8"), 替换后)

    def test_根目录写成解析后绝对路径仍通过(self) -> None:
        结果 = self._替换(self.根内文件, 根目录=str(self.补丁根.resolve()))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(取值(结果)["相对路径"], "根内目标.txt")

    def test_根目录为空保持旧行为不校验边界(self) -> None:
        结果 = self._替换(self.根外文件, 根目录="")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(取值(结果)["相对路径"], "根外目标.txt")
        self.assertEqual(self.根外文件.read_text(encoding="utf-8"), 替换后)

    def test_写入假只预览不落盘(self) -> None:
        结果 = self._替换(self.根内文件, 写入=假)
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 取值(结果)
        self.assertFalse(值["已写入"])
        self.assertIn("新值已就位", 值["差异"])
        self.assertEqual(self.根内文件.read_text(encoding="utf-8"), 原文)

    # ---------- 反向：越界必须拒绝 ----------

    def test_相对路径上跳逃逸返回路径越界(self) -> None:
        逃逸路径 = self.补丁根 / ".." / "根外目录" / "根外目标.txt"
        结果 = self._替换(逃逸路径)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")
        self.assertEqual(self.根外文件.read_text(encoding="utf-8"), 原文)

    def test_绝对路径落在根外返回路径越界(self) -> None:
        结果 = self._替换(self.根外文件)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")
        self.assertEqual(self.根外文件.read_text(encoding="utf-8"), 原文)

    def test_根外不存在的路径同样返回路径越界(self) -> None:
        结果 = self._替换(self.根外目录 / "根本没有这个文件.txt")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")

    def test_符号链接逃逸返回路径越界(self) -> None:
        链接 = self.补丁根 / "链接到根外.txt"
        try:
            链接.symlink_to(self.根外文件)
        except (OSError, NotImplementedError) as 错误:  # pragma: no cover
            self.skipTest(f"当前文件系统不支持符号链接: {错误}")
        结果 = self._替换(链接)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")
        self.assertEqual(self.根外文件.read_text(encoding="utf-8"), 原文)

    def test_越界错误说明直接指出越界位置且带详细信息(self) -> None:
        结果 = self._替换(self.根外文件)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")
        说明 = 结果.错误说明
        self.assertIn("路径越界", 说明)
        self.assertIn(str(self.补丁根.resolve()), 说明)
        self.assertIn(str(self.根外文件.resolve()), 说明)
        详情 = 结果.详细信息
        self.assertEqual(详情["声明根目录"], str(self.补丁根.resolve()))
        self.assertEqual(详情["目标路径"], str(self.根外文件.resolve()))
        self.assertEqual(详情["原始文件路径"], str(self.根外文件))

    def test_越界在只读预览模式下同样拒绝(self) -> None:
        结果 = self._替换(self.根外文件, 写入=假)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")

    def test_根目录指向不存在目录时按其为边界拒绝(self) -> None:
        结果 = self._替换(self.根内文件, 根目录=str(self.临时根 / "没有这个根"))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")

    def test_越界判定优先于文件存在性(self) -> None:
        """根外是真实存在的文件：不许报成 文件不存在，也不许照常放行。"""
        结果 = self._替换(self.根外文件)
        self.assertNotEqual(结果.错误码, "文件不存在")
        self.assertEqual(结果.错误码, "路径越界")

    # ---------- 回归：原有错误码与行为不变 ----------

    def test_文件摘要不符仍然拒绝(self) -> None:
        结果 = self._替换(self.根内文件, 预期文件摘要="0" * 64)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件摘要不符")
        self.assertEqual(结果.详细信息["当前文件摘要"], 计算文本摘要(原文))
        self.assertEqual(self.根内文件.read_text(encoding="utf-8"), 原文)

    def test_旧文本不唯一仍然拒绝(self) -> None:
        结果 = self._替换(self.根内文件, 旧文本="行")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "匹配不唯一")

    def test_根内不存在的文件仍然文件不存在(self) -> None:
        结果 = self._替换(self.补丁根 / "没有这个文件.txt")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_空文件路径仍然参数不合法(self) -> None:
        结果 = self._替换("")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    # ---------- 解析代码补丁：越界仍由本包统一错误码表达 ----------

    def test_解析代码补丁根外路径返回路径越界(self) -> None:
        补丁文本 = ("*** Begin Patch ***\n"
                    "*** Add File: ../越界新文件.txt\n"
                    "+内容一\n"
                    "*** End Patch ***")
        结果 = 解析代码补丁(str(self.补丁根), 补丁文本)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径越界")


class 文本补丁批量替换测试(unittest.TestCase):
    """批量应用精确替换：一次改多个文件，先全量内存试算、再逐文件一次原子写。

    全部用例在临时目录里造真实文件、走真实实现（不 mock）：
    「全或无」必须靠**磁盘内容一字未动**证明，不能只看错误码 —— 只看错误码的话，
    一个「先写后报错」的实现同样会绿（那是本能力唯一存在的理由，必须真的验到）。
    """

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="测试_批量替换_")
        self.临时根 = Path(self._临时.name)
        self.批量根 = self.临时根 / "批量根"
        self.批量根.mkdir(parents=True)
        self.文件1 = self.批量根 / "文件1.txt"
        self.文件2 = self.批量根 / "文件2.txt"
        self.文件1.write_text(原文, encoding="utf-8")
        self.文件2.write_text(原文, encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _条目(self, 路径: Path, 旧文本: str = "旧值在这里",
             新文本: str = "新值已就位", **额外) -> dict:
        条目 = {"文件路径": str(路径), "旧文本": 旧文本, "新文本": 新文本}
        条目.update(额外)
        return 条目

    def _批量(self, 编辑列表, 根目录: str | None = None,
             写入: bool = 真, 原子: bool = 真):
        return 批量应用精确替换(
            编辑列表=编辑列表,
            根目录=str(self.批量根) if 根目录 is None else 根目录,
            写入=写入,
            原子=原子,
        )

    # ---------- 正向：一次调用改多个文件 ----------

    def test_两文件一次调用都真实落盘(self) -> None:
        结果 = self._批量([self._条目(self.文件1), self._条目(self.文件2)])
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 取值(结果)
        self.assertEqual(值["总数"], 2)
        self.assertEqual(值["成功数"], 2)
        self.assertEqual(值["失败数"], 0)
        self.assertIs(值["全部成功"], 真)
        self.assertEqual(值["文件数"], 2)
        self.assertEqual(值["已写入文件数"], 2)
        self.assertIs(值["已写入"], 真)
        self.assertEqual(self.文件1.read_text(encoding="utf-8"), 替换后)
        self.assertEqual(self.文件2.read_text(encoding="utf-8"), 替换后)

    def test_同文件两条编辑只写一次且两条都生效(self) -> None:
        结果 = self._批量([
            self._条目(self.文件1, "旧值在这里", "二次改完"),
            self._条目(self.文件1, "第三行", "第四行"),
        ])
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 取值(结果)
        self.assertEqual(值["成功数"], 2)
        self.assertEqual(值["文件数"], 1, "同一文件两条编辑必须并成一个文件组")
        self.assertEqual(值["已写入文件数"], 1, "同一文件只该写一次")
        self.assertEqual(self.文件1.read_text(encoding="utf-8"), "第一行\n二次改完\n第四行\n")
        self.assertEqual(self.文件2.read_text(encoding="utf-8"), 原文, "没点到的文件不许动")

    def test_写入假只试算不落盘(self) -> None:
        结果 = self._批量([self._条目(self.文件1)], 写入=假)
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 取值(结果)
        self.assertIs(值["已写入"], 假)
        self.assertEqual(值["已写入文件数"], 0)
        self.assertEqual(值["成功数"], 1, "写入=假 仍要给出试算结果与差异")
        self.assertEqual(self.文件1.read_text(encoding="utf-8"), 原文)

    def test_预期文件摘要只对同文件第一条生效(self) -> None:
        # 第一条带**正确**的整文件摘要（乐观锁），第二条不带：同一文件两条都应通过。
        # 若实现拿原始摘要去比每一条，第二条必然「文件摘要不符」（锁原文≠锁每一步）。
        结果 = self._批量([
            self._条目(self.文件1, "旧值在这里", "新值已就位",
                    预期文件摘要=计算文本摘要(原文)),
            self._条目(self.文件1, "第三行", "第四行"),
        ])
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(取值(结果)["成功数"], 2)
        self.assertEqual(self.文件1.read_text(encoding="utf-8"), "第一行\n新值已就位\n第四行\n")

    def test_差异超长被截断并标注(self) -> None:
        长文件 = self.批量根 / "长.txt"
        长文件.write_text("A" * 3000 + "\n", encoding="utf-8")
        结果 = self._批量([self._条目(长文件, "A" * 3000, "B" * 3000)])
        self.assertTrue(结果.成功, 结果.错误说明)
        条目 = 取值(结果)["结果表"][0]
        self.assertIs(条目["差异已截断"], 真)
        self.assertLessEqual(len(条目["差异"]), 批量差异上限字符)

    # ---------- 全或无：本能力唯一存在的理由 ----------

    def test_一条定位失败则一条都不写(self) -> None:
        结果 = self._批量([
            self._条目(self.文件1, "旧值在这里", "不该出现"),
            self._条目(self.文件2, "压根不存在的串", "x"),
        ])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "批量未应用")
        失败清单 = 结果.详细信息["失败清单"]
        self.assertEqual(len(失败清单), 1)
        self.assertEqual(失败清单[0]["序号"], 2)
        self.assertEqual(失败清单[0]["错误码"], "未找到匹配")
        # 关键断言：合法的那条**一个字节都没动**（只看错误码会放过「先写后报错」的实现）
        self.assertEqual(self.文件1.read_text(encoding="utf-8"), 原文)
        self.assertEqual(self.文件2.read_text(encoding="utf-8"), 原文)

    def test_一条越界则整体失败且一条不写(self) -> None:
        根外 = self.临时根 / "根外.txt"
        根外.write_text(原文, encoding="utf-8")
        结果 = self._批量([self._条目(self.文件1, "旧值在这里", "不该出现"),
                        self._条目(根外)])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "批量未应用")
        self.assertEqual(结果.详细信息["失败清单"][0]["错误码"], "路径越界")
        self.assertEqual(self.文件1.read_text(encoding="utf-8"), 原文)
        self.assertEqual(根外.read_text(encoding="utf-8"), 原文)

    def test_非原子时能写的写掉失败如实列出(self) -> None:
        结果 = self._批量([
            self._条目(self.文件2, "旧值在这里", "非原子改完"),
            self._条目(self.文件2, "压根不存在的串", "x"),
        ], 原子=假)
        self.assertTrue(结果.成功, 结果.错误说明)
        值 = 取值(结果)
        self.assertEqual(值["成功数"], 1)
        self.assertEqual(值["失败数"], 1)
        self.assertIs(值["全部成功"], 假)
        self.assertEqual(值["已写入文件数"], 1)
        self.assertEqual(self.文件2.read_text(encoding="utf-8"), "第一行\n非原子改完\n第三行\n")

    def test_原子为假时全部成功字段仍是唯一整体判据(self) -> None:
        # 信封 `成功` 是「批次跑完了」，不是「全部应用了」；只看信封会把部分失败读成全部成功。
        结果 = self._批量([
            self._条目(self.文件1),
            self._条目(self.文件2, "压根不存在的串", "x"),
        ], 原子=假)
        self.assertTrue(结果.成功, "原子=假 允许带失败清单返回成功（与 执行命令集 同口径）")
        self.assertIs(取值(结果)["全部成功"], 假, "整体判据必须是 全部成功，不是信封 成功")
        self.assertEqual(self.文件1.read_text(encoding="utf-8"), 替换后)
        self.assertEqual(self.文件2.read_text(encoding="utf-8"), 原文)

    # ---------- 参数校验 ----------

    def test_编辑列表为空被拒(self) -> None:
        for 入参 in ([], None, "不是列表"):
            结果 = 批量应用精确替换(编辑列表=入参)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")

    def test_超过条数上限被拒(self) -> None:
        结果 = self._批量([self._条目(self.文件1) for _ in range(批量编辑上限条数 + 1)])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_条目缺字段被拒(self) -> None:
        用例 = [
            ("不是字典", ["不是字典"]),
            ("文件路径空", [{"文件路径": "", "旧文本": "a", "新文本": "b"}]),
            ("旧文本空", [{"文件路径": str(self.文件1), "旧文本": "", "新文本": "b"}]),
            ("新文本非文本", [{"文件路径": str(self.文件1), "旧文本": "a", "新文本": 1}]),
        ]
        for 名称, 编辑列表 in 用例:
            结果 = 批量应用精确替换(编辑列表=编辑列表)
            self.assertFalse(结果.成功, f"{名称} 应当被拒")
            self.assertEqual(结果.错误码, "参数不合法", 名称)

    def test_逻辑型参数非布尔被拒(self) -> None:
        for 关键字 in ({"写入": 1}, {"原子": "真"}):
            结果 = 批量应用精确替换(编辑列表=[self._条目(self.文件1)], **关键字)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")


_实现路径 = (Path(__file__).resolve().parents[2] / "支持库" / "后端"
         / "文件系统支持库" / "文本补丁" / "实现" / "文本补丁.py")

_全或无闸门 = "    if 原子 and 失败清单:\n"


class 原子写权限保留测试(unittest.TestCase):
    """L8（2026-09-21 批 3）：原子写必须**保留目标文件原有权限位**。

    为什么必须有这条：`tempfile.NamedTemporaryFile` 建的临时文件默认 **0o600**，
    `os.replace` 后**目标权限位就变成 0600** —— 实测 `0644→0600`、`0640→0600`。
    原实现只保证了「原子 + 内容正确」，没保证「权限不变」，而 `.py` 掉权限在共享仓库里会
    变成怪问题（别的会话下一轮改它会写不进去）。
    """

    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory(prefix="测试_权限保留_")
        self.根 = Path(self._临时.name)
        self.目标 = self.根 / "目标.py"
        self.目标.write_text(原文, encoding="utf-8")

    def tearDown(self) -> None:
        self._临时.cleanup()

    def _改一次(self):
        return 应用精确替换(
            文件路径=str(self.目标), 旧文本="旧值在这里", 新文本="新值已就位",
            根目录=str(self.根), 写入=真)

    def test_单文件原子写保留权限位(self) -> None:
        for 权限 in (0o644, 0o640, 0o600, 0o755):
            with self.subTest(权限=oct(权限)):
                self.目标.write_text(原文, encoding="utf-8")
                os.chmod(self.目标, 权限)
                结果 = self._改一次()
                self.assertTrue(结果.成功, 结果.错误说明)
                self.assertEqual(self.目标.read_text(encoding="utf-8"), 替换后)
                实际 = self.目标.stat().st_mode & 0o777
                self.assertEqual(实际, 权限,
                                 f"权限位必须保留：期望 {oct(权限)}，实际 {oct(实际)}")

    def test_批量原子写也保留权限位(self) -> None:
        文件1 = self.根 / "文件1.py"
        文件2 = self.根 / "文件2.py"
        文件1.write_text(原文, encoding="utf-8")
        文件2.write_text(原文, encoding="utf-8")
        os.chmod(文件1, 0o644)
        os.chmod(文件2, 0o640)
        结果 = 批量应用精确替换(
            编辑列表=[{"文件路径": str(文件1), "旧文本": "旧值在这里", "新文本": "新值已就位"},
                   {"文件路径": str(文件2), "旧文本": "旧值在这里", "新文本": "新值已就位"}],
            根目录=str(self.根), 写入=真, 原子=真)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(文件1.stat().st_mode & 0o777, 0o644)
        self.assertEqual(文件2.stat().st_mode & 0o777, 0o640)

    def test_新建文件不报错也不报假权限(self) -> None:
        # 新文件（目标不存在）用系统默认创建权限，不得因为「取不到权限」而失败。
        新文件 = self.根 / "新建.py"
        新文件.write_text("占位\n旧值在这里\n", encoding="utf-8")
        结果 = 应用精确替换(
            文件路径=str(新文件), 旧文本="旧值在这里", 新文本="新值已就位",
            根目录=str(self.根), 写入=真)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertIn("新值已就位", 新文件.read_text(encoding="utf-8"))


class 权限保留反向验证(unittest.TestCase):
    """反向验证：退回「不 chmod、不建对权限」的旧写法，权限判据必须变红。

    没有这层，权限断言可能在**任何**实现下都绿（比如环境 umask 恰好让它碰对）——
    等于没证明 `_目标权限位` + `os.chmod` 真的在起作用（旧实现正是 0644→0600）。
    """

    _补丁源 = Path(__file__).resolve().parents[2] / "支持库" / "后端" / "文件系统支持库" / "文本补丁" / "实现" / "文本补丁.py"
    _chmod行 = "        os.chmod(句柄.name, 权限)\n"

    def _缺陷态模块(self):
        源 = self._补丁源.read_text(encoding="utf-8")
        坏 = 源.replace(self._chmod行, "        pass  # 反向样本：退回旧写法（不把权限带回去）\n")
        if 坏 == 源:
            raise AssertionError("chmod 行未命中，反向样本失效（判据需更新）")
        命名空间: dict = {"__name__": "反向样本_文本补丁", "__file__": str(self._补丁源)}
        exec(compile(坏, str(self._补丁源), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_不退权限后判据变红(self) -> None:
        模块 = self._缺陷态模块()
        with tempfile.TemporaryDirectory(prefix="测试_反验权限_") as 临时:
            根 = Path(临时)
            目标 = 根 / "目标.txt"
            目标.write_text(原文, encoding="utf-8")
            os.chmod(目标, 0o644)
            结果 = 模块["应用精确替换"](
                文件路径=str(目标), 旧文本="旧值在这里", 新文本="新值已就位",
                根目录=str(根), 写入=真)
            self.assertTrue(结果.成功, 结果.错误说明)
            缺陷权限 = 目标.stat().st_mode & 0o777
            # 缺陷态下必须真的掉权限（这正是坏行为）
            self.assertNotEqual(缺陷权限, 0o644,
                                "缺陷态下权限未变，反向样本失效（请检查临时文件默认权限）")
        # 现行实现同一输入必须保住权限 —— 两者结论不同，样本才有效
        with tempfile.TemporaryDirectory(prefix="测试_现行权限_") as 临时:
            根 = Path(临时)
            目标 = 根 / "目标.txt"
            目标.write_text(原文, encoding="utf-8")
            os.chmod(目标, 0o644)
            结果 = 应用精确替换(
                文件路径=str(目标), 旧文本="旧值在这里", 新文本="新值已就位",
                根目录=str(根), 写入=真)
            self.assertTrue(结果.成功, 结果.错误说明)
            self.assertEqual(目标.stat().st_mode & 0o777, 0o644, "现行实现必须保住权限")


class 批量替换反向验证(unittest.TestCase):
    """反向验证：把「全或无」闸门拆掉后，本能力的核心用例必须变红。

    没有这层，`test_一条定位失败则一条都不写` 可能在「先写后报错」的实现下照样绿 ——
    那就等于没证明这道闸门真的在起作用。
    """

    def _缺陷态模块(self):
        源 = _实现路径.read_text(encoding="utf-8")
        坏 = 源.replace(_全或无闸门, "    if False:\n")
        if 坏 == 源:
            raise AssertionError("全或无闸门片段未命中，反向样本失效（判据需更新）")
        命名空间: dict = {"__name__": "反向样本", "__file__": str(_实现路径)}
        exec(compile(坏, str(_实现路径), "exec"), 命名空间)  # noqa: S102
        return 命名空间

    def test_拆掉全或无闸门后必须变红(self) -> None:
        模块 = self._缺陷态模块()
        with tempfile.TemporaryDirectory(prefix="测试_批量反向_") as 目录:
            根 = Path(目录)
            文件1 = 根 / "文件1.txt"
            文件2 = 根 / "文件2.txt"
            文件1.write_text(原文, encoding="utf-8")
            文件2.write_text(原文, encoding="utf-8")
            结果 = 模块["批量应用精确替换"](
                编辑列表=[
                    {"文件路径": str(文件1), "旧文本": "旧值在这里", "新文本": "不该出现"},
                    {"文件路径": str(文件2), "旧文本": "压根不存在的串", "新文本": "x"},
                ],
                根目录=str(根), 写入=真,
            )
            # 缺陷态：闸门没了 ⇒ 合法那条被写下去，工作区停在「改了一半」。
            self.assertEqual(文件1.read_text(encoding="utf-8"), "第一行\n不该出现\n第三行\n",
                           "缺陷态下 文件1 应当被写下去（这正是反向样本要复现的坏行为）")
            self.assertNotEqual(文件1.read_text(encoding="utf-8"), 原文)

    def test_修好后的现行实现不会出现缺陷态行为(self) -> None:
        模块 = self._缺陷态模块()
        with tempfile.TemporaryDirectory(prefix="测试_批量反向_") as 目录:
            根 = Path(目录)
            文件1 = 根 / "文件1.txt"
            文件2 = 根 / "文件2.txt"
            参数 = dict(
                编辑列表=[
                    {"文件路径": str(文件1), "旧文本": "旧值在这里", "新文本": "不该出现"},
                    {"文件路径": str(文件2), "旧文本": "压根不存在的串", "新文本": "x"},
                ],
                根目录=str(根), 写入=真,
            )
            文件1.write_text(原文, encoding="utf-8")
            文件2.write_text(原文, encoding="utf-8")
            缺陷态 = 模块["批量应用精确替换"](**参数)
            # 缺陷态已经动过盘，跑现行实现前必须把夹具复位（否则验的是残留而不是现行实现）。
            文件1.write_text(原文, encoding="utf-8")
            文件2.write_text(原文, encoding="utf-8")
            现行态 = 批量应用精确替换(**参数)
            self.assertNotEqual(缺陷态.成功, 现行态.成功,
                              "反向样本与现行实现的结论必须不同，否则样本失效")
            self.assertFalse(现行态.成功)
            self.assertEqual(文件1.read_text(encoding="utf-8"), 原文)


if __name__ == "__main__":
    unittest.main()
