"""OCR 模块迁移测试（unittest）。

setUpClass 装配全局能力调用器（安装支持库 + 创建并绑定唯一能力调用服务），
覆盖：公开入口/注册对称、参数错误（模块层校验）、平台不可用（提供者不可用）、
中文结果对称与调用器边界（取消令牌id 语义下支持库侧不传 callable）、
错误码透传、可用性检查组合、真实 tesseract 最小调用。
"""

from __future__ import annotations

import base64
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.OCR import 注册能力
from 模块库.OCR import 可用性检查
from 模块库.OCR import 识别图片文件
from 模块库.OCR import 识别图片文字

测试文本 = "OCR 12345"


def _工具可用() -> bool:
    import shutil as 壳工具
    return 壳工具.which("tesseract") is not None


class 假调用器:
    """测试注入的假能力调用器：记录调用并返回预设结果。"""

    def __init__(self, 预设结果):
        self.预设结果 = 预设结果
        self.调用历史: list[tuple[str, dict]] = []

    def 调用能力(self, 能力id, 参数=None, **关键字):
        self.调用历史.append((能力id, dict(参数 or {})))
        return self.预设结果

    def 幂等重放(self, 能力id, 参数):
        return False

    def 查询调用历史(self, 上限=50):
        return []

    def 最近失败(self, 上限=10):
        return []

    def 回答九问(self, 能力id, 错误码):
        return {}


class TestOCR模块(unittest.TestCase):
    """OCR 模块迁移测试：装配调用器后经调用边界验证。"""

    @classmethod
    def setUpClass(cls):
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定
        from 运行核心.加载器.包安装.支持库安装 import 安装全部支持库

        cls.注册表 = 能力注册表()
        安装全部支持库(系统根 / "支持库", cls.注册表)
        cls.服务 = 创建并绑定(cls.注册表)

    def setUp(self):
        from 支持库.适配层.Pillow提供者 import 生成占位图

        self.临时目录 = tempfile.mkdtemp(prefix="测试_OCR模块_")
        占位 = 生成占位图(宽度=900, 高度=200, 占位类型="文本",
                       背景颜色="#FFFFFF", 前景颜色="#000000", 文本=测试文本)
        self.assertTrue(占位.成功, f"生成占位图失败: {占位.错误说明}")
        self.图片字节 = base64.b64decode(占位.值["图像b64"])
        self.图片路径 = str(Path(self.临时目录) / "测试.png")
        Path(self.图片路径).write_bytes(self.图片字节)

    def tearDown(self):
        shutil.rmtree(self.临时目录, ignore_errors=True)

    # ── 公开入口与注册对称 ──────────────────────────────

    def test_公开入口可导入与注册能力齐全(self):
        for 能力名 in ["识别图片文字", "识别图片文件", "可用性检查"]:
            self.assertTrue(callable(globals()[能力名]), f"{能力名} 未从公开入口导出")
        from 公共契约.能力契约.契约 import 能力注册表 as 注册表类

        注册表 = 注册表类()
        注册能力(注册表)
        for 能力id in ["OCR.识别图片文字", "OCR.识别图片文件", "OCR.可用性检查"]:
            self.assertIn(能力id, 注册表.能力id列表)

    # ── 参数错误（模块层校验，不触达支持库）─────────────

    def test_路径字节同时给参数不合法(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 图片字节=self.图片字节)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_路径字节都缺参数不合法(self):
        结果 = 识别图片文字()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_识别图片文件空路径参数不合法(self):
        结果 = 识别图片文件(图片路径="")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    # ── 平台不可用 ──────────────────────────────────────

    def test_平台不可用提供者不可用(self):
        import 公共契约.能力契约.调用器 as 调用器契约

        with mock.patch.object(
            调用器契约, "获取能力调用器",
            side_effect=RuntimeError("能力调用器未注入"),
        ):
            结果 = 识别图片文字(图片路径=self.图片路径)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")

    # ── 中文结果对称与调用器边界 ─────────────────────────

    def test_中文结果对称经调用器透传(self):
        from 公共契约.能力契约.调用器 import 注册能力调用器
        from 模块库.OCR.实现 import OCR as 模块实现

        中文结果 = 结果.成功结果({"文本": "中文识别结果"})
        调用器 = 假调用器(中文结果)
        注册能力调用器(调用器)
        try:
            返回值 = 模块实现.识别图片文字(图片路径=self.图片路径)
        finally:
            注册能力调用器(self.服务)
        self.assertTrue(返回值.成功)
        self.assertEqual(返回值.值, {"文本": "中文识别结果"})
        能力id, 请求参数 = 调用器.调用历史[0]
        self.assertEqual(能力id, "OCR识别.识别图片")
        self.assertEqual(请求参数["图片路径"], self.图片路径)
        self.assertIsNone(请求参数["取消事件"], "取消令牌id 语义下支持库侧不得传 callable")

    def test_取消令牌id透传且支持库侧无callable(self):
        from 公共契约.能力契约.调用器 import 注册能力调用器
        from 模块库.OCR.实现 import OCR as 模块实现

        调用器 = 假调用器(结果.成功结果({"文本": "识别结果"}))
        注册能力调用器(调用器)
        try:
            模块实现.识别图片文字(图片路径=self.图片路径, 取消令牌id="令牌甲")
        finally:
            注册能力调用器(self.服务)
        能力id, 请求参数 = 调用器.调用历史[0]
        self.assertEqual(能力id, "OCR识别.识别图片")
        self.assertIsNone(请求参数["取消事件"])

    def test_错误码透传(self):
        from 公共契约.能力契约.调用器 import 注册能力调用器
        from 模块库.OCR.实现 import OCR as 模块实现

        调用器 = 假调用器(结果.失败("超时", "执行超时", 可重试=True))
        注册能力调用器(调用器)
        try:
            调用结果 = 模块实现.识别图片文字(图片路径=self.图片路径)
        finally:
            注册能力调用器(self.服务)
        self.assertFalse(调用结果.成功)
        self.assertEqual(调用结果.错误码, "超时")
        self.assertTrue(调用结果.可重试)

    def test_可用性检查组合两个支持库能力(self):
        from 公共契约.能力契约.调用器 import 注册能力调用器
        from 模块库.OCR.实现 import OCR as 模块实现

        调用器 = 假调用器(结果.成功结果({
            "tesseract": "tesseract", "版本": "5.3.0", "满足最低版本": True,
        }))
        注册能力调用器(调用器)
        try:
            检查结果 = 模块实现.可用性检查()
        finally:
            注册能力调用器(self.服务)
        self.assertTrue(检查结果.成功)
        self.assertEqual(检查结果.值["tesseract"], "tesseract")
        调用能力id表 = [历史[0] for 历史 in 调用器.调用历史]
        self.assertEqual(调用能力id表, ["OCR识别.版本探针", "OCR识别.语言包列表"])

    # ── 真实 tesseract 最小调用 ──────────────────────────

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实识别路径入口(self):
        结果 = 识别图片文字(图片路径=self.图片路径)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("12345", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实识别字节入口(self):
        结果 = 识别图片文字(图片字节=self.图片字节)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("OCR", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实词级数据(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 词级数据=True)
        self.assertTrue(结果.成功, f"词级识别失败: {结果.错误码} {结果.错误说明}")
        词列表 = 结果.值["词列表"]
        self.assertGreater(len(词列表), 0)
        词文本 = [词["文本"] for 词 in 词列表]
        self.assertTrue(any("12345" in 词 for 词 in 词文本), f"未识别出目标词: {词文本}")

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实识别图片文件入口(self):
        结果 = 识别图片文件(图片路径=self.图片路径)
        self.assertTrue(结果.成功, f"识别失败: {结果.错误码} {结果.错误说明}")
        self.assertIn("12345", 结果.值["文本"])

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实可用性检查(self):
        结果 = 可用性检查()
        self.assertTrue(结果.成功, f"可用性检查失败: {结果.错误码} {结果.错误说明}")
        值 = 结果.值
        self.assertTrue(值["版本"])
        self.assertTrue(值["满足最低版本"])
        self.assertIn("eng", 值["语言列表"])
        self.assertGreater(值["语言数量"], 0)

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实语言包缺失语义(self):
        结果 = 识别图片文字(图片路径=self.图片路径, 语言="xx_不存在")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "语言包缺失")

    @unittest.skipUnless(_工具可用(), "本机未配置 tesseract，如实跳过")
    def test_真实文件不存在(self):
        结果 = 识别图片文字(图片路径="/不存在的路径/图片.png")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")


if __name__ == "__main__":
    unittest.main()
