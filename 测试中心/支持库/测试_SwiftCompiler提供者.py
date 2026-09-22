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


class 工具缓存隔离基类(unittest.TestCase):
    """`_查找工具` 有**模块级缓存**：注入必须在清空缓存之后，且用例结束要再清一次。

    缓存一旦留下替身路径（或 None），后续用例会一直拿到它 —— 这是真串扰，不是风格问题。
    """

    def setUp(self):
        实现模块._工具缓存.clear()
        self.addCleanup(实现模块._工具缓存.clear)


class Test检查提供者(工具缓存隔离基类):
    """探针语义：工具缺失与探针超时都用**真实副作用 / 真实状态注入**造。

    旧写法替换的是生产模块自己的 `_查找工具` / `_跑`（`测试伪装门禁` 规则 1 判红：
    等于把「生产怎么找工具、怎么跑命令」整段跳过，测的是一个不存在的实现）。

    现写法只动**依赖边界与真实状态**：
    - 工具缺失 → 把 `_工具缓存` 预填 None（`_查找工具` 命中缓存即回缺失，走的正是
      生产自己的缓存路径），生产实现全程真跑；
    - 工具超时 → 把 `_工具缓存` 指向**真会挂起的替身脚本**，`_跑` 照常启真进程、
      走真超时强杀（比原写法多验了进程组回收）。

    **为什么不能 patch `shutil.which`**：`_查找工具` 写的是
    `next((c for c in 候选 if shutil.which(c)), None)` —— 返回的是**候选原文**
    而不是 `which` 的返回值，故 patch `which` 注入不进替身路径（实测：注入后
    `_查找工具` 仍回 `/usr/bin/swiftc`）。
    """

    def setUp(self):
        super().setUp()
        self.临时目录 = Path(tempfile.mkdtemp(prefix="swift探针_"))
        self.addCleanup(shutil.rmtree, self.临时目录, True)

    def test_工具缺失语义(self):
        """工具缺失 → 提供者不可用（不伪装成功、不混成参数问题）。

        经生产自己的缓存路径注入缺失：`_查找工具` 命中 `_工具缓存` 即回 None，
        与「机器上真没装」走的是同一条分支。
        """
        实现模块._工具缓存.update({"swiftc": None, "codesign": None})
        出 = 检查提供者()
        self.assertEqual(出.错误码, "提供者不可用")

    def test_真探针可用(self):
        出 = 检查提供者()
        self.assertTrue(出.成功, str(出.错误说明))
        self.assertTrue((出.值 or {}).get("提供者可用"))
        self.assertTrue((出.值 or {}).get("swiftc 路径"))
        self.assertTrue((出.值 or {}).get("codesign 路径"))

    def test_探针超时(self):
        """探针超时报 超时（真跑一个会挂起的替身工具，真超时、真强杀）。"""
        挂起工具 = self.临时目录 / "挂起工具"
        挂起工具.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
        挂起工具.chmod(0o700)
        实现模块._工具缓存.update({"swiftc": str(挂起工具), "codesign": str(挂起工具)})
        出 = 检查提供者(超时秒=0.5)
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


class Test签名(工具缓存隔离基类):
    def setUp(self):
        super().setUp()
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
        """签名制品遇到工具缺失 → 提供者不可用（经生产缓存路径注入真缺失）。"""
        实现模块._工具缓存.update({"swiftc": None, "codesign": None})
        出 = 签名制品(应用路径=str(self.应用))
        self.assertEqual(出.错误码, "提供者不可用")

    def test_路径不存在报参数不合法(self):
        出 = 校验签名(应用路径=str(self.工作 / "没有这个.app"))
        self.assertEqual(出.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main(verbosity=2)
