"""模块模板收敛测试：唯一生成器 两类类型/聚合契约/经调用器骨架/覆盖拒绝。

覆盖：基础模块|功能模块 包声明类型；S0.1 聚合契约结构（契约版本 + 逐能力
版本/说明/参数/返回/错误码/调用示例）；实现只经 获取能力调用器().调用能力
（不 import 支持库）；对称 __init__ 与 __all__；完整性摘要唯一校验；
已存在/路径逃逸/能力重复/类型不合法/参数类型不合法/依赖无提供者 一律拒绝。
禁止 mock：全部真实生成与真实校验。
"""

from __future__ import annotations

import json
import py_compile
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.组件合规.合规测试包 import 组件合规
from 支持库.后端.组件规范支持库 import 校验完整性摘要
from 支持库.后端.组件规范支持库 import 生成模块模板

能力清单 = [
    {"名称": "检查可用性", "参数": [], "返回": "结果", "说明": "探测支持库可用性"},
    {"名称": "读取文件", "参数": [{"名称": "文件路径", "类型": "文本型", "必填": True}],
     "返回": "结果", "说明": "经调用器读取文件"},
]
依赖清单 = [{"能力": "文件系统支持库.文件操作.读取文件", "版本": ">=1.0.0"}]


class Test模块模板收敛(unittest.TestCase):
    """唯一模块模板生成器收敛闭环测试。"""

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_模块模板收敛_"))
        self.模块库根 = self.临时根 / "模块库"
        self.测试中心根 = self.临时根 / "测试中心"
        self.模块库根.mkdir()
        (self.模块库根 / "__init__.py").write_text("", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _生成(self, 模块名="示例统计", 类型="基础模块", **覆盖):
        参数 = dict(模块名=模块名, 类型=类型, 能力清单=能力清单,
                   依赖能力清单=依赖清单, 模块库根=self.模块库根,
                   测试中心根=self.测试中心根)
        参数.update(覆盖)
        return 生成模块模板(**参数)

    def test_两类类型包声明与聚合契约(self):
        for 类型 in ("基础模块", "功能模块"):
            结果 = self._生成(模块名=f"{类型}示例", 类型=类型)
            self.assertTrue(结果.成功, f"{类型} 生成失败: {结果.错误说明}")
            模块目录 = Path(结果.值["模块目录"])
            声明 = json.loads((模块目录 / "包声明.json").read_text(encoding="utf-8"))
            self.assertEqual(声明["类型"], 类型)
            self.assertEqual(声明["包id"], f"模块库.{类型}示例")
            self.assertEqual(声明["依赖"], 依赖清单)
            契约 = json.loads((模块目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
            from 公共契约.版本规则.契约版本 import 契约版本 as 当前契约版本
            self.assertEqual(契约["契约版本"], 当前契约版本, "契约版本必须等于唯一事实源，禁止写死字面量")
            self.assertEqual([e["能力id"] for e in 契约["能力契约"]],
                             [f"{类型}示例.检查可用性", f"{类型}示例.读取文件"])

    def test_聚合契约逐能力完整(self):
        结果 = self._生成()
        self.assertTrue(结果.成功)
        契约 = json.loads((Path(结果.值["模块目录"]) / "能力契约" / "参数契约.json")
                          .read_text(encoding="utf-8"))
        for 能力 in 契约["能力契约"]:
            for 键 in ("能力id", "版本", "说明", "参数", "返回", "错误码", "调用示例"):
                self.assertIn(键, 能力, f"聚合契约缺 {键}: {能力.get('能力id')}")
            self.assertEqual(能力["返回"], {"类型": "结果", "值结构": {}})
            self.assertTrue(能力["错误码"])
            self.assertEqual(能力["调用示例"]["能力id"], 能力["能力id"])
            for 参数 in 能力["参数"]:
                for 键 in ("名称", "类型", "必填", "默认值", "说明"):
                    self.assertIn(键, 参数, f"参数缺 {键}: {参数}")
                self.assertNotEqual(参数["类型"], "任意", "禁止 任意 类型")

    def test_经调用器骨架_对称入口_完整性摘要(self):
        结果 = self._生成()
        self.assertTrue(结果.成功, f"生成失败: {结果.错误说明}")
        模块目录 = Path(结果.值["模块目录"])
        实现文本 = (模块目录 / "实现" / "示例统计.py").read_text(encoding="utf-8")
        self.assertIn("获取能力调用器().调用能力", 实现文本)
        self.assertIn('"文件系统支持库.文件操作.读取文件"', 实现文本)
        self.assertNotIn("import 支持库", 实现文本)
        self.assertNotIn("import 运行核心", 实现文本)
        self.assertNotIn("import tempfile", 实现文本)
        py_compile.compile(str(模块目录 / "实现" / "示例统计.py"), doraise=True)
        py_compile.compile(str(模块目录 / "__init__.py"), doraise=True)
        入口文本 = (模块目录 / "__init__.py").read_text(encoding="utf-8")
        for 能力名 in ("检查可用性", "读取文件"):
            self.assertIn(f"from 模块库.示例统计.实现.示例统计 import {能力名}", 入口文本)
        self.assertEqual(入口文本.split("__all__ = ")[1].split("\n")[0],
                         "['检查可用性', '读取文件']")
        self.assertIn("def 注册能力", 入口文本)
        通过, 问题 = 校验完整性摘要(模块目录)
        self.assertTrue(通过, "; ".join(问题))

    def test_已存在拒绝覆盖(self):
        结果 = self._生成()
        self.assertTrue(结果.成功)
        重复 = self._生成()
        self.assertFalse(重复.成功)
        self.assertEqual(重复.错误码, "已存在")

    def test_路径逃逸拒绝(self):
        结果 = self._生成(模块名="../逃逸")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径逃逸")

    def test_能力重复拒绝(self):
        重复清单 = [{"名称": "读取文件", "参数": []}, {"名称": "读取文件", "参数": []}]
        结果 = self._生成(能力清单=重复清单)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "能力重复")

    def test_类型不合法拒绝(self):
        结果 = self._生成(类型="模块")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "类型不合法")

    def test_参数类型不合法拒绝(self):
        结果 = self._生成(能力清单=[{"名称": "旧能力", "参数": [{"名称": "输入", "类型": "任意"}]}])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数类型不合法")

    def test_依赖无提供者拒绝(self):
        结果 = self._生成(依赖能力清单=[{"能力": "不存在的库.不存在能力"}])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "无提供者")

    def test_生成模块可经权威合规验证器执行(self):
        结果 = self._生成()
        self.assertTrue(结果.成功)
        报告 = 组件合规(Path(结果.值["模块目录"])).执行()
        self.assertEqual(报告.总场景数, 13)
        self.assertEqual(len(报告.场景结果表), 13)


if __name__ == "__main__":
    unittest.main()
