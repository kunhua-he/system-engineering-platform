"""模块合规验证测试：合规模块通过；各类违规检出；真实模块校验。

覆盖：导入白名单（第三方/支持库实现目录/核心）、能力占用（无提供者）、
包七要素（要素缺失/摘要漂移）、真实模块库 文件管理 与 OCR 应通过。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from MCP工具箱.模块合规 import (
    校验导入白名单,
    校验能力占用,
    校验模块合规,
    校验包七要素,
)

合规模块源码 = (
    "from __future__ import annotations\n"
    "import threading\n"
    "from 公共契约.基础类型.结果类型 import 结果\n"
    "from 支持库.后端.样例服务 import 问候 as _问候\n"
    "def 问候() -> 结果:\n"
    "    return _问候()\n"
)


def 搭建样例支持库(项目根: Path) -> None:
    """搭建声明 样例.问候 能力的支持库公开入口（不写完整性摘要）。"""
    服务目录 = 项目根 / "支持库" / "后端" / "样例服务"
    (服务目录 / "实现").mkdir(parents=True)
    (服务目录 / "实现" / "样例服务.py").write_text(
        "def 问候() -> str:\n    return \"你好\"\n", encoding="utf-8")
    (服务目录 / "__init__.py").write_text(
        "from 支持库.后端.样例服务.实现.样例服务 import 问候 as 问候\n",
        encoding="utf-8")
    (服务目录 / "包声明.json").write_text(json.dumps({
        "包id": "支持库.后端.样例服务",
        "名称": "样例服务",
        "类型": "支持库",
        "版本": "1.0.0",
        "入口": "__init__.py",
        "依赖": [],
        "能力": [{"能力id": "样例.问候", "名称": "问候", "参数": [], "返回": "结果",
                  "说明": "样例能力"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def 生成模块(项目根: Path, 模块名: str, *, 依赖: list[dict],
             实现源码: str = 合规模块源码,
             缺要素: tuple[str, ...] = ()) -> Path:
    """搭建模块库/<模块名> 七要素齐全的模块；缺要素 用于构造要素缺失样例。"""
    模块目录 = 项目根 / "模块库" / 模块名
    (模块目录 / "实现").mkdir(parents=True)
    (模块目录 / "能力契约").mkdir()
    (模块目录 / "说明").mkdir()
    (模块目录 / "实现" / (模块名 + ".py")).write_text(实现源码, encoding="utf-8")
    (模块目录 / "能力契约" / "参数契约.json").write_text(json.dumps({
        "能力契约": [{"能力id": "样例.问候", "参数": [], "返回": "结果"}]},
        ensure_ascii=False), encoding="utf-8")
    (模块目录 / "说明" / "使用说明.md").write_text("使用说明", encoding="utf-8")
    (模块目录 / "验证场景引用.json").write_text("{}", encoding="utf-8")
    (模块目录 / "包声明.json").write_text(json.dumps({
        "包id": "模块库." + 模块名,
        "名称": 模块名,
        "类型": "模块",
        "版本": "1.0.0",
        "入口": "__init__.py",
        "依赖": 依赖,
        "能力": [{"能力id": "样例.问候", "名称": "问候", "参数": [], "返回": "结果",
                  "说明": "样例能力"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (模块目录 / "__init__.py").write_text(
        f"from 模块库.{模块名}.实现.{模块名} import 问候\n", encoding="utf-8")
    if "完整性摘要.json" not in 缺要素:
        from 开发工具.组件规范.完整性摘要 import 生成完整性摘要
        (模块目录 / "完整性摘要.json").write_text(
            json.dumps(生成完整性摘要(模块目录, 包id="模块库." + 模块名, 版本="1.0.0"),
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for 要素 in 缺要素:
        if 要素 == "完整性摘要.json":
            continue
        路径 = 模块目录 / 要素
        if 路径.is_dir():
            import shutil
            shutil.rmtree(路径)
        else:
            路径.unlink(missing_ok=True)
    return 模块目录


class 模块合规测试(unittest.TestCase):
    """模块合规验证闭环测试。"""

    def 临时项目根(self):
        临时目录 = tempfile.TemporaryDirectory()
        self.addCleanup(临时目录.cleanup)
        项目根 = Path(临时目录.name)
        搭建样例支持库(项目根)
        return 项目根

    def test_合规模块通过(self) -> None:
        项目根 = self.临时项目根()
        生成模块(项目根, "合规模块", 依赖=[{"能力": "样例.问候", "版本": ">=1.0.0"}])
        结果 = 校验模块合规(项目根, "合规模块")
        self.assertTrue(结果["成功"], 结果["违规列表"])
        self.assertEqual(结果["错误码"], "")
        self.assertEqual(结果["违规列表"], [])
        self.assertTrue(校验导入白名单(项目根, "合规模块")["成功"])
        self.assertTrue(校验能力占用(项目根, "合规模块")["成功"])
        self.assertTrue(校验包七要素(项目根, "合规模块")["成功"])

    def test_模块不存在(self) -> None:
        项目根 = self.临时项目根()
        结果 = 校验模块合规(项目根, "不存在模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "MODULE_NOT_FOUND")
        self.assertEqual(结果["违规列表"][0]["类别"], "模块不存在")

    def test_导入第三方检出(self) -> None:
        项目根 = self.临时项目根()
        生成模块(项目根, "第三方模块", 依赖=[{"能力": "样例.问候", "版本": ">=1.0.0"}],
                  实现源码="import fitz\nimport PIL\nfrom docx import Document\n")
        结果 = 校验模块合规(项目根, "第三方模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "IMPORT_VIOLATION")
        类别表 = {违规["模块"]: 违规["类别"] for 违规 in 结果["违规列表"]
                  if 违规["类别"] == "第三方导入"}
        self.assertEqual(类别表, {"fitz": "第三方导入", "PIL": "第三方导入",
                                 "docx": "第三方导入"})
        for 违规 in 结果["违规列表"]:
            self.assertTrue(违规["文件"].endswith(".py"))
            self.assertGreaterEqual(违规["行"], 1)

    def test_导入支持库实现目录检出(self) -> None:
        项目根 = self.临时项目根()
        生成模块(项目根, "深挖模块",
                  依赖=[{"能力": "样例.问候", "版本": ">=1.0.0"}],
                  实现源码=(
                      "from 支持库.后端.样例服务.实现 import 问候\n"
                      "from 支持库.后端.样例服务.实现.样例服务 import 问候 as _问候\n"))
        结果 = 校验模块合规(项目根, "深挖模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "IMPORT_VIOLATION")
        self.assertEqual(
            [违规["类别"] for 违规 in 结果["违规列表"]],
            ["实现目录导入", "实现目录导入"])
        self.assertEqual(结果["违规列表"][0]["模块"], "支持库.后端.样例服务.实现")

    def test_导入运行核心检出(self) -> None:
        项目根 = self.临时项目根()
        生成模块(项目根, "核心模块",
                  依赖=[{"能力": "样例.问候", "版本": ">=1.0.0"}],
                  实现源码="from 运行核心.能力注册 import 注册能力\n")
        结果 = 校验模块合规(项目根, "核心模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "IMPORT_VIOLATION")
        self.assertEqual(结果["违规列表"][0]["类别"], "核心导入")
        self.assertEqual(结果["违规列表"][0]["模块"], "运行核心.能力注册")

    def test_白名单外导入检出(self) -> None:
        项目根 = self.临时项目根()
        生成模块(项目根, "越界模块",
                  依赖=[{"能力": "样例.问候", "版本": ">=1.0.0"}],
                  实现源码="from 模块库.其他模块 import 甲\nfrom 项目适配层.依赖锁定 import 乙\n")
        结果 = 校验模块合规(项目根, "越界模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "IMPORT_VIOLATION")
        self.assertEqual({违规["类别"] for 违规 in 结果["违规列表"]},
                         {"白名单外导入"})

    def test_声明能力无提供者检出(self) -> None:
        项目根 = self.临时项目根()
        生成模块(项目根, "无提供者模块",
                  依赖=[{"能力": "不存在.能力", "版本": ">=1.0.0"},
                        {"能力": "样例.问候", "版本": ">=1.0.0"}])
        结果 = 校验模块合规(项目根, "无提供者模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "NO_PROVIDER")
        self.assertEqual(结果["违规列表"][0]["模块"], "不存在.能力")
        self.assertEqual(结果["违规列表"][0]["类别"], "无提供者")

    def test_缺要素检出(self) -> None:
        项目根 = self.临时项目根()
        生成模块(项目根, "缺要素模块",
                  依赖=[{"能力": "样例.问候", "版本": ">=1.0.0"}],
                  缺要素=("说明", "验证场景引用.json", "__init__.py",
                          "完整性摘要.json"))
        结果 = 校验模块合规(项目根, "缺要素模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "ELEMENT_MISSING")
        缺失集合 = {违规["要素"] for 违规 in 结果["违规列表"]
                   if 违规["类别"] == "要素缺失"}
        self.assertEqual(缺失集合, {"说明", "验证场景引用.json", "__init__.py",
                                  "完整性摘要.json"})

    def test_摘要漂移检出(self) -> None:
        项目根 = self.临时项目根()
        模块目录 = 生成模块(项目根, "漂移模块",
                          依赖=[{"能力": "样例.问候", "版本": ">=1.0.0"}])
        (模块目录 / "实现" / "漂移模块.py").write_text(
            "from 支持库.后端.样例服务 import 问候 as _问候\n# 篡改\n",
            encoding="utf-8")
        结果 = 校验模块合规(项目根, "漂移模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "SUMMARY_DRIFT")
        self.assertTrue(所有违规["类别"] == "摘要漂移"
                        for 违规 in 结果["违规列表"])

    def test_真实文件管理通过(self) -> None:
        项目根 = Path(__file__).resolve().parents[2]
        结果 = 校验模块合规(项目根, "文件管理")
        self.assertTrue(结果["成功"], 结果["违规列表"])
        self.assertEqual(结果["错误码"], "")

    def test_真实OCR通过(self) -> None:
        项目根 = Path(__file__).resolve().parents[2]
        结果 = 校验模块合规(项目根, "OCR")
        self.assertTrue(结果["成功"], 结果["违规列表"])
        self.assertEqual(结果["错误码"], "")


if __name__ == "__main__":
    unittest.main()
