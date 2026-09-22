"""PyMuPDF 提供者测试：真实 PDF 加密检测/页数/渲染/校验 + 超时与崩溃注入。
架构验证：主进程不加载 fitz（SWIG 崩溃隔离）；子进程覆盖启动/调用/超时/崩溃/
重启/停止与残留清理；提供者不可用走环境变量依赖注入。
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

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时.平台适配 import 子进程组启动标志
from 支持库.适配层.PyMuPDF提供者 import 检测加密页数, 渲染整页, 提取图像, 校验PDF
from 支持库.适配层.PyMuPDF提供者.实现 import 提供者 as 提供者模块

最小PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
def _生成文本PDF(路径: Path, 页数: int = 1) -> Path:
    from reportlab.pdfgen import canvas
    画布 = canvas.Canvas(str(路径))
    for 页 in range(页数):
        画布.drawString(50, 700, f"PyMuPDF provider page {页 + 1}")
        画布.showPage()
    画布.save()
    return 路径
def _生成带图PDF(路径: Path) -> Path:
    import io
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    画布 = canvas.Canvas(str(路径))
    画布.drawImage(ImageReader(io.BytesIO(最小PNG)), 50, 600, width=80, height=80)
    画布.save()
    return 路径
def _生成加密PDF(路径: Path) -> Path:
    """子进程内 fitz 生成带密码 PDF（测试进程仍不加载 fitz）。"""
    代码 = ("import fitz;d=fitz.open();d.new_page();"
            f"d.save({str(路径)!r}, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='o', user_pw='u')")
    subprocess.run([sys.executable, "-c", 代码], check=True, capture_output=True)
    return 路径
def _退出子进程(码: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import os; os._exit({码})"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **子进程组启动标志(),
    )
def _关闭进程(进程: subprocess.Popen) -> None:
    try:
        进程.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
        if 流:
            try:
                流.close()
            except (OSError, ValueError):
                pass


def _制品已安装() -> bool:
    """平台客户端制品是否已安装（激活指针存在且指向已安装 平台客户端）。

    这是 PyMuPDF 提供者**契约声明的运行前提**（`说明/设计说明.md`「运行前提」：
    「依赖平台客户端制品已安装（激活指针存在）」）。子进程入口 `注入平台客户端路径()`
    解析 `工程缓存/制品仓库/平台客户端环境/当前.json`，缺失/不可读/指向未安装即回
    `提供者不可用`。

    本判据**直接探运行前提本身**（激活指针 + 已安装制品），**不拿「一次调用失败」
    当跳过依据** —— 那样会把真缺陷（入口坏了/子进程拉不起来）混进「环境性跳过」。
    前提在则真调用必跑（缺陷会被判红）；前提不在则如实跳过（环境性）。
    缺件语义由 `测试_PyMuPDF自足性.test_激活指针缺失返回提供者不可用` 钉住。
    """
    from 支持库.适配层.PyMuPDF提供者.实现 import 子进程入口 as 入口模块
    环境目录 = 入口模块.平台客户端环境目录()
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


class TestPyMuPDF提供者(unittest.TestCase):
    def _要求制品(self) -> None:
        """真调用用例的运行前提门：前提不在 ⇒ 如实跳过（环境性，非缺陷）。"""
        if not _制品已安装():
            self.skipTest(
                "平台客户端制品未安装（激活指针缺失或指向未安装制品）——"
                "PyMuPDF 提供者运行前提未满足，环境性如实跳过（非缺陷；缺件语义由"
                " 测试_PyMuPDF自足性.test_激活指针缺失返回提供者不可用 钉住）")

    def setUp(self):
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试_PyMuPDF提供者_"))
        self.文本PDF = _生成文本PDF(self.临时目录 / "文本.pdf", 页数=2)
        self.带图PDF = _生成带图PDF(self.临时目录 / "带图.pdf")
    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)
    def test_主进程不加载fitz(self):
        self.assertNotIn("fitz", sys.modules)
        检测加密页数(str(self.文本PDF))
        self.assertNotIn("fitz", sys.modules)
    def test_检测加密页数正常(self):
        self._要求制品()
        结果 = 检测加密页数(str(self.文本PDF))
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, {"已加密": 假, "页数": 2})
    def test_检测加密页数文件不存在(self):
        结果 = 检测加密页数(str(self.临时目录 / "不存在.pdf"))
        self.assertEqual(结果.错误码, "文件不存在")
    def test_检测加密页数加密文件返回文件加密(self):
        self._要求制品()
        加密PDF = _生成加密PDF(self.临时目录 / "加密.pdf")
        结果 = 检测加密页数(str(加密PDF))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件加密")
        self.assertEqual(结果.详细信息["值"], {"已加密": 真, "页数": 0})
    def test_渲染整页返回PNG(self):
        self._要求制品()
        结果 = 渲染整页(str(self.文本PDF), 1)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue(base64.b64decode(结果.值).startswith(b"\x89PNG"))
    def test_渲染整页页序号越界(self):
        self._要求制品()
        结果 = 渲染整页(str(self.文本PDF), 9)
        self.assertEqual(结果.错误码, "参数不合法")
    def test_提取图像带图页(self):
        self._要求制品()
        结果 = 提取图像(str(self.带图PDF), 1)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(len(结果.值), 1)
        图像 = 结果.值[0]
        self.assertIn("xref", 图像)
        self.assertTrue(base64.b64decode(图像["字节b64"]).startswith(b"\x89PNG"))
        self.assertEqual(图像["尺寸"]["宽度"], 1)
    def test_提取图像无图页返回空列表(self):
        self._要求制品()
        结果 = 提取图像(str(self.文本PDF), 1)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值, [])
    def test_校验PDF正常(self):
        self._要求制品()
        结果 = 校验PDF(self.文本PDF.read_bytes())
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["页数"], 2)
    def test_校验PDF损坏字节(self):
        self._要求制品()
        结果 = 校验PDF(b"%PDF-1.4\n%%EOF broken-fragment")
        self.assertEqual(结果.错误码, "文件损坏")
    def test_校验PDF非法参数(self):
        self.assertEqual(校验PDF(b"").错误码, "参数不合法")
    def test_超时返回超时(self):
        def 挂起执行(请求, 超时秒=提供者模块.默认超时秒):
            进程 = 提供者模块._启动子进程()
            try:
                进程.communicate(timeout=0.5)  # 不发请求 → 子进程阻塞 → 真实超时
            except subprocess.TimeoutExpired:
                return 提供者模块._失败("超时", "模拟超时", 可重试=真)
            finally:
                提供者模块._终止进程组(进程)
                for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
                    if 流:
                        流.close()
            return 提供者模块._失败("超时", "模拟超时", 可重试=真)
        with mock.patch.object(提供者模块, "执行任务", side_effect=挂起执行):
            结果 = 渲染整页(str(self.文本PDF), 1)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)
    def test_子进程崩溃返回提供者崩溃(self):
        with mock.patch.object(提供者模块, "_启动子进程", side_effect=lambda: _退出子进程(7)), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            结果 = 校验PDF(self.文本PDF.read_bytes())
        self.assertEqual(结果.错误码, "提供者崩溃")
        self.assertTrue(结果.可重试)
    def test_重启恢复(self):
        self._要求制品()
        原始启动 = 提供者模块._启动子进程
        计数 = {"n": 0}
        def 先崩后正常():
            计数["n"] += 1
            return _退出子进程(9) if 计数["n"] == 1 else 原始启动()
        with mock.patch.object(提供者模块, "_启动子进程", side_effect=先崩后正常), \
                mock.patch.object(提供者模块, "_终止进程组", side_effect=_关闭进程):
            第一次 = 渲染整页(str(self.文本PDF), 1)
            第二次 = 渲染整页(str(self.文本PDF), 1)
        self.assertEqual(第一次.错误码, "提供者崩溃")
        self.assertTrue(第二次.成功, 第二次.错误说明)
    def test_无残留与停止清理(self):
        self._要求制品()
        for _ in range(3):
            检测加密页数(str(self.文本PDF))
        进程 = 提供者模块._启动子进程()
        self.assertIsNone(进程.poll())
        提供者模块.等待并收集([进程])
        for 流 in (进程.stdin, 进程.stdout, 进程.stderr):
            if 流:
                流.close()
        self.assertIsNotNone(进程.poll())
if __name__ == "__main__":
    unittest.main()
