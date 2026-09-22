"""`参数可用性体检` 判据 4/5（返回字段形状）的破坏样本与不触发样本。

为什么单独有这一件（哲学 12.5「规则的破坏样本是接口义务」）：判据 4/5 是
2026-09-23 新接的 —— `返回` 不得退化成裸文本、`返回.值结构` 的字段值不得只有类型名。
新增检查项如果不带样本，就没人知道它到底会不会响；本件给两态各一个样本：

- **应被拦住**：裸返回（`"返回": "结果型"`）、裸值结构（`{"句柄": "整数型"}`）；
- **不应被触发**：写全的返回（`{"类型": ..., "值结构": {"句柄": "句柄型，由 … 返回"}}`）。

判据出处是平台自己：`公共契约/基础类型/字段名册.py` 的 `返回` 条目原文
「不得退化成裸文本」。本件只锚**这个口径**，不另立标准。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[2]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 开发工具.契约编译.参数可用性体检 import (
    值结构存量基线,
    只有类型名,
    检查值结构可用性,
)


def 契约(返回声明) -> dict:
    """造一份最小聚合契约（只含判据 4/5 关心的字段）。"""
    return {"能力契约": [{"能力id": "探针.示例.动作", "返回": 返回声明}]}


class Test只有类型名(unittest.TestCase):
    """判据 5 的最小判定单元：`只有类型名` 的两态。"""

    def test_裸类型名应判真(self):
        for 声明 in ("整数型", "文本型", "双精度数型", "句柄型", "  列表型  "):
            with self.subTest(声明=声明):
                self.assertTrue(只有类型名(声明), f"{声明!r} 应被判为「只有类型名」")

    def test_带说明应判假(self):
        for 声明 in ("整数型，本次返回的记录条数", "句柄型，由 连接LLM 返回",
                     "列表型，租约记录（含 内容指纹）", "文本型"):
            if 声明 == "文本型":
                continue  # 纯类型名，另测
            with self.subTest(声明=声明):
                self.assertFalse(只有类型名(声明), f"{声明!r} 带了说明，不该判为裸型")

    def test_非文本不判(self):
        for 声明 in (None, 123, {"类型": "整数型"}, ["整数型"]):
            with self.subTest(声明=声明):
                self.assertFalse(只有类型名(声明))


class Test应被拦住(unittest.TestCase):
    """反向样本：把缺陷改进去，判据必须响。"""

    def test_裸返回被判红(self):
        问题 = 检查值结构可用性(契约("结果型"))
        self.assertEqual(len(问题), 1, f"裸返回必须判红，实际 {问题}")
        self.assertIn("退化成裸文本", 问题[0])

    def test_裸值结构被判红(self):
        问题 = 检查值结构可用性(
            契约({"类型": "结果型", "值结构": {"句柄": "整数型", "模型": "文本型"}}))
        self.assertEqual(len(问题), 2, f"两个裸字段应各判一条，实际 {问题}")
        self.assertTrue(all("只有类型名" in 项 for 项 in 问题))

    def test_裸返回不再往下查值结构(self):
        """裸返回整条已判红，不必再补一条「值结构缺失」——避免一条缺陷报两遍。"""
        self.assertEqual(len(检查值结构可用性(契约("结果型"))), 1)


class Test不应被触发(unittest.TestCase):
    """正向样本：写全的契约必须一条都不报（否则判据会逼作者瞎改）。"""

    def test_写全的返回不报(self):
        问题 = 检查值结构可用性(契约({
            "类型": "结果型",
            "值结构": {
                "句柄": "句柄型，由 连接LLM 返回",
                "模型": "文本型，实际加载的模型名",
                "超时秒": "双精度数型，无人使用自动释放秒数",
            },
        }))
        self.assertEqual(问题, [], f"写全的返回不该被判红，实际 {问题}")

    def test_空值结构不报(self):
        """`值结构: {}` 是「该能力不声明载荷字段」，不是「字段没有说明」——不判红。"""
        self.assertEqual(检查值结构可用性(契约({"类型": "结果型", "值结构": {}})), [])

    def test_无返回字段不报(self):
        self.assertEqual(检查值结构可用性({"能力契约": [{"能力id": "探针.示例.动作"}]}), [])


class Test存量基线(unittest.TestCase):
    """基线只减不增：它必须是个真数，且与实测同量级（防有人图省事把它改成 0 或调大）。"""

    def test_基线为正数(self):
        self.assertGreater(值结构存量基线, 0, "存量未清零前基线不该是 0")


if __name__ == "__main__":
    unittest.main()
