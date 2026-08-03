"""公开调用完整性门禁测试：六环一致合法样本零违规；缺口/同义/重复各检出。

覆盖：合法样本零违规、声明缺口（未列能力/能力定义缺失）、注册缺口、
说明书缺口（缺失/未含能力名）、搜索缺口（缺失/未含能力id）、公开调用缺口
（声明未导出）、验证场景缺口（缺失/未覆盖）、同义能力、重复提供者、
无声明目录跳过、循环注册映射提取、真实扫描现有包如实输出。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 开发工具.公开调用完整性门禁 import (
    找包目录, 提取导出名, 提取注册映射, 运行门禁,
)

仓库根 = Path(__file__).resolve().parents[2]


def 写(路径: Path, 内容: str) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(内容, encoding="utf-8")


def 合法包(根: Path, 包名: str = "示例包", 包id: str = "支持库.适配层.示例包",
         能力id: str = "示例.测试能力", 能力名: str = "测试能力") -> Path:
    """构造六环完整合法包，返回包目录。"""
    包目录 = 根 / "支持库" / "适配层" / 包名
    写(包目录 / "包声明.json", json.dumps({"包id": 包id, "能力": [{"能力id": 能力id, "名称": 能力名}]}, ensure_ascii=False))
    写(包目录 / "能力定义.json", json.dumps({"包id": 包id, "能力列表": [{"能力id": 能力id}]}, ensure_ascii=False))
    写(包目录 / "能力数据" / "能力搜索数据.json", json.dumps([{"能力id": 能力id, "名称": 能力名}], ensure_ascii=False))
    写(包目录 / "说明" / "使用说明.md", f"# {包名}\n{能力名} 能力说明")
    写(包目录 / "验证场景引用.json", json.dumps({"验证场景引用": [{"场景id": "支持库.资产验证", "目标": 包id, "范围": "资产"}]}, ensure_ascii=False))
    写(包目录 / "__init__.py",
       f"""from 支持库.适配层.{包名}.实现.实现 import {能力名}

__all__ = ["{能力名}"]


def 注册能力(注册表) -> None:
    from 公共契约.能力契约.契约 import 能力实现
    注册表.注册(能力实现(能力id="{能力id}", 实现函数={能力名}, 参数=[], 返回="结果", 说明=""))
""")
    return 包目录


class Test公开调用完整性门禁(unittest.TestCase):
    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp())

    def test_合法样本零违规(self):
        合法包(self.临时)
        self.assertEqual(运行门禁(self.临时), [])

    def test_无声明目录跳过(self):
        (self.临时 / "支持库" / "适配层" / "基础组件").mkdir(parents=True)
        self.assertEqual(找包目录(self.临时), [])

    def test_声明未列能力检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "包声明.json", json.dumps({"包id": "支持库.适配层.示例包"}, ensure_ascii=False))
        违规 = 运行门禁(self.临时)
        self.assertEqual(违规[0]["缺口类型"], "声明-包声明.json未列能力")
        self.assertEqual(违规[0]["包"], "支持库.适配层.示例包")

    def test_缺能力定义检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "能力定义.json").unlink()
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "声明-能力定义.json缺失")

    def test_入口未注册检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "能力数据" / "能力搜索数据.json").unlink()
        (包目录 / "能力数据").rmdir()
        写(包目录 / "__init__.py", '"""占位"""\n')
        类型表 = [条["缺口类型"] for 条 in 运行门禁(self.临时)]
        self.assertIn("注册-入口未注册能力", 类型表)

    def test_缺说明书检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "说明" / "使用说明.md").unlink()
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "说明书-使用说明.md缺失")

    def test_说明书未含能力名检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "说明" / "使用说明.md", "# 标题\n不含任何能力内容")
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "说明书-未含能力名")
        self.assertEqual(违规[0]["能力id"], "示例.测试能力")

    def test_缺搜索数据检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "能力数据" / "能力搜索数据.json").unlink()
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "搜索-能力搜索数据.json缺失")

    def test_搜索未含能力检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "能力数据" / "能力搜索数据.json", json.dumps([{"能力id": "别的.能力"}], ensure_ascii=False))
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "搜索-未含能力id")

    def test_声明未导出检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "__init__.py", '"""占位"""\n__all__ = ["未导出的名字"]\n')
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "公开调用-声明未导出")

    def test_验证场景缺失检出(self):
        包目录 = 合法包(self.临时)
        (包目录 / "验证场景引用.json").unlink()
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "验证场景-验证场景引用.json缺失")

    def test_验证场景未覆盖能力检出(self):
        包目录 = 合法包(self.临时)
        写(包目录 / "验证场景引用.json", json.dumps({"验证场景引用": [{"场景id": "x", "目标": "别的.包", "范围": "资产"}]}, ensure_ascii=False))
        违规 = 运行门禁(self.临时)
        self.assertEqual(len(违规), 1)
        self.assertEqual(违规[0]["缺口类型"], "验证场景-未覆盖能力")

    def test_同义能力检出(self):
        合法包(self.临时, 包名="甲包", 包id="支持库.适配层.甲包", 能力id="甲.测试能力", 能力名="测试能力")
        合法包(self.临时, 包名="乙包", 包id="支持库.适配层.乙包", 能力id="乙.测试能力", 能力名="测试能力")
        类型表 = [条["缺口类型"] for 条 in 运行门禁(self.临时)]
        self.assertIn("同义能力-跨包同名", 类型表)

    def test_重复提供者检出(self):
        合法包(self.临时, 包名="丙包", 包id="支持库.适配层.丙包", 能力id="重复.能力", 能力名="丙能力")
        合法包(self.临时, 包名="丁包", 包id="支持库.适配层.丁包", 能力id="重复.能力", 能力名="丁能力")
        类型表 = [条["缺口类型"] for 条 in 运行门禁(self.临时)]
        self.assertIn("重复提供者-同能力id多包", 类型表)

    def test_循环注册映射提取(self):
        源码 = '''from 模块库.OCR.实现.OCR import 识别图片文字

__all__ = ["识别图片文字"]


def 注册能力(注册表) -> None:
    from 公共契约.能力契约.契约 import 能力实现
    for 能力id, 函数, 参数名 in [
        ("OCR.识别图片文字", 识别图片文字, ["图片路径"]),
    ]:
        注册表.注册(能力实现(能力id=能力id, 实现函数=函数, 参数=[], 返回="结果", 说明=""))
'''
        映射 = 提取注册映射(源码)
        导出 = 提取导出名(源码)
        self.assertEqual(映射.get("OCR.识别图片文字"), "识别图片文字")
        self.assertIn("识别图片文字", 导出)

    def test_真实扫描如实输出(self):
        """真实仓库当前存在缺口（能力定义/搜索数据未迁移包），必须如实报告。"""
        违规 = 运行门禁(仓库根)
        self.assertGreater(len(违规), 0)
        for 条 in 违规:
            self.assertIn("缺口类型", 条)
            self.assertIn("路径", 条)
        结果 = subprocess.run([sys.executable, "开发工具/公开调用完整性门禁.py"],
                             cwd=仓库根, capture_output=True, text=True)
        self.assertIn("项违规", 结果.stdout)
        self.assertEqual(结果.returncode, 1)


if __name__ == "__main__":
    unittest.main()
