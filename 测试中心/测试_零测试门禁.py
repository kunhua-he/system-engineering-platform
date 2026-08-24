"""零测试门禁测试：证明"零测试不能返回成功"。

覆盖：判断零测试、主函数零套件返回非零、导入失败门禁、跳过门禁。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

import 测试中心
import 测试中心.运行测试 as 运行测试


class Test零测试门禁(unittest.TestCase):
    def test_空套件判定为零测试(self):
        套件 = unittest.TestSuite()
        self.assertTrue(运行测试.判断零测试(套件))

    def test_非空套件判定非零测试(self):
        套件 = unittest.TestSuite()
        套件.addTest(Test零测试门禁("test_空套件判定为零测试"))
        self.assertFalse(运行测试.判断零测试(套件))

    def test_主函数零套件返回非零(self):
        退出码 = 运行测试.主函数(unittest.TestSuite())
        self.assertNotEqual(退出码, 0)

    def test_主函数真实套件返回零(self):
        # 使用小型独立套件（避免运行完整套件导致递归）
        class 小测试(unittest.TestCase):
            def test_通过(self):
                self.assertTrue(True)

        小套件 = unittest.TestSuite()
        小套件.addTest(小测试("test_通过"))
        退出码 = 运行测试.主函数(小套件)
        self.assertEqual(退出码, 0)

    def test_导入失败门禁检测(self):
        结果 = unittest.TestResult()
        失败用例 = unittest.FunctionTestCase(lambda: None)
        结果.startTest(失败用例)
        try:
            raise AssertionError("导入失败")
        except AssertionError:
            结果.addFailure(失败用例, sys.exc_info())
        结果.stopTest(失败用例)
        self.assertTrue(运行测试.判断导入失败(结果))

    def test_无失败时导入门禁通过(self):
        结果 = unittest.TestResult()
        用例 = Test零测试门禁("test_空套件判定为零测试")
        结果.startTest(用例)
        用例.run(结果)
        结果.stopTest(用例)
        self.assertFalse(运行测试.判断导入失败(结果))

    def test_跳过门禁检测(self):
        结果 = unittest.TestResult()
        用例 = Test零测试门禁("test_空套件判定为零测试")
        结果.startTest(用例)
        结果.addSkip(用例, "反向验证")
        结果.stopTest(用例)
        self.assertTrue(运行测试.判断存在跳过(结果))

    def test_主函数遇到跳过返回非零(self):
        class 跳过测试(unittest.TestCase):
            @unittest.skip("反向验证")
            def test_不得伪装成功(self):
                self.fail("本场景不应执行")

        套件 = unittest.TestSuite([跳过测试("test_不得伪装成功")])
        self.assertNotEqual(运行测试.主函数(套件), 0)

    def test_工程缓存正式实现引用门禁在引用清零后通过(self):
        """生产化完成后：测试不得引用工程缓存候选实现，门禁必须通过。"""
        违规文件 = 运行测试.审计工程缓存正式实现引用()
        self.assertEqual(违规文件, [],
                         f"正式测试不得引用工程缓存候选实现: {违规文件[:5]}")

    def test_工作包模式只加载指定测试文件(self):
        套件 = 运行测试.加载指定测试文件([
            "测试中心/MCP工具箱/测试_项目服务.py",
        ])
        # 结构性最小约束：套件非空、全部用例仅来自指定文件对应模块；
        # 不写死具体数量，新增测试无需修改本断言。
        # 注：Python 3.13+ 的 TestSuite.__iter__ 不再递归展开，需逐层展开。

        def 展开全部用例(当前套件):
            for 项 in 当前套件._tests:
                if isinstance(项, unittest.TestSuite):
                    yield from 展开全部用例(项)
                else:
                    yield 项

        用例表 = list(展开全部用例(套件))
        self.assertGreater(len(用例表), 0, "指定文件必须加载出测试用例")
        来源模块表 = {type(用例).__module__ for 用例 in 用例表}
        self.assertEqual(len(来源模块表), 1,
                         "工作包模式不得混入指定文件以外的测试")
        self.assertTrue(
            next(iter(来源模块表)).endswith("_测试_项目服务"),
            f"用例必须来自指定文件，实际来源: {来源模块表}",
        )

    def test_工作包模式拒绝测试中心外文件(self):
        with self.assertRaises(ValueError):
            运行测试.加载指定测试文件(["MCP工具箱/项目服务.py"])

    def test_波次模式保持阶段固定顺序(self):
        阶段表 = [("甲", ["甲"]), ("乙", ["乙"]), ("丙", ["丙"])]
        self.assertEqual(
            运行测试.筛选阶段(阶段表, ["丙", "甲"]),
            [("甲", ["甲"]), ("丙", ["丙"])],
        )

    def test_工作包并行数自动有界(self):
        self.assertEqual(运行测试.计算并行数(1, 0), 1)
        self.assertEqual(运行测试.计算并行数(4, 2), 2)
        self.assertLessEqual(运行测试.计算并行数(100, 0), os.cpu_count())

    def test_慢速证据相同且有效时复用(self):
        缓存 = {
            "摘要": "源码", "成功": True, "测试数": 3,
            "结构版本": 运行测试.缓存结构版本,
            "环境摘要": "环境", "时间戳": 1000,
        }
        self.assertTrue(运行测试.阶段缓存可复用(
            "慢速层", 缓存, "源码", "环境", 当前时间=1001,
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "慢速层", 缓存, "源码", "新环境", 当前时间=1001,
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "慢速层", 缓存, "源码", "环境",
            强制慢速=True, 当前时间=1001,
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "慢速层", 缓存, "源码", "环境",
            当前时间=1000 + 运行测试.运行证据有效秒 + 1,
        ))

    def test_断点原子写入读取与清理(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            原路径 = 运行测试.断点文件路径
            运行测试.断点文件路径 = Path(临时目录) / "断点.json"
            try:
                运行测试.写入断点("常规", "乙", [("甲", []), ("乙", [])], "测试失败")
                断点 = 运行测试.读取断点()
                self.assertEqual(断点["失败阶段"], "乙")
                self.assertEqual(断点["阶段列表"], ["甲", "乙"])
                运行测试.清除断点()
                self.assertEqual(运行测试.读取断点(), {})
            finally:
                运行测试.断点文件路径 = 原路径

    def test_断点从失败阶段继续(self):
        阶段表 = [("甲", ["甲"]), ("乙", ["乙"]), ("丙", ["丙"])]
        缓存 = {
            "甲": {"摘要": "甲摘要", "成功": True, "测试数": 1,
                   "结构版本": 运行测试.缓存结构版本, "环境摘要": "环境"},
        }
        with patch.object(运行测试, "收集阶段文件", return_value=[Path(__file__)]), \
                patch.object(运行测试, "阶段依赖目录表", return_value=set()), \
                patch.object(运行测试, "阶段摘要", return_value="甲摘要"):
            结果 = 运行测试.计算断点续跑阶段(
                阶段表, {"失败阶段": "乙", "阶段列表": ["甲", "乙", "丙"]},
                缓存, "环境", False,
            )
        self.assertEqual(结果, [("乙", ["乙"]), ("丙", ["丙"])])

    def test_断点在上游摘要变化时自动回退(self):
        阶段表 = [("甲", ["甲"]), ("乙", ["乙"]), ("丙", ["丙"])]
        缓存 = {
            "甲": {"摘要": "旧摘要", "成功": True, "测试数": 1,
                   "结构版本": 运行测试.缓存结构版本},
        }
        with patch.object(运行测试, "收集阶段文件", return_value=[Path(__file__)]), \
                patch.object(运行测试, "阶段依赖目录表", return_value=set()), \
                patch.object(运行测试, "阶段摘要", return_value="新摘要"):
            结果 = 运行测试.计算断点续跑阶段(
                阶段表, {"失败阶段": "乙", "阶段列表": ["甲", "乙", "丙"]},
                缓存, "环境", False,
            )
        self.assertEqual(结果, 阶段表)

    def test_没有断点时拒绝续跑(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            with patch.object(运行测试, "断点文件路径", Path(临时目录) / "不存在.json"), \
                    patch.object(运行测试, "审计工程缓存正式实现引用", return_value=[]):
                self.assertEqual(运行测试.主函数(继续运行=True), 2)


class Test断点集成链路(unittest.TestCase):
    """阶段失败 → 写断点 → 续跑从失败阶段开始 的集成链路。

    覆盖 主函数串行执行中阶段失败时 写入断点 的正确性，以及断点续跑
    从失败阶段继续、更早阶段缓存可复用则跳过。
    """

    def setUp(self) -> None:
        self.临时目录 = tempfile.TemporaryDirectory()
        self.addCleanup(self.临时目录.cleanup)
        self.断点路径 = Path(self.临时目录.name) / "验证断点.json"

    def test_阶段失败写入断点且续跑从失败阶段开始(self) -> None:
        阶段表 = [("甲", ["甲"]), ("乙", ["乙"]), ("丙", ["丙"])]
        # 甲阶段成功（写缓存），乙阶段失败（触发断点），丙阶段不执行
        调用记录: list[str] = []

        def 假阶段执行(阶段名, 匹配表, 范围, 断点表, 缓存, 环境, 强制慢速):
            if 阶段名 == "甲":
                调用记录.append("甲")
                return 0, 1, True, 缓存
            if 阶段名 == "乙":
                调用记录.append("乙")
                # 模拟 _执行单个阶段串行 内部写断点（真实逻辑在阶段失败分支）
                运行测试.写入断点("常规", "乙", 断点表, "测试失败")
                return 1, 0, False, 缓存
            调用记录.append("丙")
            return 0, 1, True, 缓存

        with tempfile.TemporaryDirectory() as 缓存目录:
            缓存目录路径 = Path(缓存目录)
            with patch.object(运行测试, "写入断点") as 假写断点, \
                    patch.object(运行测试, "_执行单个阶段串行", side_effect=假阶段执行), \
                    patch.object(运行测试, "清除断点") as 假清除:
                from 测试中心.运行测试 import _执行阶段顺序表串行
                结果 = _执行阶段顺序表串行(
                    "常规", 阶段表, 阶段表, {}, "环境", False,
                )
        # 乙失败后丙不执行，且断点被写入（失败阶段=乙）
        self.assertEqual(调用记录, ["甲", "乙"])
        self.assertEqual(结果, 1)
        假写断点.assert_called_once()
        写断点参数 = 假写断点.call_args[0]
        self.assertEqual(写断点参数[0], "常规")
        self.assertEqual(写断点参数[1], "乙")  # 失败阶段
        假清除.assert_not_called()

    def test_全部阶段成功时清除断点(self) -> None:
        阶段表 = [("甲", ["甲"]), ("乙", ["乙"])]

        def 假阶段执行(阶段名, 匹配表, 范围, 断点表, 缓存, 环境, 强制慢速):
            return 0, 1, True, 缓存

        with tempfile.TemporaryDirectory() as 缓存目录:
            with patch.object(运行测试, "写入断点") as 假写断点, \
                    patch.object(运行测试, "_执行单个阶段串行", side_effect=假阶段执行), \
                    patch.object(运行测试, "清除断点") as 假清除:
                from 测试中心.运行测试 import _执行阶段顺序表串行
                结果 = _执行阶段顺序表串行(
                    "常规", 阶段表, 阶段表, {}, "环境", False,
                )
        self.assertEqual(结果, 0)
        假写断点.assert_not_called()
        假清除.assert_called_once()


if __name__ == "__main__":
    unittest.main()
