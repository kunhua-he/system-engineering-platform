"""能力目录模块定向测试：经 后端核心 装配后真实调用两个公开能力。

硬边界（第 12 条 1 项）：本文件只做单能力定向冒烟，不跑发布门禁与全量测试；
调用链一律走 后端核心(项目根).启动() → 后端核心.调用(能力id, 参数)，
不直接 获取能力调用器()（未装配会报 E未装配）。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.能力目录 import 搜索能力, 读取能力, 注册能力

搜索能力id = "能力目录.搜索能力"
读取能力id = "能力目录.读取能力"
旧实现字段 = (
    "能力id", "中文名称", "说明", "参数", "返回结构", "错误码",
    "版本", "提供者", "调用示例", "验证状态", "包id", "包名称", "类型", "返回",
)
开发入口字段 = ("能力id", "名称", "包id", "说明", "参数")
十四字段 = (
    "能力id", "中文名", "说明", "参数类型", "必填", "默认值", "返回结构",
    "错误码", "调用示例", "权限", "资源预算", "依赖", "版本", "最近成功验证",
)


class 能力目录测试基类(unittest.TestCase):
    """共享一次装配：整套定向测试复用同一后端实例。"""

    后端: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from 后端核心.后端核心 import 后端核心

        cls.后端 = 后端核心(系统根)
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise AssertionError(f"后端核心装配失败: {启动结果.错误码} {启动结果.错误说明}")


class 装配与注册测试(能力目录测试基类):
    def test_公开入口可导入(self):
        for 能力名 in ["搜索能力", "读取能力"]:
            self.assertTrue(callable(globals()[能力名]), f"{能力名} 未从公开入口导出")

    def test_注册能力齐全(self):
        from 公共契约.能力契约.契约 import 能力注册表

        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in [搜索能力id, 读取能力id]:
            self.assertIn(能力id, 注册表.能力id列表)

    def test_装配后两个能力都在注册表(self):
        for 能力id in [搜索能力id, 读取能力id]:
            self.assertIsNotNone(self.后端.注册表.获取(能力id), f"{能力id} 未装配")

    def test_直接调用未装配调用器_as_fallback_返回统一结果(self):
        """不经后端核心直接调用模块函数：仍返回统一结果（不抛异常）。"""
        返回值 = 搜索能力("能力目录.搜索能力", 5)
        self.assertIsInstance(返回值, 结果)


class 搜索能力测试(能力目录测试基类):
    def 搜索(self, 关键词: str, 限制: int) -> 结果:
        return self.后端.调用(搜索能力id, {"关键词": 关键词, "限制": 限制})

    def test_关键词命中自身能力(self):
        调用结果 = self.搜索("能力目录.搜索能力", 5)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        值 = 调用结果.值
        self.assertEqual("能力目录.搜索能力", 值["关键词"])
        self.assertEqual(5, 值["限制"])
        # 命中数不写死：读取能力的参数说明里也写着「例如 能力目录.搜索能力」，
        # 整条记录子串匹配（与旧两道实现同口径）会把那条一并命中。
        self.assertGreaterEqual(值["返回数"], 1)
        self.assertLessEqual(值["返回数"], 值["总数"])
        自命中 = [记录 for 记录 in 值["能力列表"]
                 if 记录["能力id"] == "能力目录.搜索能力"]
        self.assertEqual(1, len(自命中))
        self.assertEqual("搜索能力", 自命中[0]["中文名"])
        for 记录 in 值["能力列表"]:
            self.assertIn("能力目录.搜索能力", json.dumps(记录, ensure_ascii=False))

    def test_空关键词不过滤且被限制截断(self):
        调用结果 = self.搜索("", 100)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        值 = 调用结果.值
        self.assertEqual(100, 值["返回数"])
        self.assertTrue(值["总数"] > 100, f"公开能力总数应大于 100，实测 {值['总数']}")
        self.assertTrue(值["是否截断"] is True)

    def test_限制超上界按边界收敛(self):
        调用结果 = self.搜索("", 5000)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        self.assertEqual(100, 调用结果.值["限制"])
        self.assertEqual(100, 调用结果.值["返回数"])

    def test_限制非整数被拒绝(self):
        调用结果 = self.后端.调用(搜索能力id, {"关键词": "", "限制": "5"})
        self.assertFalse(调用结果.成功)
        self.assertEqual("参数不合法", 调用结果.错误码)

    def test_记录覆盖旧两道检索实现的字段(self):
        调用结果 = self.搜索("能力目录.搜索能力", 1)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        记录 = 调用结果.值["能力列表"][0]
        for 字段 in 旧实现字段 + 开发入口字段 + 十四字段:
            self.assertIn(字段, 记录, f"记录缺少旧实现字段: {字段}")

    def test_不暴露适配层与内部层包(self):
        调用结果 = self.搜索("", 100)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        for 记录 in 调用结果.值["能力列表"]:
            self.assertFalse(记录["包id"].startswith("支持库.适配层."),
                             f"暴露了内部实现边界: {记录['包id']}")

    def test_重复调用结果一致(self):
        第一次 = self.搜索("文件", 3)
        第二次 = self.搜索("文件", 3)
        self.assertTrue(第一次.成功 and 第二次.成功)
        self.assertEqual(json.dumps(第一次.值, ensure_ascii=False, sort_keys=True),
                         json.dumps(第二次.值, ensure_ascii=False, sort_keys=True))


class 读取能力测试(能力目录测试基类):
    def 读取(self, 能力id: str) -> 结果:
        return self.后端.调用(读取能力id, {"能力id": 能力id})

    def test_读取自身完整契约(self):
        调用结果 = self.读取(读取能力id)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        记录 = 调用结果.值
        self.assertEqual(读取能力id, 记录["能力id"])
        self.assertEqual("模块库.能力目录", 记录["包id"])
        self.assertEqual("功能模块", 记录["类型"])
        self.assertEqual(["能力id"], 记录["必填"])
        self.assertEqual("允许用户: *", 记录["权限"])
        self.assertIn("能力不存在", 记录["错误码"])
        self.assertIsInstance(记录["最近成功验证"], str)
        self.assertTrue(记录["最近成功验证"] in ("暂无成功验证记录",)
                        or 记录["最近成功验证"][:2] == "20", 记录["最近成功验证"])
        self.assertIn("有验证场景引用", 记录["验证状态"])

    def test_读取不存在能力明确失败(self):
        调用结果 = self.读取("不存在的能力.测试")
        self.assertFalse(调用结果.成功)
        self.assertEqual("能力不存在", 调用结果.错误码)

    def test_能力id为空被拒绝(self):
        调用结果 = self.读取("   ")
        self.assertFalse(调用结果.成功)
        self.assertEqual("参数不合法", 调用结果.错误码)

    def test_读取结果与搜索结果一致(self):
        搜索值 = self.后端.调用(搜索能力id, {"关键词": "能力目录.读取能力", "限制": 1}).值
        读取值 = self.读取("能力目录.读取能力").值
        关键字 = ("能力id", "中文名", "包id", "版本", "必填", "默认值", "错误码")
        for 字段 in 关键字:
            self.assertEqual(搜索值["能力列表"][0][字段], 读取值[字段], f"{字段} 两处不一致")

    def test_调用示例是可执行示例而非空骨架(self):
        记录 = self.读取("能力目录.搜索能力").值
        示例 = 记录["调用示例"]
        self.assertEqual("能力目录.搜索能力", 示例["能力id"])
        self.assertEqual(["关键词", "限制"], sorted(示例["参数"]))
        for 值 in 示例["参数"].values():
            self.assertIsNotNone(值, "调用示例不应留 None 骨架占位")
        self.assertTrue(记录["调用示例文本"].startswith("能力目录.搜索能力("))
        self.assertNotIn("=None", 记录["调用示例文本"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
