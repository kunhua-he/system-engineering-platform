"""九要素支持库模板生成器测试：产物齐全/摘要校验/可编译/重复拒绝/逃逸拒绝/
同名拒绝/真实生成并运行测试骨架。
"""

from __future__ import annotations

import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 支持库.后端.组件规范支持库 import 校验完整性摘要
from 支持库.后端.组件规范支持库 import 生成支持库模板

包id = "支持库.示例.示例提供者"
名称 = "示例提供者"


def 样例能力清单() -> list[dict]:
    return [
        {
            "能力id": "示例分组.示例操作",
            "中文名称": "示例操作",
            "说明": "骨架占位能力：返回占位结果",
            "参数": [
                {"名称": "输入", "类型": "文本型", "必填": 真, "说明": "任意输入"},
                {"名称": "数量", "类型": "整数型", "必填": 假, "默认值": 1, "说明": "次数"},
            ],
            "返回": "结果型",
            "错误码": ["参数不合法", "超时", "提供者崩溃", "提供者不可用"],
            "行为": {
                "修改输入": 假, "幂等": 真, "副作用": "只读", "排序稳定": 真,
                "时区": "不涉及", "编码": "utf-8", "精度": "不涉及", "空值": "缺省",
                "输入上限": "骨架不设限", "超时可重试": 真, "取消": "支持",
                "重试条件": "超时/提供者崩溃/提供者不可用", "事务边界": "无",
                "补偿动作": "无", "线程安全": 真, "进程安全": 真,
                "资源释放": "子进程自动回收", "错误码": "统一", "可重试性": "超时可重试",
            },
        },
        {
            "能力id": "示例分组.第二操作",
            "中文名称": "第二操作",
            "说明": "第二个骨架占位能力（缺省字段自动补齐）",
            "参数": [{"名称": "输入", "类型": "文本型", "必填": 真, "说明": "任意输入"}],
            "返回": "结果型",
        },
    ]


class Test支持库模板生成器(unittest.TestCase):
    """支持库模板生成器闭环测试。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp())
        self.包目录 = self.临时 / 名称
        self.测试文件 = self.临时 / f"测试_{名称}.py"

    def tearDown(self):
        shutil.rmtree(self.临时, ignore_errors=True)

    def 生成(self, **覆盖):
        参数 = dict(输出目录=self.包目录, 包id=包id, 名称=名称,
                    能力清单=样例能力清单(), 测试文件路径=self.测试文件)
        参数.update(覆盖)
        return 生成支持库模板(**参数)

    def test_生成九要素齐全(self):
        结果 = self.生成()
        self.assertTrue(结果.成功, str(结果.错误说明))
        # **依赖锁.json 不在无条件必要文件里**（决策 0033 铁口径：
        # 「依赖锁存在 ⟺ 有第三方/外部依赖」——无第三方时不产该文件，
        # 「缺失」就是「无第三方」的唯一表达；早期模板无条件造空壳锁会被判「依赖锁为空」
        # 并禁止装配提供者）。本用例不传第三方说明 ⇒ 期望**不产**锁，见下方两向断言。
        必要文件 = [
            "能力定义.json", "包声明.json", "能力契约/参数契约.json",
            "配置契约/配置契约.json", "权限契约/权限契约.json", "验证场景引用.json",
            "说明/使用说明.md", "说明/设计说明.md", "复用决策.json", "资源预算.json",
            "完整性摘要.json", "__init__.py", "实现/__init__.py",
            "实现/子进程入口.py", "实现/提供者.py",
        ]
        实际文件 = {str(p.relative_to(self.包目录)) for p in self.包目录.rglob("*") if p.is_file()}
        for 路径 in 必要文件:
            self.assertIn(路径, 实际文件, f"缺少九要素文件: {路径}")
        self.assertTrue(self.测试文件.is_file(), "缺少测试骨架")
        # 能力定义.json 单源与包声明能力清单一致
        定义 = json.loads((self.包目录 / "能力定义.json").read_text(encoding="utf-8"))
        self.assertEqual(定义["包id"], 包id)
        self.assertEqual(len(定义["能力列表"]), 2)
        声明 = json.loads((self.包目录 / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(len(声明["能力"]), 2)
        # 第三方向导（两向，决策 0033）：
        # ① 本用例未传第三方说明 → **不得产出 依赖锁.json**（缺失＝无第三方的唯一表达）
        self.assertFalse((self.包目录 / "依赖锁.json").exists(),
                         "无第三方依赖时不得产出 依赖锁.json（决策 0033：依赖锁存在 ⟺ 有第三方/外部依赖）")
        # ② 传了第三方说明 → 必须产出锁，且锁里如实登记该第三方
        带三方 = self.临时 / "带三方"
        结果2 = self.生成(输出目录=带三方,
                          测试文件路径=self.临时 / "测试_带三方.py",
                          第三方说明=[{"名称": "示例第三方", "版本": "1.0.0",
                                       "模块名": "示例模块", "接入方式": "外部工具"}])
        self.assertTrue(结果2.成功, str(结果2.错误说明))
        锁路径 = 带三方 / "依赖锁.json"
        self.assertTrue(锁路径.is_file(), "有第三方依赖时必须产出 依赖锁.json")
        依赖锁 = json.loads(锁路径.read_text(encoding="utf-8"))
        self.assertEqual(依赖锁["包"], [{"名称": "示例第三方", "版本": "1.0.0",
                                        "模块名": "示例模块", "接入方式": "外部工具"}])
        self.assertIn("第三方", 依赖锁["说明"])

    def test_完整性摘要校验通过(self):
        结果 = self.生成()
        self.assertTrue(结果.成功, str(结果.错误说明))
        通过, 问题列表 = 校验完整性摘要(self.包目录)
        self.assertTrue(通过, str(问题列表))

    def test_生成文件可编译(self):
        结果 = self.生成()
        self.assertTrue(结果.成功, str(结果.错误说明))
        for 路径 in self.包目录.rglob("*.py"):
            py_compile.compile(str(路径), doraise=True)
        py_compile.compile(str(self.测试文件), doraise=True)

    def test_重复生成拒绝覆盖(self):
        结果 = self.生成()
        self.assertTrue(结果.成功, str(结果.错误说明))
        结果 = self.生成()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件已存在")
        self.assertIn("包声明.json", 结果.详细信息.get("已存在", []))

    def test_路径逃逸拒绝(self):
        能力清单 = 样例能力清单()
        能力清单[0]["能力id"] = "示例../逃逸.操作"
        结果 = self.生成(能力清单=能力清单)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径逃逸")
        self.assertTrue(self.包目录.exists() is 假 or not self.包目录.is_dir())

    def test_包名路径逃逸拒绝(self):
        结果 = self.生成(名称="../逃逸提供者")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "路径逃逸")

    def test_同名能力拒绝(self):
        能力清单 = 样例能力清单()
        能力清单[1]["能力id"] = 能力清单[0]["能力id"]
        结果 = self.生成(能力清单=能力清单)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "同名能力")
        self.assertIn("示例分组.示例操作", "".join(结果.详细信息.get("明细", [])))

    def test_能力清单为空拒绝(self):
        结果 = self.生成(能力清单=[])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_真实生成并运行测试骨架(self):
        结果 = self.生成()
        self.assertTrue(结果.成功, str(结果.错误说明))
        运行 = subprocess.run(
            [sys.executable, str(self.测试文件)],
            capture_output=True, text=True, timeout=180,
        )
        输出 = 运行.stdout + 运行.stderr
        self.assertEqual(运行.returncode, 0, f"测试骨架失败:\n{输出}")
        for 关键词 in ("合法调用", "参数不合法", "超时", "提供者不可用"):
            self.assertIn(关键词, 输出, f"缺少测试项: {关键词}")
        self.assertIn("OK", 输出)


if __name__ == "__main__":
    unittest.main()
