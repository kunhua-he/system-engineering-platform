"""前端核心调用入口必须绑定统一能力调用器。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parents[2]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

from 前端核心.前端核心 import 前端核心


class 假统一调用器:
    def 调用能力(self, 能力id: str, 参数: dict):
        return {"成功": True, "能力id": 能力id, "参数": 参数}


class 测试前端核心唯一调用(unittest.TestCase):
    def test_裸函数不能作为能力执行入口(self) -> None:
        前端 = 前端核心()
        with self.assertRaisesRegex(TypeError, "调用能力"):
            前端.设置调用入口(lambda *_: {"成功": True})

    def test_统一调用器对象可以作为能力执行入口(self) -> None:
        前端 = 前端核心()
        前端.设置调用入口(假统一调用器())
        返回 = 前端.调用后端能力("测试.能力", {"参数": 1})
        self.assertTrue(返回["成功"])
        self.assertEqual(返回["能力id"], "测试.能力")


if __name__ == "__main__":
    unittest.main()
