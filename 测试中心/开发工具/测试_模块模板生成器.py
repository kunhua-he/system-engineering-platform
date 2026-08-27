"""模块模板生成器测试：九要素齐全/摘要校验/编译通过/防御拒绝/真实生成并跑测试骨架。

覆盖：临时目录生成 → 九要素齐全 + 摘要校验 + py_compile；
已存在/路径逃逸/能力重复/依赖无提供者 一律拒绝（结构化错误码）；
真实生成示例模块模板并在子进程运行测试骨架（退出码 0）。
禁止 mock：全部真实生成与真实校验。
"""

from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.组件规范.完整性摘要 import 校验完整性摘要
from 开发工具.组件规范.模块模板生成器 import 生成模块模板

九要素文件表 = [
    "包声明.json",
    "能力契约/参数契约.json",
    "依赖契约/依赖契约.json",
    "配置契约/配置契约.json",
    "权限契约/权限契约.json",
    "实现/示例统计.py",
    "验证场景引用.json",
    "说明/使用说明.md",
    "完整性摘要.json",
]
示例能力清单 = [
    {"名称": "检查可用性", "参数": [], "返回": "结果", "说明": "探测支持库可用性"},
    {"名称": "读取文件", "参数": [{"名称": "文件路径", "类型": "文本"}], "返回": "结果", "说明": "转发读取文件"},
]
示例依赖清单 = [{"能力": "文件系统支持库.文件操作.读取文件", "版本": ">=1.0.0"}]


class Test生成模块模板(unittest.TestCase):
    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_模块模板_"))
        self.模块库根 = self.临时根 / "模块库"
        self.测试中心根 = self.临时根 / "测试中心"
        self.模块库根.mkdir()
        (self.模块库根 / "__init__.py").write_text("", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _生成(self, **覆盖):
        参数 = dict(模块名="示例统计", 能力清单=示例能力清单, 依赖能力清单=示例依赖清单,
                   模块库根=self.模块库根, 测试中心根=self.测试中心根)
        参数.update(覆盖)
        return 生成模块模板(**参数)

    def test_九要素齐全_摘要校验_编译通过(self):
        结果 = self._生成()
        self.assertTrue(结果.成功, f"生成失败: {结果.错误说明}")
        模块目录 = Path(结果.值["模块目录"])
        for 相对 in 九要素文件表:
            self.assertTrue((模块目录 / 相对).is_file(), f"缺少九要素文件: {相对}")
        通过, 问题 = 校验完整性摘要(模块目录)
        self.assertTrue(通过, "; ".join(问题))
        py_compile.compile(str(模块目录 / "实现" / "示例统计.py"), doraise=True)
        py_compile.compile(str(模块目录 / "__init__.py"), doraise=True)
        骨架 = Path(结果.值["测试骨架"])
        self.assertTrue(骨架.is_file(), "缺少测试骨架")
        声明 = json.loads((模块目录 / "包声明.json").read_text(encoding="utf-8"))
        依赖契约 = json.loads((模块目录 / "依赖契约" / "依赖契约.json").read_text(encoding="utf-8"))
        self.assertEqual(依赖契约["依赖"], 声明["依赖"])
        权限契约 = json.loads((模块目录 / "权限契约" / "权限契约.json").read_text(encoding="utf-8"))
        for 能力id in [条目["能力id"] for 条目 in 声明["能力"]]:
            self.assertIn(能力id, 权限契约, f"能力缺权限声明: {能力id}")
        实现文本 = (模块目录 / "实现" / "示例统计.py").read_text(encoding="utf-8")
        self.assertIn("获取能力调用器().调用能力", 实现文本)
        self.assertNotIn("import 支持库", 实现文本)
        self.assertNotIn("支持库.后端.文件系统支持库.文件操作.实现", 实现文本)

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

    def test_能力名重复拒绝(self):
        重复清单 = [{"名称": "读取文件", "参数": []}, {"名称": "读取文件", "参数": []}]
        结果 = self._生成(能力清单=重复清单)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "能力重复")

    def test_依赖无提供者拒绝(self):
        结果 = self._生成(依赖能力清单=[{"能力": "不存在的库.不存在能力"}])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "无提供者")

    def test_真实生成示例模块并跑测试骨架(self):
        结果 = self._生成(模块名="示例模块")
        self.assertTrue(结果.成功, f"生成失败: {结果.错误说明}")
        骨架路径 = Path(结果.值["测试骨架"])
        环境 = dict(os.environ, PYTHONPATH=f"{self.临时根}{os.pathsep}{系统根}")
        完成 = subprocess.run([sys.executable, str(骨架路径)], env=环境,
                              cwd=str(self.临时根), capture_output=True, text=True)
        self.assertEqual(完成.returncode, 0, f"骨架测试未通过:\n{完成.stdout}\n{完成.stderr}")


if __name__ == "__main__":
    unittest.main()
