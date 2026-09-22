"""契约升级判定：`检测契约升级` 每次调用都必须能跑（不是抛 NameError）。

背景（2026-09-23 潜伏缺陷复核）：
2026-09-18 把 `开发工具/契约编译/漂移检测.py` 按簇搬成五个内部模块时，
`检测契约升级` 的函数体搬进了 `漂移判定.py`，但它的**唯一依赖** `主版本号`
（`int(str(版本).split(".")[0])`，带 0 兜底）留在了门面文件里 ⇒ 该函数
**一被调用即 `NameError: name '主版本号' is not defined`**（实测），而它正是
`全面漂移检测` 判「契约破坏但未升级主版本」的判据（漂移检测.py 两处调用）。

为什么能潜伏：本仓测试只覆盖 `检测能力定义漂移` / `检测参数漂移` 等判据，
`检测契约升级` 全仓无用例（`测试中心/开发工具/测试_漂移门禁.py` 也不碰它）。
修法＝把 `主版本号` 随其唯一使用者落 `漂移判定.py`，门面按名回托（对外零变化、
不两处定义）；本文件同时锁「门面回托的必须是同一个函数对象」，防回潮成两份实现。

运行（仓库根目录）：
    export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH; unset PYTHONPATH;
    python3.14 -m unittest 测试中心.开发工具.测试_契约升级判定 -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.契约编译.漂移检测 import 主版本号, 检测契约升级, 检测破坏
from 开发工具.契约编译 import 漂移判定


def _契约(版本: str, 参数: list[dict], 错误码: list[str] | None = None) -> dict:
    return {"能力id": "示例.能力", "版本": 版本, "参数": 参数,
            "错误码": 错误码 if 错误码 is not None else ["参数不合法"]}


必填甲 = {"名称": "甲", "类型": "文本型", "必填": True}
必填乙 = {"名称": "乙", "类型": "文本型", "必填": True}


class 契约升级判定(unittest.TestCase):
    def test_主版本号取值与兜底(self):
        self.assertEqual(1, 主版本号("1.0.0"))
        self.assertEqual(3, 主版本号("3.12.7"))
        self.assertEqual(0, 主版本号("不是版本"))
        self.assertEqual(0, 主版本号(None))
        self.assertEqual(0, 主版本号(""))

    def test_门面回托的是同一个函数对象(self):
        """`漂移检测.主版本号` 必须是 `漂移判定.主版本号`（单一实现，门面只回托）。"""
        self.assertIs(漂移判定.主版本号, 主版本号)

    def test_破坏未升主版本判红(self):
        旧 = _契约("1.0.0", [必填甲])
        新 = _契约("1.0.0", [必填甲, 必填乙])
        self.assertIn("新增必填参数", 检测破坏(旧, 新) or "")
        问题 = 检测契约升级(旧, 新)
        self.assertIsNotNone(问题)
        self.assertIn("契约破坏但未升级主版本", 问题)
        self.assertIn("1.0.0 → 1.0.0", 问题)

    def test_破坏已升主版本不判红(self):
        旧 = _契约("1.0.0", [必填甲])
        新 = _契约("2.0.0", [必填甲, 必填乙])
        self.assertIsNone(检测契约升级(旧, 新))

    def test_非破坏变更不判红(self):
        旧 = _契约("1.0.0", [必填甲])
        新 = _契约("1.0.0", [必填甲], 错误码=["参数不合法", "超出限制"])
        self.assertIsNone(检测契约升级(旧, 新))

    def test_缺版本键走零兜底不抛异常(self):
        """版本键缺失/为空时按 0.0.0 兜底（旧判据口径），不得抛异常。"""
        self.assertIsNotNone(检测契约升级({"参数": [必填甲]}, {"参数": [必填甲, 必填乙]}))
        self.assertIsNone(检测契约升级({"参数": [必填甲]},
                                  {"参数": [必填甲, 必填乙], "版本": "1.0.0"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
