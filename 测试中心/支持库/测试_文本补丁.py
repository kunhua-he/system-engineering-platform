"""文本补丁支持库：声明根目录路径边界（正向合法 + 越界反向）真实返回值测试。

全部用例在临时目录里造真实文件、真实符号链接，落盘走真实实现（不 mock）：
正向必须真的改到文件；越界必须返回 `路径越界` 且磁盘上原文件一字未动。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.后端.文件系统支持库.文本补丁 import (  # noqa: E402
    应用精确替换,
    计算文本摘要,
    解析代码补丁,
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
        写入: bool = True,
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
        结果 = self._替换(self.根内文件, 写入=False)
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
        结果 = self._替换(self.根外文件, 写入=False)
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


if __name__ == "__main__":
    unittest.main()
