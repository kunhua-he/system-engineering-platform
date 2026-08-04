"""模块合规验证测试：权威 13 项合规 + 模块专属边界审计。

覆盖：真实 模块库.OCR 边界审计通过（过渡期 适配层 公开入口放行）；
构造违规样本（支持库导入/直接I/O/tempfile/subprocess/socket/数据库客户端/
动态import/第三方/运行核心）逐一检出；标准库纯 import 无调用不误伤
（按行为调用图判断）；反向：删除任一要素 权威合规与 MCP 一致失败。
禁止 mock：全部真实调用。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 开发工具.组件合规.合规测试包 import 组件合规
from 开发工具.组件规范.模块模板生成器 import 生成模块模板
from MCP工具箱.模块合规 import 审计模块边界, 校验模块合规

系统根 = Path(__file__).resolve().parents[2]
能力清单 = [
    {"名称": "检查可用性", "参数": [], "返回": "结果", "说明": "探测支持库可用性"},
    {"名称": "读取文件", "参数": [{"名称": "文件路径", "类型": "文本", "必填": True}],
     "返回": "结果", "说明": "经调用器读取文件"},
]
依赖清单 = [{"能力": "文件系统.读取文件", "版本": ">=1.0.0"}]


def 搭建违规模块(项目根: Path, 模块名: str, 实现源码: str) -> Path:
    """最小边界审计样例：模块库/<模块名>/实现/<模块名>.py。"""
    模块目录 = 项目根 / "模块库" / 模块名
    (模块目录 / "实现").mkdir(parents=True)
    (模块目录 / "实现" / f"{模块名}.py").write_text(实现源码, encoding="utf-8")
    return 模块目录


def 模板生成模块(临时根: Path, 模块名: str, *, 类型: str = "基础模块",
                缺要素: tuple[str, ...] = ()):
    """经唯一生成器产出真实模块；缺要素 用于反向破坏样例。"""
    模块库根 = 临时根 / "模块库"
    测试中心根 = 临时根 / "测试中心"
    模块库根.mkdir(exist_ok=True)
    (模块库根 / "__init__.py").write_text("", encoding="utf-8")
    结果 = 生成模块模板(模块名=模块名, 类型=类型, 能力清单=能力清单,
                   依赖能力清单=依赖清单, 模块库根=模块库根,
                   测试中心根=测试中心根)
    if not 结果.成功:
        raise AssertionError(f"模板生成失败: {结果.错误码}: {结果.错误说明}")
    模块目录 = Path(结果.值["模块目录"])
    for 要素 in 缺要素:
        路径 = 模块目录 / 要素
        if 路径.is_dir():
            shutil.rmtree(路径)
        else:
            路径.unlink(missing_ok=True)
    return 模块目录


class 模块合规测试(unittest.TestCase):
    """模块合规验证闭环测试：边界审计 + 权威合规一致判定。"""

    def setUp(self):
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_模块合规_"))
        self.addCleanup(shutil.rmtree, self.临时根, ignore_errors=True)

    def test_真实OCR边界审计通过(self):
        """真实 模块库.OCR：适配层公开入口 + 无原子旁路 → 边界审计通过。"""
        结果 = 审计模块边界(系统根, "OCR")
        self.assertTrue(结果["成功"], 结果["违规列表"])
        self.assertEqual(结果["错误码"], "")
        self.assertEqual(结果["违规列表"], [])

    def test_真实OCR校验模块合规只含权威违规(self):
        """MCP 校验 = 权威 13 项 + 边界审计；OCR 边界干净，失败仅来自权威部分。"""
        结果 = 校验模块合规(系统根, "OCR")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "AUTHORITY_VIOLATION")
        self.assertTrue(结果["权威合规"]["成功"] is False)
        类别表 = {违规["类别"] for 违规 in 结果["违规列表"]}
        self.assertEqual(类别表, {"权威合规"})

    def test_支持库导入检出(self):
        搭建违规模块(self.临时根, "支持库导入模块",
                      "from 支持库.后端.文件系统 import 读取文件\n")
        结果 = 审计模块边界(self.临时根, "支持库导入模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "IMPORT_VIOLATION")
        self.assertEqual(结果["违规列表"][0]["类别"], "支持库导入")
        self.assertEqual(结果["违规列表"][0]["模块"], "支持库.后端.文件系统")

    def test_实现目录导入检出(self):
        搭建违规模块(self.临时根, "深挖模块",
                      "from 支持库.后端.文件系统.实现.文件系统 import 读取文件\n")
        结果 = 审计模块边界(self.临时根, "深挖模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["违规列表"][0]["类别"], "实现目录导入")

    def test_直接IO检出(self):
        搭建违规模块(self.临时根, "直接IO模块",
                      "from pathlib import Path\nPath(\"数据\").read_bytes()\n")
        结果 = 审计模块边界(self.临时根, "直接IO模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "BOUNDARY_VIOLATION")
        self.assertEqual(结果["违规列表"][0]["类别"], "直接I/O")

    def test_tempfile检出(self):
        搭建违规模块(self.临时根, "临时目录模块",
                      "import tempfile\ntempfile.mkdtemp()\n")
        结果 = 审计模块边界(self.临时根, "临时目录模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["违规列表"][0]["类别"], "临时目录操作")

    def test_subprocess检出(self):
        搭建违规模块(self.临时根, "进程模块",
                      "import subprocess\nsubprocess.run([\"ls\"])\n")
        结果 = 审计模块边界(self.临时根, "进程模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["违规列表"][0]["类别"], "进程调用")

    def test_socket检出(self):
        搭建违规模块(self.临时根, "套接字模块",
                      "import socket\nsocket.socket()\n")
        结果 = 审计模块边界(self.临时根, "套接字模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["违规列表"][0]["类别"], "网络套接字")

    def test_数据库客户端检出(self):
        搭建违规模块(self.临时根, "数据库模块",
                      "import sqlite3\nsqlite3.connect(\"数据.db\")\n")
        结果 = 审计模块边界(self.临时根, "数据库模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["违规列表"][0]["类别"], "数据库客户端")

    def test_动态import检出(self):
        搭建违规模块(self.临时根, "动态导入模块",
                      "import importlib\nimportlib.import_module(\"os\")\n")
        结果 = 审计模块边界(self.临时根, "动态导入模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["违规列表"][0]["类别"], "动态导入绕过")

    def test_第三方与运行核心检出(self):
        搭建违规模块(self.临时根, "第三方模块",
                      "import PIL\nfrom 运行核心.加载器 import 扫描目录\n")
        结果 = 审计模块边界(self.临时根, "第三方模块")
        self.assertFalse(结果["成功"])
        类别表 = {违规["类别"] for 违规 in 结果["违规列表"]}
        self.assertEqual(类别表, {"第三方导入", "运行核心导入"})

    def test_标准库纯import无调用放行(self):
        """标准库按行为调用图判断：只 import 不调用不算违规。"""
        搭建违规模块(self.临时根, "纯导入模块",
                      "import tempfile\nimport subprocess\nimport json\n")
        结果 = 审计模块边界(self.临时根, "纯导入模块")
        self.assertTrue(结果["成功"], 结果["违规列表"])

    def test_生成模块边界审计通过(self):
        模块目录 = 模板生成模块(self.临时根, "生成边界模块")
        结果 = 审计模块边界(self.临时根, "生成边界模块")
        self.assertTrue(结果["成功"], 结果["违规列表"])
        声明 = json.loads((模块目录 / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(声明["类型"], "基础模块")

    def test_模块不存在(self):
        结果 = 校验模块合规(self.临时根, "不存在模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "MODULE_NOT_FOUND")
        self.assertEqual(结果["违规列表"][0]["类别"], "模块不存在")

    def test_删除任一要素权威合规与MCP一致失败(self):
        """反向：删除任一要素 → 权威 13 项与 MCP 校验模块合规一致失败。"""
        模块目录 = 模板生成模块(self.临时根, "缺要素模块", 缺要素=("说明",))
        权威报告 = 组件合规(模块目录).执行()
        self.assertFalse(权威报告.成功)
        结果 = 校验模块合规(self.临时根, "缺要素模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["权威合规"]["成功"], 权威报告.成功)
        失败场景 = {违规["场景"] for 违规 in 结果["违规列表"] if 违规["类别"] == "权威合规"}
        权威失败场景 = {名称 for 名称, 通过, _ in 权威报告.场景结果表 if not 通过}
        self.assertEqual(失败场景, 权威失败场景)
        self.assertIn("结构", 权威失败场景)
        self.assertEqual(结果["错误码"], "AUTHORITY_VIOLATION")

    def test_删除实现要素边界与权威一致失败(self):
        模块目录 = 模板生成模块(self.临时根, "缺实现模块", 缺要素=("实现",))
        权威报告 = 组件合规(模块目录).执行()
        self.assertFalse(权威报告.成功)
        结果 = 校验模块合规(self.临时根, "缺实现模块")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["权威合规"]["成功"], 权威报告.成功)


if __name__ == "__main__":
    unittest.main()
