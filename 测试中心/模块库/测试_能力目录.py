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

    def 搜索完整契约(self, 关键词: str, 限制: int) -> 结果:
        """按最高档取完整契约：断言「字段齐全」类用例必须显式要这一档。

        2026-09-18 起默认档＝「名称」（只回精简字段，见该能力 `说明` 与
        `说明/设计说明.md`）。旧用例断言的 21 字段面仍然存在，只是**不再默认返回**——
        它们从此必须显式传 细节级别=完整契约，否则测的就不是它自称要测的东西。
        """
        return self.后端.调用(搜索能力id, {"关键词": 关键词, "限制": 限制,
                                    "细节级别": "完整契约"})

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

    def test_默认档只回精简字段且与重字段互斥(self):
        """默认档（不传 细节级别）＝「名称」：只回指针，重字段一律不得出现。

        判据是**与重字段表互斥**，不是「键数等于 5」——只数键数的断言挡不住重字段
        换个名字回流。这里直接拿实现里的 重字段表 当判据（同一份事实，不另抄一遍）。
        """
        from 模块库.能力目录.实现.能力目录 import 精简字段表, 重字段表

        调用结果 = self.搜索("", 100)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        值 = 调用结果.值
        self.assertEqual("名称", 值["细节级别"])
        self.assertEqual(100, 值["返回数"])
        for 记录 in 值["能力列表"]:
            self.assertEqual(set(精简字段表), set(记录),
                             f"{记录['能力id']} 默认档键集不等于精简字段表")
            for 重字段 in 重字段表:
                self.assertNotIn(重字段, 记录,
                                 f"{记录['能力id']} 默认档不得回重字段 {重字段}")
        # 精简字段本身必须有值（不是空壳占位）
        for 记录 in 值["能力列表"]:
            self.assertTrue(记录["能力id"])
            self.assertTrue(记录["名称"])
            self.assertTrue(记录["包id"])
            self.assertTrue(记录["一句话说明"])

    def test_中间档不含重字段且比默认档多说明(self):
        from 模块库.能力目录.实现.能力目录 import 说明字段表, 重字段表

        调用结果 = self.后端.调用(搜索能力id, {"关键词": "OCR", "限制": 5,
                                       "细节级别": "名称+说明"})
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        值 = 调用结果.值
        self.assertEqual("名称+说明", 值["细节级别"])
        self.assertGreater(值["返回数"], 0)
        for 记录 in 值["能力列表"]:
            self.assertEqual(set(说明字段表), set(记录))
            self.assertIn("说明", 记录)
            self.assertTrue(记录["说明"])
            for 重字段 in 重字段表:
                self.assertNotIn(重字段, 记录, f"中间档不得回重字段 {重字段}")

    def test_非法细节级别一律拒绝不静默降级(self):
        """不认识的档位必须报 参数不合法，不得悄悄按默认档返回。

        静默降级会让调用方以为拿到了完整契约、实际只拿到指针。
        """
        for 坏档 in ("完整", "json", "名称+", ""):
            with self.subTest(细节级别=坏档):
                调用结果 = self.后端.调用(搜索能力id, {"关键词": "", "限制": 3,
                                               "细节级别": 坏档})
                if 坏档 == "":
                    # 空文本＝未传，按默认档（向后兼容），不是非法值
                    self.assertTrue(调用结果.成功, 调用结果.错误说明)
                    self.assertEqual("名称", 调用结果.值["细节级别"])
                else:
                    self.assertFalse(调用结果.成功)
                    self.assertEqual("参数不合法", 调用结果.错误码)

    def test_游标翻页三页无重复且合计等于总数(self):
        """游标正确性硬证据：按「每页 总数/3」翻三页，去重后条数 == 合计 == 总数。

        选「总数能被 3 整除」的关键词，三页正好覆盖全集——这样「合计 == 总数」
        才是无遗漏 + 无重复的**充分**证据；否则（如 456 条取 3 页 ×3）恒不等于总数，
        断言写出来就是错的。
        """
        关键词 = "OCR"
        总数 = self.搜索(关键词, 1).值["总数"]
        self.assertGreater(总数, 0)
        self.assertEqual(0, 总数 % 3, f"关键词 {关键词} 的总数 {总数} 需能被 3 整除")
        页大小 = 总数 // 3
        游标 = ""
        汇总: list[str] = []
        for 页号 in range(1, 4):
            with self.subTest(页号=页号):
                值 = self.后端.调用(搜索能力id, {"关键词": 关键词, "限制": 页大小,
                                           "游标": 游标}).值
                self.assertEqual(页大小, 值["返回数"], f"第 {页号} 页应满页")
                汇总.extend(记录["能力id"] for 记录 in 值["能力列表"])
                游标 = 值["下一条游标"]
        self.assertEqual(总数, len(汇总), f"三页合计 {len(汇总)} ≠ 总数 {总数}（漏项）")
        self.assertEqual(len(汇总), len(set(汇总)), "三页出现了重复能力id")
        self.assertEqual(汇总, sorted(汇总), "翻页顺序不是排序键升序（续取位置有误）")
        self.assertEqual("", 游标, "取满全集后不得再给下一条游标")

    def test_游标翻页走完全集与不分页取全逐条一致(self):
        """页大小=100 翻到底：无重复、无遗漏，且与直接取全的 id 序列逐条相同。"""
        页大小 = 100
        游标 = ""
        汇总: list[str] = []
        频次: dict[str, int] = {}
        while True:
            值 = self.后端.调用(搜索能力id, {"关键词": "", "限制": 页大小,
                                       "游标": 游标}).值
            汇总.extend(记录["能力id"] for 记录 in 值["能力列表"])
            游标 = 值["下一条游标"]
            if not 游标:
                break
            频次[游标] = 频次.get(游标, 0) + 1
            self.assertLess(频次[游标], 20, "游标未前进（防死循环保护触发）")
        self.assertEqual(值["总数"], len(汇总), "翻页合计 ≠ 总数")
        self.assertEqual(len(汇总), len(set(汇总)), "翻页出现重复")
        直接一次 = self.搜索("", 100).值["能力列表"]
        self.assertEqual([记录["能力id"] for 记录 in 直接一次], 汇总[:100],
                         "第一页与不分页取法的首百条必须逐条一致")

    def test_伪造游标与换关键词一律拒绝(self):
        """游标不透明：自造的、改了关键词的、"看起来像"的游标全部 fail-closed。

        绝不静默退回「从头开始」——那会把调用方的错变成静默漏项。
        """
        首发 = self.搜索("", 3).值
        真游标 = 首发["下一条游标"]
        self.assertTrue(真游标)
        for 坏游标 in ("我自己拼的游标", "无", "0000", 真游标[:-1] + "X"):
            with self.subTest(游标=坏游标):
                调用结果 = self.后端.调用(搜索能力id, {"关键词": "", "限制": 3,
                                               "游标": 坏游标})
                self.assertFalse(调用结果.成功, f"非法游标 {坏游标!r} 不得放行")
                self.assertEqual("参数不合法", 调用结果.错误码)
        # 换关键词：游标记的是签发时的过滤条件，换了条件还接老位置必然漏项/重项
        换词 = self.后端.调用(搜索能力id, {"关键词": "OCR", "限制": 3, "游标": 真游标})
        self.assertFalse(换词.成功)
        self.assertEqual("参数不合法", 换词.错误码)
        self.assertIn("关键词", 换词.错误说明)

    def test_游标非文本被拒绝(self):
        调用结果 = self.后端.调用(搜索能力id, {"关键词": "", "限制": 3, "游标": 123})
        self.assertFalse(调用结果.成功)
        self.assertEqual("参数不合法", 调用结果.错误码)

    def test_完整契约档与读取能力逐字段一致(self):
        """最高档必须**逐字段等于** 读取能力 的单条结果（不是"多几个字段"就算）。

        这是「要完整契约必须显式传最高档」的兑现方式：拿到的东西与按 id 单独读
        完全一致，调用方不因为走搜索而少任何字段。
        """
        搜索记录 = self.搜索完整契约("能力目录.搜索能力", 5).值["能力列表"][0]
        读取记录 = self.后端.调用(读取能力id, {"能力id": "能力目录.搜索能力"}).值
        self.assertEqual(set(读取记录), set(搜索记录))
        self.assertEqual(json.dumps(读取记录, ensure_ascii=False, sort_keys=True),
                         json.dumps(搜索记录, ensure_ascii=False, sort_keys=True))

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

    def test_返回键只增不改(self):
        """对外只增不改：原 7 键必须都在，新 3 键追加，一个都不能少或改名。"""
        值 = self.搜索("", 3).值
        for 旧键 in ("关键词", "限制", "总数", "返回数", "是否截断", "能力列表", "项目根"):
            self.assertIn(旧键, 值, f"旧返回键 {旧键} 不得删除或改名")
        for 新键 in ("游标", "下一条游标", "细节级别"):
            self.assertIn(新键, 值, f"新返回键 {新键} 缺失")
        self.assertIn("游标", 值)
        self.assertIn("下一条游标", 值)
        self.assertIn("细节级别", 值)

    def test_记录覆盖旧两道检索实现的字段(self):
        """旧用例的字段面语义不变，但**必须显式要最高档**才拿得到（默认档只给指针）。

        断言的是「完整契约档仍然覆盖旧两道实现读取过的每一个键名」——这是平滑迁移的
        底线：转调方只要显式要最高档，就没有任何信息损失。
        """
        调用结果 = self.搜索完整契约("能力目录.搜索能力", 1)
        self.assertTrue(调用结果.成功, 调用结果.错误说明)
        记录 = 调用结果.值["能力列表"][0]
        for 字段 in 旧实现字段 + 开发入口字段 + 十四字段:
            self.assertIn(字段, 记录, f"完整契约档记录缺少旧实现字段: {字段}")

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
        """完整契约档与 读取能力 必须同口径（同一份记录的两个出口，逐字段相等）。

        必须显式传 细节级别=完整契约：默认档只回指针，与 读取能力 不构成「同口径对比」。
        **按能力id 定位**，不取「第一条」——关键词是整条记录子串匹配，命中集里谁排第一
        取决于其它记录的说明文案（改一句说明就会换位），取 [0] 等于把断言挂在文案上。
        """
        目标 = "能力目录.读取能力"
        搜索值 = self.后端.调用(搜索能力id, {"关键词": 目标, "限制": 100,
                                       "细节级别": "完整契约"}).值
        命中 = [记录 for 记录 in 搜索值["能力列表"] if 记录["能力id"] == 目标]
        self.assertEqual(1, len(命中), f"应恰好命中一条 {目标}")
        读取值 = self.读取(目标).值
        关键字 = ("能力id", "中文名", "包id", "版本", "必填", "默认值", "错误码")
        for 字段 in 关键字:
            self.assertEqual(命中[0][字段], 读取值[字段], f"{字段} 两处不一致")

    def test_调用示例是可执行示例而非空骨架(self):
        记录 = self.读取("能力目录.搜索能力").值
        示例 = 记录["调用示例"]
        self.assertEqual("能力目录.搜索能力", 示例["能力id"])
        # 参数面**只增不改**：示例可以演示新增参数，但旧参数一个都不能丢。
        self.assertIn("关键词", 示例["参数"])
        self.assertIn("限制", 示例["参数"])
        契约参数名 = {参数["名称"] for 参数 in 记录["参数"]}
        self.assertTrue(set(示例["参数"]) <= 契约参数名,
                        f"调用示例出现契约未声明的参数: {set(示例['参数']) - 契约参数名}")
        for 值 in 示例["参数"].values():
            self.assertIsNotNone(值, "调用示例不应留 None 骨架占位")
        self.assertTrue(记录["调用示例文本"].startswith("能力目录.搜索能力("))
        self.assertNotIn("=None", 记录["调用示例文本"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
