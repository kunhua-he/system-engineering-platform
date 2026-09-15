"""漂移检测门禁：口径必须与唯一编译器一致，全仓 0 漂移（哲学第 1 条 3 项、第 1 条 4 项）。

历史缺陷（2026-09-15 复核）：`检测能力定义漂移` 调 `生成能力契约(定义)` 时**没传既有契约**，
而编译器是**非破坏性**的（按既有契约保留手写 `中文名称`/`名称`/自定义键、手写 `调用示例`，
契约版本恒等于契约事实源）。于是凡有手写保留键的包一律被误报「能力契约与能力定义不一致」——
实测 **67 包**报红，口径修正后降到 **21 包**（真漂移），重编译对齐后为 **0**。

本门禁锁两件事：
1. 全仓 `检测能力定义漂移` 必须为 0（门禁不许长期红着，第 1 条 4 项）；
2. 口径一致性：对任意包，`生成能力契约(定义, 既有契约)` 与磁盘既有契约必须逐键相同
   （在无真漂移的前提下），保证检测器与编译器同源，不再假报。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.契约编译.漂移检测 import 检测能力定义漂移
from 开发工具.契约编译.能力定义编译器 import 生成能力契约, 读取能力定义

跳过 = ("__pycache__", "工程缓存", "示例项目")


def 全部能力定义():
    for 定义 in sorted(系统根.rglob("能力定义.json")):
        if any(段 in 定义.parts for 段 in 跳过):
            continue
        yield 定义


class 漂移门禁(unittest.TestCase):
    def test_全仓无漂移(self):
        报红 = []
        for 定义 in 全部能力定义():
            问题 = 检测能力定义漂移(定义.parent)
            if 问题:
                报红.append((定义.parent.relative_to(系统根).as_posix(), 问题[0]))
        self.assertEqual([], 报红[:10],
                         f"仍有 {len(报红)} 包漂移（能力定义与派生物不一致，需按事实源重编译）")

    def test_检测口径与编译器同源(self):
        """非破坏性口径：把既有契约传进生成器后，结果必须与磁盘既有契约一致。"""
        不一致 = []
        for 定义 in 全部能力定义():
            契约路径 = 定义.parent / "能力契约" / "参数契约.json"
            if not 契约路径.is_file():
                continue
            既有 = json.loads(契约路径.read_text(encoding="utf-8"))
            期望 = json.loads(生成能力契约(读取能力定义(定义), 既有))
            if 期望 != 既有:
                不一致.append(定义.parent.relative_to(系统根).as_posix())
        self.assertEqual([], 不一致[:10], f"{len(不一致)} 包的契约与「按既有契约再生成」不一致")


if __name__ == "__main__":
    unittest.main()
