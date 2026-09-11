"""进程管理支持库黑盒测试：沙箱执行命令失败路径必须返回失败结果而非抛异常。

背景：`沙箱执行命令` 的失败分支曾引用未定义名 `来源`，导致**全部失败路径抛 NameError**，
「无沙箱平台 fail-closed」这条明文承诺在 Linux 上直接失效。本测试以「调用不抛异常 +
返回失败结果 + 错误码正确」三条断言锁死该行为，防止回归。

测试只经进程管理包级入口，不导入 实现/。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.系统核心支持库.进程管理 import 执行命令, 沙箱执行命令

有无内核沙箱 = sys.platform == "darwin" and bool(shutil.which("sandbox-exec"))


class 测试沙箱执行命令失败路径(unittest.TestCase):
    """失败路径统一口径：不抛异常、成功=False、错误码与来源正确。"""

    def _断言失败(self, 调用结果, 期望错误码: str) -> None:
        self.assertIsNotNone(调用结果)
        self.assertFalse(调用结果.成功)
        self.assertEqual(调用结果.错误码, 期望错误码)
        self.assertEqual(调用结果.来源, "进程管理")
        self.assertTrue(调用结果.错误说明)

    def test_空命令返回参数不合法(self) -> None:
        self._断言失败(沙箱执行命令(""), "参数不合法")

    def test_空白命令返回参数不合法(self) -> None:
        self._断言失败(沙箱执行命令("   "), "参数不合法")

    def test_非文本命令返回参数不合法(self) -> None:
        self._断言失败(沙箱执行命令(12345), "参数不合法")
        self._断言失败(沙箱执行命令(["echo", "1"]), "参数不合法")

    def test_缺工作目录返回参数不合法(self) -> None:
        self._断言失败(沙箱执行命令("echo 1"), "参数不合法")

    def test_空工作目录返回参数不合法(self) -> None:
        self._断言失败(沙箱执行命令("echo 1", ""), "参数不合法")

    def test_工作目录不存在返回目录不存在(self) -> None:
        self._断言失败(沙箱执行命令("echo 1", "/不存在的工作目录/子目录"), "目录不存在")

    def test_工作目录是文件而非目录返回目录不存在(self) -> None:
        with tempfile.TemporaryDirectory(prefix="进程管理_") as 临时目录:
            文件 = Path(临时目录) / "不是目录.txt"
            文件.write_text("占位", encoding="utf-8")
            self._断言失败(沙箱执行命令("echo 1", str(文件)), "目录不存在")

    @unittest.skipIf(有无内核沙箱, "本机有 sandbox-exec，无法验 fail-closed")
    def test_无沙箱平台fail_closed(self) -> None:
        结果 = 沙箱执行命令("echo 1", str(Path(tempfile.gettempdir())))
        self._断言失败(结果, "沙箱不可用")


class 测试沙箱执行命令运行路径(unittest.TestCase):
    """有内核沙箱时：成功路径与超时路径返回真实结果。"""

    def setUp(self) -> None:
        if not 有无内核沙箱:
            self.skipTest("本机无 sandbox-exec，跳过真实沙箱运行")
        self._临时目录 = tempfile.TemporaryDirectory(prefix="沙箱运行_")
        self.工作目录 = self._临时目录.name

    def tearDown(self) -> None:
        临时目录 = getattr(self, "_临时目录", None)
        if 临时目录 is not None:
            临时目录.cleanup()

    def test_成功路径返回真实退出码与标准输出(self) -> None:
        结果 = 沙箱执行命令("echo 沙箱已跑通", self.工作目录)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["退出码"], 0)
        self.assertTrue(结果.值["成功执行"])
        self.assertIn("沙箱已跑通", 结果.值["标准输出"])
        self.assertEqual(结果.值["沙箱"], "macOS sandbox-exec")

    def test_工作目录内可写且可读回(self) -> None:
        写结果 = 沙箱执行命令("printf '越界测试' > 产物.txt", self.工作目录)
        self.assertTrue(写结果.成功, 写结果.错误说明)
        读结果 = 沙箱执行命令("cat 产物.txt", self.工作目录)
        self.assertTrue(读结果.成功, 读结果.错误说明)
        self.assertIn("越界测试", 读结果.值["标准输出"])

    def test_超时路径返回超时并回收进程组(self) -> None:
        结果 = 沙箱执行命令("sleep 30", self.工作目录, 超时秒=1)
        self._断言超时(结果)

    def _断言超时(self, 结果) -> None:
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")
        self.assertEqual(结果.来源, "进程管理")


class 测试执行命令回归(unittest.TestCase):
    """同文件 `执行命令` 的成功/失败口径不受本次修复影响。"""

    def test_空命令返回参数不合法(self) -> None:
        结果 = 执行命令("")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")
        self.assertEqual(结果.来源, "进程管理")

    def test_真实执行返回退出码与输出(self) -> None:
        结果 = 执行命令("echo 进程管理回归")
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.值["退出码"], 0)
        self.assertIn("进程管理回归", 结果.值["标准输出"])


if __name__ == "__main__":
    unittest.main()
