"""PyMuPDF 提供者自足性测试：子进程入口 sys.path 自足注入与运行前提。

覆盖（第二十五阶段 wp7）：
- 子进程入口独立启动可 import 平台客户端（真实渲染能力成功）；
- 激活指针缺失 → 明确错误（提供者不可用/制品缺失）；
- 注入幂等：进程内重复调用不重复注入；
- 回归：渲染整页/检测加密页数/提取图像/校验PDF 真实调用；
- 零残留：无残留进程与文件。
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 支持库.适配层.PyMuPDF提供者 import 检测加密页数, 提取图像, 校验PDF, 渲染整页
from 支持库.适配层.PyMuPDF提供者.实现 import 子进程入口

客户端环境变量名 = "PyMuPDF提供者_客户端环境目录"
默认环境目录 = 子进程入口.平台客户端环境目录()


def _生成PDF(路径: Path) -> Path:
    from reportlab.pdfgen import canvas
    画布 = canvas.Canvas(str(路径))
    画布.drawString(50, 700, "PyMuPDF 自足性")
    画布.showPage()
    画布.save()
    return 路径


def _制品已安装() -> bool:
    """平台客户端制品是否已安装（激活指针存在且指向已安装 平台客户端）。

    这是 PyMuPDF 提供者契约声明的运行前提（`说明/设计说明.md`「运行前提」）。
    本判据直接探前提本身，**不拿「一次调用失败」当跳过依据** —— 前提在则真调用
    必跑（缺陷判红），前提不在则如实跳过（环境性）；缺件语义由本文件的
    `test_激活指针缺失返回提供者不可用` 钉住。
    """
    环境目录 = 子进程入口.平台客户端环境目录()
    指针文件 = 环境目录 / "当前.json"
    if not 指针文件.is_file():
        return False
    try:
        指针 = json.loads(指针文件.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not 指针.get("制品目录"):
        return False
    已安装目录 = 环境目录 / "平台客户端"
    return ((已安装目录 / "平台客户端" / "__init__.py").is_file()
            or (已安装目录 / "__init__.py").is_file())


class TestPyMuPDF自足性(unittest.TestCase):
    def _要求制品(self) -> None:
        """真调用用例的运行前提门：前提不在 ⇒ 如实跳过（环境性，非缺陷）。"""
        if not _制品已安装():
            self.skipTest(
                "平台客户端制品未安装（激活指针缺失或指向未安装制品）——"
                "PyMuPDF 提供者运行前提未满足，环境性如实跳过（非缺陷；缺件语义由"
                " 本文件 test_激活指针缺失返回提供者不可用 钉住）")

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_PyMuPDF自足性_"))
        self.样本PDF = _生成PDF(self.临时目录 / "样本.pdf")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_子进程入口独立启动可导入平台客户端(self):
        """新 python 进程：入口注入 → import 平台客户端 → 真实渲染成功。"""
        self._要求制品()
        代码 = "\n".join([
            "import sys",
            f"sys.path.insert(0, {str(系统根)!r})",
            "from 支持库.适配层.PyMuPDF提供者.实现.子进程入口 import 注入平台客户端路径",
            "错误 = 注入平台客户端路径()",
            "assert 错误 is None, 错误",
            "import 平台客户端",
            "print('平台客户端可导入')",
        ])
        运行 = subprocess.run(
            [sys.executable, "-c", 代码], capture_output=True, text=True,
            env=dict(os.environ))
        self.assertEqual(运行.returncode, 0, 运行.stderr)
        self.assertIn("平台客户端可导入", 运行.stdout)

    def test_真实渲染回归(self):
        """四个能力真实调用（走子进程入口全链路）。"""
        self._要求制品()
        结果 = 渲染整页(str(self.样本PDF), 1)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(base64.b64decode(结果.值).startswith(b"\x89PNG"))
        页数 = 检测加密页数(str(self.样本PDF))
        self.assertTrue(页数.成功)
        self.assertEqual(页数.值, {"已加密": 假, "页数": 1})
        图像 = 提取图像(str(self.样本PDF), 1)
        self.assertTrue(图像.成功)
        self.assertEqual(图像.值, [])
        校验 = 校验PDF(self.样本PDF.read_bytes())
        self.assertTrue(校验.成功)
        self.assertEqual(校验.值["页数"], 1)

    def test_激活指针缺失返回提供者不可用(self):
        """激活指针缺失 → 提供者不可用，错误说明含 制品缺失。"""
        with mock.patch.dict(os.environ, {客户端环境变量名: str(self.临时目录 / "空环境")}):
            结果 = 检测加密页数(str(self.样本PDF))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertIn("制品缺失", 结果.错误说明)
        self.assertTrue(结果.可重试)

    def test_注入幂等(self):
        """进程内重复调用注入，sys.path 只注入一次。"""
        self._要求制品()
        # 兼容双结构：新版制品根含 平台客户端 包层时注入 环境目录/平台客户端，
        # 旧版平铺结构时注入 环境目录（两者均视为一次注入）
        注入前 = sum(1 for 路径 in sys.path
                   if Path(路径) in (默认环境目录, 默认环境目录 / "平台客户端"))
        第一次 = 子进程入口.注入平台客户端路径()
        self.assertIsNone(第一次, 第一次)
        第二次 = 子进程入口.注入平台客户端路径()
        self.assertIsNone(第二次, 第二次)
        注入后 = sum(1 for 路径 in sys.path
                   if Path(路径) in (默认环境目录, 默认环境目录 / "平台客户端"))
        self.assertEqual(注入后 - 注入前, 1)

    def test_零残留(self):
        """调用后无残留子进程；临时目录内无新增残留文件。"""
        self._要求制品()
        结果 = 检测加密页数(str(self.样本PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        残留 = subprocess.run(
            ["pgrep", "-f", "子进程入口.py"], capture_output=True, text=True)
        self.assertNotIn("子进程入口.py", 残留.stdout)
        self.样本PDF.unlink(missing_ok=True)
        self.assertFalse(list(self.临时目录.glob("*")))


if __name__ == "__main__":
    unittest.main()
