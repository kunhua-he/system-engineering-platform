"""项目编译器工作包测试：依赖闭包、循环/缺依赖阻断与启动器零 pyc。"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from 开发工具.项目编译.项目编译器 import _解析依赖闭包, 编译项目
from 开发工具.项目编译.正式包索引 import 构建索引, 校验能力引用, 校验显式包引用, 解析依赖闭包
from 开发工具.快速编译.运行快速编译 import _全局能力所有者


def _包(包id: str, 依赖: list | None = None, 能力: list | None = None) -> tuple[Path, dict]:
    return Path("/虚拟") / 包id, {
        "包id": 包id,
        "版本": "1.0.0",
        "依赖": 依赖 or [],
        "能力": 能力 or [],
    }


class 测试项目编译器(unittest.TestCase):
    def _验证模块Provider闭包(self, 模块id: str, 提供者id: str):
        支持库, _, _ = 解析依赖闭包(Path.cwd(), set(), {模块id})
        self.assertIn(提供者id, 支持库)

    def test_OCR模块闭包包含Tesseract(self):
        self._验证模块Provider闭包("模块库.OCR", "支持库.适配层.Tesseract提供者")

    def test_图像处理模块闭包包含Pillow(self):
        self._验证模块Provider闭包("模块库.图像处理", "支持库.适配层.Pillow提供者")

    def test_媒体处理模块闭包包含FFmpeg(self):
        self._验证模块Provider闭包("模块库.媒体处理", "支持库.适配层.FFmpeg提供者")

    def test_媒体转写模块闭包包含MLXWhisper(self):
        self._验证模块Provider闭包("模块库.媒体转写", "支持库.适配层.MLXWhisper提供者")

    def test_文档解析模块闭包包含LibreOffice(self):
        self._验证模块Provider闭包("模块库.文档解析", "支持库.适配层.LibreOffice提供者")

    def test_文档生成模块闭包包含PDF隔离(self):
        self._验证模块Provider闭包("模块库.文档生成", "支持库.适配层.PDF隔离提供者")

    def test_自修复模块闭包包含Git(self):
        self._验证模块Provider闭包("模块库.自修复工具", "支持库.适配层.Git提供者")

    def test_模板不进入正式索引与owner(self):
        索引 = 构建索引(Path.cwd())
        self.assertNotIn("模块库._模板", 索引["模块库"])
        self.assertIn("模块库._模板", 索引["排除包"])
        self.assertNotIn("_模板.示例能力", 索引["能力所有者"])
        self.assertNotIn("_模板.示例能力", _全局能力所有者())

    def test_显式模板包和能力引用_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "被拒绝"):
            校验显式包引用(Path.cwd(), "模块库._模板")
        with self.assertRaisesRegex(ValueError, "被拒绝"):
            校验能力引用(Path.cwd(), "_模板.示例能力")

    def test_项目引用模板_fail_closed(self):
        根 = Path(tempfile.mkdtemp(prefix="项目编译器模板阻断_"))
        (根 / "后端").mkdir()
        (根 / "项目声明.json").write_text(
            json.dumps({"项目id": "测试.模板阻断"}, ensure_ascii=False), encoding="utf-8"
        )
        (根 / "后端" / "模块引用.json").write_text(
            json.dumps({"模块id": "模块库._模板"}, ensure_ascii=False), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "被拒绝|没有发现能力id"):
            编译项目(根, 根 / "制品")

    def test_支持库能力依赖递归进入闭包(self):
        支持库 = {
            "支持库.甲": _包("支持库.甲", [{"能力": "能力.乙"}], [{"能力id": "能力.甲"}]),
            "支持库.乙": _包("支持库.乙", [], [{"能力id": "能力.乙"}]),
        }
        支持库选中, 模块选中, 锁 = _解析依赖闭包(
            支持库, {}, {"能力.甲": "支持库.甲", "能力.乙": "支持库.乙"},
            {"支持库.甲"}, set())
        self.assertEqual(支持库选中, {"支持库.甲", "支持库.乙"})
        self.assertEqual(模块选中, set())
        self.assertEqual(锁[0]["目标包"], "支持库.乙")

    def test_循环和缺依赖_fail_closed(self):
        表 = {
            "支持库.甲": _包("支持库.甲", [{"包id": "支持库.乙"}]),
            "支持库.乙": _包("支持库.乙", [{"包id": "支持库.甲"}]),
        }
        with self.assertRaisesRegex(ValueError, "依赖循环"):
            _解析依赖闭包(表, {}, {}, {"支持库.甲"}, set())
        with self.assertRaisesRegex(ValueError, "不存在"):
            _解析依赖闭包({"支持库.甲": _包("支持库.甲", [{"包id": "支持库.不存在"}])}, {}, {}, {"支持库.甲"}, set())

    def test_新鲜制品启动入口不写pyc(self):
        根 = Path(tempfile.mkdtemp(prefix="项目编译器工作包_"))
        制品 = 根 / "制品"
        编译项目(Path("示例项目/可双击演示/开发文件夹"), 制品)
        锁 = json.loads((制品 / "依赖锁.json").read_text(encoding="utf-8"))
        self.assertTrue(锁["依赖闭包"])
        环境 = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        结果 = subprocess.run(
            ["python3.14", "-B", str(制品 / "运行入口" / "启动.py"), "--帮助"],
            cwd=制品, env=环境, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(结果.returncode, 2)
        self.assertEqual(list(制品.rglob("*.pyc")), [])
        self.assertEqual(list(制品.rglob("__pycache__")), [])
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", (制品 / "运行入口" / "启动网页.command").read_text())
        self.assertIn("-B", (制品 / "运行入口" / "启动网页.bat").read_text())


if __name__ == "__main__":
    unittest.main()
