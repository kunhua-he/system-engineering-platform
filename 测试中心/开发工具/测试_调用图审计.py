"""第二十九阶段G4-能力调用图与原子旁路审计测试。

构造违规样本（支持库导入/read_bytes/tempfile/subprocess/网络/数据库/动态import）
逐一检出；四者漂移检出；重复能力检出；允许 能力调用器 与 公共契约 不误报；
真实 模块库.OCR 审计如实报出当前支持库静态导入（第二波迁移后清零）。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(系统根))

from 开发工具.复用审计.能力调用图审计 import 审计模块库


def 构造包(根: Path, 包名: str, 实现文本: str, 能力id表: list[str],
           __all__表: list[str] | None = None) -> Path:
    """构造一个模块包目录：包声明/能力契约/__init__（注册+__all__）/实现。"""
    包目录 = 根 / 包名
    (包目录 / "实现").mkdir(parents=True)
    (包目录 / "能力契约").mkdir()
    (包目录 / "实现" / f"{包名}.py").write_text(实现文本, encoding="utf-8")
    (包目录 / "包声明.json").write_text(json.dumps({
        "包id": f"模块库.{包名}", "名称": 包名, "类型": "基础模块", "版本": "1.0.0",
        "入口": "__init__.py", "依赖": [],
        "能力": [{"能力id": 能力id, "名称": 能力id.split(".")[-1], "参数": [], "返回": "结果"}
                 for 能力id in 能力id表],
    }, ensure_ascii=False), encoding="utf-8")
    (包目录 / "能力契约" / "参数契约.json").write_text(json.dumps({
        "能力契约": [{"能力id": 能力id, "参数": [], "返回": "结果"} for 能力id in 能力id表],
    }, ensure_ascii=False), encoding="utf-8")
    __all__表 = __all__表 if __all__表 is not None else [能力id.split(".")[-1] for 能力id in 能力id表]
    注册行 = "\n".join(
        f'    注册表.注册(能力实现(能力id="{能力id}", 包id="模块库.{包名}",'
        f' 实现函数={能力id.split(".")[-1]}, 参数=[], 返回="结果", 说明=""))'
        for 能力id in 能力id表)
    (包目录 / "__init__.py").write_text(
        '"""入口。"""\n\nfrom __future__ import annotations\n\n'
        f"from 模块库.{包名}.实现.{包名} import {', '.join(能力id.split('.')[-1] for 能力id in 能力id表)}\n\n"
        f"__all__ = {json.dumps(__all__表, ensure_ascii=False)}\n\n\n"
        "def 注册能力(注册表) -> None:\n"
        "    from 公共契约.能力契约.契约 import 能力实现\n\n"
        f"{注册行}\n",
        encoding="utf-8")
    return 包目录


class Test能力调用图审计(unittest.TestCase):
    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="调用图审计样本_"))
        self.模块库根 = self.临时根 / "模块库"
        self.模块库根.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.临时根, ignore_errors=True)

    def _审计(self) -> list[tuple[str, int, str]]:
        报告 = 审计模块库(self.模块库根)
        return [(违规.文件, 违规.行号, 违规.类型) for 违规 in 报告.违规列表]

    def _检出类型(self, 类型片段: str) -> list[tuple[str, int, str]]:
        return [项 for 项 in self._审计() if 类型片段 in 项[2]]

    def test_支持库导入检出(self) -> None:
        构造包(self.模块库根, "样本1",
               "from 支持库.适配层.Tesseract提供者 import 识别图片\n\ndef 能力1():\n    return 识别图片()\n",
               ["样本1.能力1"])
        命中 = self._检出类型("支持库直连")
        self.assertEqual(len(命中), 1)
        self.assertEqual(命中[0][1], 1)

    def test_read_bytes检出(self) -> None:
        构造包(self.模块库根, "样本2",
               "from pathlib import Path\n\ndef 能力2():\n    return Path('x').read_bytes()\n",
               ["样本2.能力2"])
        命中 = self._检出类型("原子旁路-文件读")
        self.assertEqual(len(命中), 1)

    def test_tempfile检出(self) -> None:
        构造包(self.模块库根, "样本丙",
               "import tempfile\n\ndef 能力丙():\n    return tempfile.mkdtemp()\n",
               ["样本丙.能力丙"])
        命中 = self._检出类型("原子旁路-临时目录")
        self.assertGreaterEqual(len(命中), 1)

    def test_subprocess检出(self) -> None:
        构造包(self.模块库根, "样本丁",
               "import subprocess\n\ndef 能力丁():\n    return subprocess.run(['ls'])\n",
               ["样本丁.能力丁"])
        命中 = self._检出类型("原子旁路-进程")
        self.assertGreaterEqual(len(命中), 1)

    def test_os系统检出(self) -> None:
        构造包(self.模块库根, "样本戊",
               "import os\n\ndef 能力戊():\n    return os.system('ls')\n",
               ["样本戊.能力戊"])
        命中 = self._检出类型("原子旁路-进程")
        self.assertGreaterEqual(len(命中), 1)

    def test_网络检出(self) -> None:
        构造包(self.模块库根, "样本己",
               "import socket\n\ndef 能力己():\n    return socket.socket()\n",
               ["样本己.能力己"])
        命中 = self._检出类型("原子旁路-网络")
        self.assertGreaterEqual(len(命中), 1)

    def test_数据库检出(self) -> None:
        构造包(self.模块库根, "样本庚",
               "import sqlite3\n\ndef 能力庚():\n    return sqlite3.connect('x.db')\n",
               ["样本庚.能力庚"])
        命中 = self._检出类型("原子旁路-数据库")
        self.assertGreaterEqual(len(命中), 1)

    def test_动态导入检出(self) -> None:
        构造包(self.模块库根, "样本辛",
               "def 能力辛():\n    return __import__('os')\n",
               ["样本辛.能力辛"])
        命中 = self._检出类型("动态导入")
        self.assertEqual(len(命中), 1)

    def test_四者漂移检出(self) -> None:
        构造包(self.模块库根, "样本壬", "def 能力壬():\n    return 1\n",
               ["样本壬.能力壬"], __all__表=["漂移名"])
        命中 = self._检出类型("漂移")
        self.assertEqual(len(命中), 1)

    def test_重复能力检出(self) -> None:
        构造包(self.模块库根, "样本癸",
               "import subprocess\n\ndef 能力癸():\n    return subprocess.run(['x'])\n",
               ["样本癸.能力癸"])
        命中 = self._检出类型("重复能力")
        self.assertEqual(len(命中), 1)

    def test_能力调用器与公共契约放行(self) -> None:
        构造包(self.模块库根, "干净包",
               "from 公共契约.基础类型.结果类型 import 结果\n"
               "from 公共契约.能力契约.调用器 import 获取能力调用器\n\n"
               "def 干净能力(文本: str) -> 结果:\n"
               "    return 获取能力调用器().调用能力('支持库.能力', {'文本': 文本})\n",
               ["干净包.干净能力"])
        self.assertEqual(self._审计(), [])

    def test_实现目录直连检出(self) -> None:
        构造包(self.模块库根, "样本子",
               "from 模块库.其他包.实现.其他 import 函数\n\ndef 能力子():\n    return 函数()\n",
               ["样本子.能力子"])
        命中 = self._检出类型("实现目录直连")
        self.assertEqual(len(命中), 1)

    def test_真实OCR审计清零确认(self) -> None:
        """OCR 经第二波迁移后支持库静态导入必须为零（S0.5 验收）。"""
        报告 = 审计模块库(系统根 / "模块库")
        OCR违规 = [违规 for 违规 in 报告.违规列表
                 if "OCR" in 违规.文件 and 违规.类型 in ("支持库直连", "原子旁路", "四者漂移")]
        self.assertFalse(OCR违规, f"OCR 迁移后必须清零，实际违规: {[违规.详情 for 违规 in OCR违规]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
