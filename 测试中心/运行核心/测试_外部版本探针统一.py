"""外部应用版本探针统一测试（第二十二阶段-工作包一）。

背景：环境指纹.探测外部应用版本 与 系统探针.检查系统工具 原为两套
独立逻辑；本测试锁定统一后行为：

- 统一版本来源：探测外部应用版本 经 检查系统工具 获取版本，
  不再独立 subprocess 逻辑（patch 生效即证明调用统一入口）
- 探针结果字段完整：成功/版本/退出码/耗时秒/错误摘要/可重试
- 失败语义：工具缺失/探针超时/退出码非零 → "失败:<错误码>" 明确失败，
  绝不返回伪造版本（如"未知"或路径冒充）
- 版本漂移：证据记录指纹（锁版本）vs 当前探针版本不符 → 校验证据有效 失败
- 主进程不加载原生扩展：fitz/PyMuPDF 不进入 sys.modules
- 真实 LibreOffice/textutil 探针成功（缺工具跳过）
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.环境指纹 import 计算环境指纹, 生成证据记录, 校验证据有效
from 支持库.适配层.系统探针 import 检查系统工具, 探针结果

macOSsoffice路径 = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")


def _查找soffice() -> str | None:
    """soffice 路径探测：PATH 或 /Applications 固定路径。"""
    return shutil.which("soffice") or (
        str(macOSsoffice路径) if macOSsoffice路径.is_file() else None
    )


def _macOS版本() -> str:
    return platform.mac_ver()[0] or platform.release()


def _成功探针(版本: str) -> 探针结果:
    return 探针结果(True, 退出码=0, 版本=版本, 耗时秒=0.05,
                    诊断="探针成功")


class Test统一版本来源(unittest.TestCase):
    """探测外部应用版本 经 系统探针 获取版本（patch 生效即证明）。"""

    def test_探测外部应用版本经系统探针(self):
        from 运行核心.环境指纹 import 探测外部应用版本
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=_成功探针("26.2.2.2"),
        ) as 探针函数:
            结果 = 探测外部应用版本()
        self.assertEqual(结果["LibreOffice"], "26.2.2.2")
        self.assertEqual(结果["textutil"], _macOS版本())
        self.assertEqual(探针函数.call_count, 2)  # LibreOffice + textutil 同一入口

    def test_环境指纹详情含统一版本(self):
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=_成功探针("26.2.2.2"),
        ):
            指纹 = 计算环境指纹()
        self.assertTrue(指纹.成功)
        self.assertEqual(指纹.详细信息["外部应用"]["LibreOffice"], "26.2.2.2")
        self.assertEqual(指纹.详细信息["外部应用"]["textutil"], _macOS版本())


class Test探针结果字段完整(unittest.TestCase):
    """探针结果 统一包含 成功/版本/退出码/耗时/错误摘要/可重试。"""

    def test_成功字段完整且错误摘要为空(self):
        结果 = _成功探针("26.2.2.2")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.退出码, 0)
        self.assertEqual(结果.版本, "26.2.2.2")
        self.assertGreater(结果.耗时秒, 0)
        self.assertEqual(结果.错误摘要, "")
        self.assertFalse(结果.可重试)

    def test_失败字段完整且错误摘要派生(self):
        结果 = 探针结果(False, 错误码="退出码非零", 退出码=3,
                        标准错误摘要="错误明细XYZ", 耗时秒=0.1,
                        诊断="soffice 退出码 3")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误摘要, "soffice 退出码 3")
        self.assertIn("错误明细XYZ", 结果.标准错误摘要)

    def test_超时标记可重试(self):
        结果 = 探针结果(False, 错误码="探针超时", 诊断="卡住已强杀",
                        可重试=True)
        self.assertTrue(结果.可重试)
        self.assertEqual(结果.错误摘要, "卡住已强杀")

    def test_真实探针超时标记可重试(self):
        """真实 检查系统工具 超时 → 错误码 探针超时 + 可重试。"""
        结果 = 检查系统工具(
            "卡住工具",
            [sys.executable, "-c", "import time; time.sleep(30)"],
            超时秒=0.5,
        )
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "探针超时")
        self.assertTrue(结果.可重试)
        self.assertIn("超时", 结果.错误摘要)


class Test失败语义(unittest.TestCase):
    """工具缺失/探针超时/退出码非零 → 明确失败，绝不伪造版本。"""

    def test_工具缺失明确失败(self):
        from 运行核心.环境指纹.环境指纹 import 探测外部应用版本
        with mock.patch("运行核心.环境指纹.环境指纹.shutil.which",
                        return_value=None):
            结果 = 探测外部应用版本()
        self.assertEqual(结果["LibreOffice"], "失败:工具缺失")
        self.assertEqual(结果["textutil"], "失败:工具缺失")
        # 失败标记不是伪造版本
        for 值 in 结果.values():
            self.assertNotEqual(值, "未知")
            self.assertFalse(值.startswith("/"))  # 不以路径冒充版本

    def test_探针超时明确失败(self):
        from 运行核心.环境指纹 import 探测外部应用版本
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=探针结果(False, 错误码="探针超时",
                                   诊断="soffice 探针超时", 可重试=True),
        ):
            结果 = 探测外部应用版本()
        self.assertEqual(结果["LibreOffice"], "失败:探针超时")
        self.assertEqual(结果["textutil"], "失败:探针超时")

    def test_退出码非零明确失败(self):
        from 运行核心.环境指纹 import 探测外部应用版本
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=探针结果(False, 错误码="退出码非零", 退出码=3,
                                   诊断="soffice 退出码 3"),
        ):
            结果 = 探测外部应用版本()
        self.assertEqual(结果["LibreOffice"], "失败:退出码非零")
        self.assertNotEqual(结果["LibreOffice"], "未知")

    def test_真实退出码非零失败(self):
        """真实命令退出码非0 → 错误码 退出码非零 + 退出码带回。"""
        结果 = 检查系统工具(
            "失败工具", [sys.executable, "-c", "import sys; sys.exit(3)"])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "退出码非零")
        self.assertEqual(结果.退出码, 3)
        self.assertTrue(结果.错误摘要)


class Test版本漂移(unittest.TestCase):
    """锁版本（证据记录指纹）vs 探针版本不符 → 校验证据有效 失败。"""

    def test_探针版本漂移证据失效(self):
        临时 = Path(tempfile.mkdtemp())
        证据文件 = 临时 / "证据.json"
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=_成功探针("26.2.2.2"),
        ):
            生成证据记录(证据文件, {"测试": "锁定"})
        记录 = json.loads(证据文件.read_text(encoding="utf-8"))
        self.assertEqual(记录["指纹详情"]["外部应用"]["LibreOffice"],
                         "26.2.2.2")
        # 探针版本漂移 → 指纹变化 → 证据失效
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=_成功探针("26.2.3.0"),
        ):
            校验 = 校验证据有效(证据文件)
        self.assertFalse(校验.成功)
        self.assertTrue(any("环境指纹漂移" in 问题
                            for 问题 in 校验.问题列表))

    def test_探针失败后证据失效不伪造(self):
        """探针失败（版本变失败标记）→ 指纹变化 → 证据失效。"""
        临时 = Path(tempfile.mkdtemp())
        证据文件 = 临时 / "证据.json"
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=_成功探针("26.2.2.2"),
        ):
            生成证据记录(证据文件)
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=探针结果(False, 错误码="工具缺失",
                                   诊断="未找到 LibreOffice"),
        ):
            校验 = 校验证据有效(证据文件)
        self.assertFalse(校验.成功)
        self.assertTrue(any("环境指纹漂移" in 问题
                            for 问题 in 校验.问题列表))


class Test主进程不加载原生扩展(unittest.TestCase):
    """fitz/PyMuPDF 等原生扩展禁止主进程加载（版本走发行包元数据）。"""

    def test_计算指纹不加载fitz(self):
        with mock.patch(
            "支持库.适配层.系统探针.检查系统工具",
            return_value=_成功探针("26.2.2.2"),
        ):
            指纹 = 计算环境指纹()
        self.assertTrue(指纹.成功)
        self.assertNotIn("fitz", sys.modules)
        self.assertNotIn("PyMuPDF", sys.modules)

    def test_第三方版本经元数据非import(self):
        指纹 = 计算环境指纹(含外部应用=False)
        第三方 = 指纹.详细信息["第三方"]
        self.assertIn("PyMuPDF", 第三方)
        self.assertTrue(第三方["PyMuPDF"])  # 真实发行版本或"未安装"，非异常
        self.assertNotIn("fitz", sys.modules)


class Test真实探针(unittest.TestCase):
    """真实 LibreOffice/textutil 探针成功（缺工具跳过）。"""

    def test_LibreOffice真实探针(self):
        soffice = _查找soffice()
        if not soffice:
            self.skipTest("LibreOffice 不可用")
        探针 = 检查系统工具("LibreOffice soffice", [soffice])
        self.assertTrue(探针.成功, 探针.诊断)
        self.assertEqual(探针.退出码, 0)
        self.assertRegex(探针.版本, r"^\d+(?:\.\d+)+$")
        self.assertEqual(探针.错误摘要, "")
        from 运行核心.环境指纹 import 探测外部应用版本
        结果 = 探测外部应用版本()
        self.assertEqual(结果["LibreOffice"], 探针.版本)

    def test_textutil真实探针(self):
        textutil = shutil.which("textutil")
        if not textutil:
            self.skipTest("textutil 不可用")
        探针 = 检查系统工具("textutil", [textutil], 版本参数="-help")
        self.assertTrue(探针.成功, 探针.诊断)
        self.assertEqual(探针.退出码, 0)
        self.assertTrue(探针.版本)
        from 运行核心.环境指纹 import 探测外部应用版本
        结果 = 探测外部应用版本()
        self.assertEqual(结果["textutil"], _macOS版本())


if __name__ == "__main__":
    unittest.main()
