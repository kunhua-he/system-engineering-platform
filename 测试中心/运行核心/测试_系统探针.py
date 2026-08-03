"""系统级提供者健康探针测试：真实探针/超时强杀/退出码非0/标准错误摘要/
工具缺失/主进程不崩溃/提供者入口「外部提供者不可用」映射。

风格与 测试_运行环境管理器.py 一致：sys.path 注入系统根、unittest 用例。
真实工具（LibreOffice/textutil）探针走真实独立子进程；失败路径
（超时/退出码非0/缺失）用真实命令构造；提供者入口的不可用映射
用 mock 探针返回（测试内合法用法，生产代码不 mock）。
"""

from __future__ import annotations

import platform
import shutil
import sys
import time
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.运行环境管理器.系统探针 import 检查系统工具, 探针结果

macOSsoffice路径 = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")


def _查找soffice() -> str | None:
    """soffice 路径探测：PATH 或 /Applications 固定路径。"""
    return shutil.which("soffice") or (
        str(macOSsoffice路径) if macOSsoffice路径.is_file() else None
    )


class Test系统探针真实工具(unittest.TestCase):
    """真实工具独立进程探针成功（返回版本）。"""

    def test_textutil真实探针(self):
        textutil = shutil.which("textutil")
        if not textutil:
            self.skipTest("textutil 不可用")
        结果 = 检查系统工具("textutil", [textutil], 版本参数="-help")
        self.assertTrue(结果.成功, 结果.诊断)
        self.assertEqual(结果.退出码, 0)
        self.assertTrue(结果.版本)
        self.assertGreater(结果.耗时秒, 0)

    def test_soffice真实探针(self):
        soffice = _查找soffice()
        if not soffice:
            self.skipTest("LibreOffice 不可用")
        结果 = 检查系统工具("LibreOffice soffice", [soffice])
        self.assertTrue(结果.成功, 结果.诊断)
        self.assertEqual(结果.退出码, 0)
        self.assertRegex(结果.版本, r"^\d+(?:\.\d+)+$")

    def test_textutil提供者真实检查(self):
        """textutil提供者.检查提供者 → 可用 + macOS 版本 + 退出码。"""
        from 支持库.适配层.textutil提供者.实现.文本转换 import 检查提供者
        结果 = 检查提供者()
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["textutil"], "可用")
        self.assertEqual(结果.值["退出码"], 0)
        self.assertEqual(结果.值["版本"],
                         platform.mac_ver()[0] or platform.release())

    def test_LibreOffice提供者真实检查(self):
        """LibreOffice提供者.检查提供者 → 可用 + 版本 + 退出码。"""
        if not _查找soffice():
            self.skipTest("LibreOffice 不可用")
        from 支持库.适配层.LibreOffice提供者.实现.文档转换 import 检查提供者
        结果 = 检查提供者()
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["LibreOffice"], "可用")
        self.assertEqual(结果.值["退出码"], 0)
        self.assertRegex(结果.值["版本"], r"^\d+(?:\.\d+)+$")


class Test系统探针失败路径(unittest.TestCase):
    """超时强杀/退出码非0/工具缺失/标准错误摘要/主进程不崩溃。"""

    def test_探针超时强杀(self):
        """命令卡住 → 超时返回失败（terminate→kill），主进程不受影响。"""
        开始 = time.monotonic()
        结果 = 检查系统工具(
            "卡住工具",
            [sys.executable, "-c", "import time; time.sleep(30)"],
            超时秒=0.5,
        )
        耗时 = time.monotonic() - 开始
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "探针超时")
        self.assertIsNone(结果.退出码)
        self.assertLess(耗时, 20)  # 强杀生效，未等满 30 秒

    def test_退出码非零(self):
        结果 = 检查系统工具(
            "失败工具", [sys.executable, "-c", "import sys; sys.exit(3)"])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "退出码非零")
        self.assertEqual(结果.退出码, 3)

    def test_工具缺失(self):
        结果 = 检查系统工具("不存在工具", ["/usr/bin/肯定不存在的命令xyz"])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "工具缺失")
        self.assertIsNone(结果.退出码)
        self.assertIn("不存在", 结果.诊断)

    def test_标准错误摘要捕获(self):
        结果 = 检查系统工具(
            "报错工具",
            [sys.executable, "-c",
             "import sys; print('探针标准错误内容XYZ', file=sys.stderr); sys.exit(1)"],
        )
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "退出码非零")
        self.assertIn("探针标准错误内容XYZ", 结果.标准错误摘要)

    def test_探针失败主进程不崩溃(self):
        """探针失败后主进程继续执行（后续调用正常返回）。"""
        结果一 = 检查系统工具("不存在工具", ["/usr/bin/肯定不存在的命令xyz"])
        self.assertFalse(结果一.成功)
        结果二 = 检查系统工具("textutil", [shutil.which("textutil") or "textutil"],
                             版本参数="-help")
        self.assertIsInstance(结果二, 探针结果)
        if not shutil.which("textutil"):
            self.skipTest("textutil 不可用")
        self.assertTrue(结果二.成功)

    def test_参数不合法(self):
        结果 = 检查系统工具("", ["/bin/echo"])
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        结果2 = 检查系统工具("x", [], 超时秒=-1)
        self.assertEqual(结果2.错误码, "参数不合法")


class Test提供者入口不可用映射(unittest.TestCase):
    """提供者 检查提供者 探针失败 → 外部提供者不可用（mock 探针失败路径）。"""

    def test_LibreOffice探针失败返回外部提供者不可用(self):
        from unittest import mock
        from 支持库.适配层.LibreOffice提供者.实现 import 文档转换 as 模块
        原缓存 = dict(模块._提供者缓存)
        模块._提供者缓存 = {"soffice": str(macOSsoffice路径)}
        try:
            with mock.patch(
                "运行核心.运行环境管理器.系统探针.检查系统工具",
                return_value=探针结果(False, 错误码="探针超时", 诊断="卡住已强杀"),
            ):
                结果 = 模块.检查提供者()
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "外部提供者不可用")
                self.assertIn("探针超时", 结果.错误说明)
        finally:
            模块._提供者缓存 = 原缓存

    def test_textutil探针失败返回外部提供者不可用(self):
        from unittest import mock
        from 支持库.适配层.textutil提供者.实现 import 文本转换 as 模块
        原缓存 = dict(模块._提供者缓存)
        模块._提供者缓存 = {"textutil": "/usr/bin/textutil"}
        try:
            with mock.patch(
                "运行核心.运行环境管理器.系统探针.检查系统工具",
                return_value=探针结果(False, 错误码="退出码非零", 退出码=1,
                                      诊断="textutil 退出码 1"),
            ):
                结果 = 模块.检查提供者()
                self.assertFalse(结果.成功)
                self.assertEqual(结果.错误码, "外部提供者不可用")
                self.assertIn("退出码非零", 结果.错误说明)
        finally:
            模块._提供者缓存 = 原缓存


if __name__ == "__main__":
    unittest.main()
