"""契约参数漂移判据：名序必须覆盖**全部**参数（必填 + 可选）。

背景（2026-09-23 判据唯一化 ④）：
`开发工具/契约编译/漂移判定.检测参数漂移` 原先只比**必填**参数的相对顺序
（`_必填名序问题(契约必填, 入口参数)`）⇒ **可选参数顺序全仓无判据**。实测
`平台控制面.能力目录.释放文件租约` 契约 `[租约id清单, 原因, 项目根, 存储目录]`
vs 实现签名 `(…, 存储目录, 项目根)` 判 `None`（静默放过）。现改为覆盖全部参数的
相对顺序；纯 `**kwargs` 转发壳（形参名序不是契约面）仍照旧「判不出即不报」。

运行（仓库根目录）：
    export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH; unset PYTHONPATH;
    python3.14 -m unittest 测试中心.开发工具.测试_契约参数漂移全参数名序 -v
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.契约编译.入口定位 import _必填名序问题
from 开发工具.契约编译.漂移检测 import 检测参数漂移



def _契约(参数: list[tuple[str, bool]]) -> dict:
    return {"能力id": "示例.能力",
            "参数": [{"名称": 名, "类型": "文本型", "必填": 必} for 名, 必 in 参数]}


class 契约参数漂移全参数名序测试(unittest.TestCase):
    def setUp(self) -> None:
        self.临时 = Path(tempfile.mkdtemp(prefix="参数漂移_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.临时, ignore_errors=True)

    def _入口(self, 源码: str) -> Path:
        文件 = self.临时 / "入口.py"
        文件.write_text(源码, encoding="utf-8")
        return 文件

    def test_正向_全部参数同序_不漂移(self):
        契约 = _契约([("甲", True), ("乙", False), ("丙", False)])
        入口 = self._入口(
            "def 能力(甲: str, 乙: str = '', 丙: str = '') -> dict:\n    return {}\n")
        self.assertIsNone(检测参数漂移(契约, 入口))

    def test_反向_可选参数顺序颠倒_必须判红(self):
        """盲区复现：乙/丙 都是可选参数，错序必须被抓住（旧必填-only 判据恒绿）。"""
        契约 = _契约([("甲", True), ("乙", False), ("丙", False)])
        入口 = self._入口(
            "def 能力(甲: str, 丙: str = '', 乙: str = '') -> dict:\n    return {}\n")
        漂移 = 检测参数漂移(契约, 入口)
        self.assertIsNotNone(漂移, "可选参数错序必须判红（这正是修前的盲区）")
        self.assertIn("顺序颠倒", 漂移)

    def test_盲区_旧必填口径判据对可选错序恒绿(self):
        """钉住「静默」机理：只比必填的旧判据对 乙/丙 错序一条不报。"""
        入口参数 = ["甲", "丙", "乙"]
        缺失旧, 错序旧 = _必填名序问题(["甲"], 入口参数)
        self.assertEqual((缺失旧, 错序旧), ([], []),
                         "旧必填-only 判据对可选参数错序恒绿")
        缺失全, 错序全 = _必填名序问题(["甲", "乙", "丙"], 入口参数)
        self.assertTrue(错序全, "覆盖全部参数的判据必须看出错序")

    def test_反向_契约参数缺失_必须判红(self):
        契约 = _契约([("甲", True), ("乙", False)])
        入口 = self._入口("def 能力(甲: str) -> dict:\n    return {}\n")
        漂移 = 检测参数漂移(契约, 入口)
        self.assertIsNotNone(漂移)
        self.assertIn("缺失", 漂移)

    def test_纯kwargs转发壳_名序判不出_不报(self):
        """`**kwargs` 纯转发壳的形参名序不是契约面：名序判不出，不报（判不出 ≠ 判红）。"""
        契约 = _契约([("甲", True), ("乙", False)])
        入口 = self._入口("def 能力(**参数):\n    return {}\n")
        self.assertIsNone(检测参数漂移(契约, 入口))

    def test_带具名形参的kwargs_仍照比名序(self):
        契约 = _契约([("甲", True), ("乙", False)])
        入口 = self._入口(
            "def 能力(乙: str = '', 甲: str = '', **参数) -> dict:\n    return {}\n")
        漂移 = 检测参数漂移(契约, 入口)
        self.assertIsNotNone(漂移, "有具名形参者即便同时带 **kwargs 也照比名序")


if __name__ == "__main__":
    unittest.main()
