"""SwiftCompiler提供者 定向测试：探针 / 真编译 / 签名与篡改 / 错误码与超时。

单测只做**定向**（本包受影响的编译与契约），不跑全量 —— HTML 经网关黑盒才是唯一全量验收。
形态照同层先例 `测试中心/支持库/测试_Tesseract提供者.py`：从工程根导入包级入口。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.Swift编译器提供者 import (  # noqa: E402
    检查提供者, 校验签名, 签名制品, 编译源代码,
)
from 支持库.适配层.Swift编译器提供者.实现 import Swift工具 as 实现模块  # noqa: E402

夹具 = Path(__file__).resolve().parents[2] / "支持库/适配层/Swift编译器提供者/验证夹具/你好.swift"


def _有swiftc() -> bool:
    return shutil.which("swiftc") is not None or Path("/usr/bin/swiftc").exists()


class Test检查提供者(unittest.TestCase):
    def test_工具缺失语义(self):
        """工具缺失 → 提供者不可用（不伪装成功、不混成参数问题）。"""
        with mock.patch.object(实现模块, "_查找工具", return_value=None):
            出 = 检查提供者()
        self.assertEqual(出.错误码, "提供者不可用")

    def test_真探针可用(self):
        出 = 检查提供者()
        self.assertTrue(出.成功, str(出.错误说明))
        self.assertTrue((出.值 or {}).get("提供者可用"))
        self.assertTrue((出.值 or {}).get("swiftc 路径"))
        self.assertTrue((出.值 or {}).get("codesign 路径"))

    def test_探针超时(self):
        """探针超时报 超时（把 _跑 卡住，不依赖环境变量假功能）。"""
        def 假跑(命令, *, 超时秒=30.0):
            raise TimeoutError("模拟探针超时")
        with mock.patch.object(实现模块, "_跑", side_effect=假跑):
            出 = 检查提供者(超时秒=0.2)
        self.assertEqual(出.错误码, "超时")


class Test编译源代码(unittest.TestCase):
    def setUp(self):
        self.工作 = Path(tempfile.mkdtemp(prefix="swift单测_"))

    def test_参数不合法_清单为空(self):
        出 = 编译源代码(源文件清单=[], 输出路径=str(self.工作 / "x"))
        self.assertEqual(出.错误码, "参数不合法")

    def test_参数不合法_源文件不存在(self):
        出 = 编译源代码(源文件清单=["~/不存在/没有.swift"], 输出路径=str(self.工作 / "y"))
        self.assertEqual(出.错误码, "参数不合法")

    def test_参数不合法_输出路径非绝对(self):
        出 = 编译源代码(源文件清单=[str(夹具)], 输出路径="相对路径/不许")
        self.assertEqual(出.错误码, "参数不合法")

    def test_真编译出可跑二进制(self):
        if not _有swiftc():
            self.skipTest("本机无 swiftc")
        出 = 编译源代码(源文件清单=[str(夹具)], 输出路径=str(self.工作 / "你好"), 超时秒=180.0)
        self.assertTrue(出.成功, str(出.错误说明))
        可执行 = (出.值 or {}).get("可执行文件")
        self.assertTrue(Path(可执行).is_file())
        跑 = subprocess.run([可执行], capture_output=True, text=True, timeout=30)
        self.assertEqual(跑.returncode, 0)
        self.assertIn("真编译成功", 跑.stdout)

    def test_编译失败不吞错(self):
        if not _有swiftc():
            self.skipTest("本机无 swiftc")
        坏 = self.工作 / "坏.swift"
        坏.write_text('let x: Int = "不是整数"\n', encoding="utf-8")
        出 = 编译源代码(源文件清单=[str(坏)], 输出路径=str(self.工作 / "坏"), 超时秒=180.0)
        self.assertEqual(出.错误码, "编译失败")
        self.assertIn("坏.swift", str(出.错误说明))


class Test签名(unittest.TestCase):
    def setUp(self):
        self.工作 = Path(tempfile.mkdtemp(prefix="swift签名_"))
        if not _有swiftc():
            self.skipTest("本机无 swiftc")
        out = 编译源代码(源文件清单=[str(夹具)], 输出路径=str(self.工作 / "可执行"), 超时秒=180.0)
        if not out.成功:
            self.skipTest(f"编译失败，跳过签名：{out.错误说明}")
        self.应用 = self.工作 / "演示.app"
        (self.应用 / "Contents" / "MacOS").mkdir(parents=True)
        shutil.copy2(self.工作 / "可执行", self.应用 / "Contents" / "MacOS" / "演示")
        (self.应用 / "Contents" / "Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
            '<key>CFBundleExecutable</key><string>演示</string>'
            '<key>CFBundleIdentifier</key><string>com.demo.swift</string>'
            '<key>CFBundlePackageType</key><string>APPL</string></dict></plist>',
            encoding="utf-8")

    def test_adhoc签名并校验通过(self):
        出 = 签名制品(应用路径=str(self.应用), 超时秒=120.0)
        self.assertTrue(出.成功, str(出.错误说明))
        self.assertEqual((出.值 or {}).get("签名档位"), "adhoc")
        self.assertTrue((出.值 or {}).get("校验通过"))

    def test_篡改后校验必须失败(self):
        self.assertTrue(签名制品(应用路径=str(self.应用)).成功)
        with open(self.应用 / "Contents" / "MacOS" / "演示", "ab") as f:
            f.write(b"bad")
        出 = 校验签名(应用路径=str(self.应用))
        self.assertEqual(出.错误码, "校验失败")

    def test_签名档位只做adhoc(self):
        """不许偷偷扩出证书/公证档位（无证书环境那是死腿）。"""
        出 = 签名制品(应用路径=str(self.应用), 超时秒=120.0)
        self.assertEqual((出.值 or {}).get("签名档位"), "adhoc")

    def test_工具缺失语义(self):
        with mock.patch.object(实现模块, "_查找工具", return_value=None):
            出 = 签名制品(应用路径=str(self.应用))
        self.assertEqual(出.错误码, "提供者不可用")

    def test_路径不存在报参数不合法(self):
        出 = 校验签名(应用路径=str(self.工作 / "没有这个.app"))
        self.assertEqual(出.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main(verbosity=2)
