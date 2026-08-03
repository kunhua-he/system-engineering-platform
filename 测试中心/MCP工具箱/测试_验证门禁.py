"""验证门禁测试：命令白名单、结果判定、反馈阻断。"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

门禁路径 = Path(__file__).resolve().parents[2] / "MCP工具箱" / "验证门禁.py"
sys.path.insert(0, str(门禁路径.parent))
规格 = importlib.util.spec_from_file_location("验证门禁", 门禁路径)
assert 规格 and 规格.loader
门禁模块 = importlib.util.module_from_spec(规格)
规格.loader.exec_module(门禁模块)

from 使用反馈 import 写入反馈  # noqa: E402

系统根 = Path(__file__).resolve().parents[2]


class 命令白名单测试(unittest.TestCase):
    """校验验证命令：白名单判定。"""

    def test_运行测试形态合法命令通过(self) -> None:
        结果 = 门禁模块.校验验证命令([
            "python3.14", "测试中心/运行测试.py",
            "--测试文件", "测试中心/MCP工具箱/测试_验证门禁.py", "--并行数", "0",
        ])
        self.assertTrue(结果["成功"], 结果["消息"])
        self.assertEqual(结果["错误码"], "")

    def test_运行测试形态多文件通过(self) -> None:
        结果 = 门禁模块.校验验证命令([
            "python3.14", "测试中心/运行测试.py",
            "--测试文件", "测试中心/MCP工具箱/测试_验证门禁.py",
            "测试中心/MCP工具箱/测试_项目服务.py", "--并行数", "2",
        ])
        self.assertTrue(结果["成功"], 结果["消息"])

    def test_pytest形态合法命令通过(self) -> None:
        结果 = 门禁模块.校验验证命令([
            "python3.14", "-m", "pytest",
            "测试中心/MCP工具箱/测试_验证门禁.py", "-q", "--timeout=60",
        ])
        self.assertTrue(结果["成功"], 结果["消息"])
        self.assertEqual(结果["错误码"], "")

    def test_工作根校验文件存在性(self) -> None:
        结果 = 门禁模块.校验验证命令([
            "python3.14", "-m", "pytest",
            "测试中心/不存在_测试.py", "-q", "--timeout=60",
        ], 工作根=系统根)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "命令拒绝")
        self.assertIn("不存在", 结果["消息"])

    def test_绝对路径拒绝(self) -> None:
        for 命令 in [
            ["python3.14", "测试中心/运行测试.py", "--测试文件",
             "/Users/某人/测试_越权.py", "--并行数", "0"],
            ["python3.14", "/Users/某人/运行测试.py", "--测试文件",
             "测试中心/x.py", "--并行数", "0"],
            ["python3.14", "-m", "pytest", "/Users/某人/x.py", "-q", "--timeout=60"],
        ]:
            结果 = 门禁模块.校验验证命令(命令)
            self.assertFalse(结果["成功"], 命令)
            self.assertEqual(结果["错误码"], "命令拒绝")
            self.assertIn("绝对路径", 结果["消息"])

    def test_路径逃逸拒绝(self) -> None:
        for 文件 in ["测试中心/../MCP工具箱/项目服务.py", "../测试_逃逸.py"]:
            结果 = 门禁模块.校验验证命令([
                "python3.14", "测试中心/运行测试.py",
                "--测试文件", 文件, "--并行数", "0",
            ])
            self.assertFalse(结果["成功"], 文件)
            self.assertEqual(结果["错误码"], "命令拒绝")

    def test_shell元字符拒绝(self) -> None:
        非法命令表 = [
            ["python3.14", "测试中心/运行测试.py", "--测试文件",
             "测试中心/x.py; rm -rf /", "--并行数", "0"],
            ["python3.14", "-m", "pytest", "测试中心/x.py", "-q",
             "--timeout=60 | cat"],
            ["python3.14", "-m", "pytest", "$(echo 危险)", "-q", "--timeout=60"],
            ["python3.14", "-m", "pytest", "测试中心/x.py", "-q", "--timeout=60`id`"],
        ]
        for 命令 in 非法命令表:
            结果 = 门禁模块.校验验证命令(命令)
            self.assertFalse(结果["成功"], 命令)
            self.assertEqual(结果["错误码"], "命令拒绝")
            self.assertIn("shell 元字符", 结果["消息"])

    def test_shell参数拒绝(self) -> None:
        结果 = 门禁模块.校验验证命令([
            "python3.14", "-m", "pytest", "测试中心/x.py", "-q", "shell=True",
        ])
        self.assertFalse(结果["成功"])
        self.assertIn("shell=", 结果["消息"])

    def test_超时超限拒绝(self) -> None:
        for 超时 in ["1801", "0", "abc", "60.5"]:
            结果 = 门禁模块.校验验证命令([
                "python3.14", "-m", "pytest", "测试中心/x.py", "-q",
                f"--timeout={超时}",
            ])
            self.assertFalse(结果["成功"], 超时)
            self.assertEqual(结果["错误码"], "命令拒绝")

    def test_未知可执行拒绝(self) -> None:
        for 命令 in [
            ["bash", "-c", "echo 危险"],
            ["python3", "测试中心/运行测试.py", "--测试文件",
             "测试中心/x.py", "--并行数", "0"],
            ["rm", "-rf", "测试中心"],
        ]:
            结果 = 门禁模块.校验验证命令(命令)
            self.assertFalse(结果["成功"], 命令)
            self.assertEqual(结果["错误码"], "命令拒绝")

    def test_任意字符串执行拒绝(self) -> None:
        for 命令 in [
            ["python3.14", "-c", "print(1)"],
            ["python3.14", "MCP工具箱/项目服务.py"],
            ["python3.14", "测试中心/运行测试.py"],
            ["python3.14", "测试中心/运行测试.py", "--测试文件",
             "测试中心/x.py"],
            ["python3.14", "测试中心/运行测试.py", "--测试文件",
             "测试中心/x.py", "--并行数", "0", "多余参数"],
        ]:
            结果 = 门禁模块.校验验证命令(命令)
            self.assertFalse(结果["成功"], 命令)
            self.assertEqual(结果["错误码"], "命令拒绝")


class 结果判定测试(unittest.TestCase):
    """判定验证结果：退出码、收集错误、零测试、未解释跳过。"""

    def test_退出码非零检出(self) -> None:
        for 退出码, 输出 in [(1, "1 failed"), (2, ""), (124, "超时")]:
            结果 = 门禁模块.判定验证结果(退出码, 输出)
            self.assertFalse(结果["成功"], 退出码)
            self.assertEqual(结果["错误码"], "验证失败")
            self.assertIn(str(退出码), 结果["消息"])

    def test_收集错误检出(self) -> None:
        结果 = 门禁模块.判定验证结果(0, "ERROR at collection of 测试中心/x.py")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "验证失败")
        self.assertIn("收集错误", 结果["消息"])

    def test_零测试文本检出(self) -> None:
        for 输出 in [
            "============================= no tests ran in 0.01s =============================",
            "零测试门禁失败：未发现任何测试用例（测试数量为零不允许返回成功）",
            "测试中心门禁失败：未发现任何测试用例（测试数量为零不允许返回成功）",
            "Ran 0 tests in 0.000s\n\nOK",
        ]:
            结果 = 门禁模块.判定验证结果(0, 输出)
            self.assertFalse(结果["成功"], 输出)
            self.assertEqual(结果["错误码"], "零测试")

    def test_未解释跳过检出(self) -> None:
        for 输出 in [
            "SKIPPED [1]\n1 skipped in 0.01s",
            "存在未执行场景，停止后续阶段",
            "test_跳过场景 ... skipped\n\nOK (skipped=1)",
        ]:
            结果 = 门禁模块.判定验证结果(0, 输出)
            self.assertFalse(结果["成功"], 输出)
            self.assertEqual(结果["错误码"], "未解释跳过")

    def test_解释跳过不阻断(self) -> None:
        for 输出 in [
            "SKIPPED [1] Skipped: 需要特定环境\n1 skipped in 0.01s",
            "跳过门禁失败：test_不得伪装成功 未执行，原因：反向验证",
            "test_a ... skipped '缺少外部程序'\n\nOK (skipped=1)",
        ]:
            结果 = 门禁模块.判定验证结果(0, 输出)
            self.assertTrue(结果["成功"], 输出)
            self.assertEqual(结果["错误码"], "")

    def test_正常输出通过(self) -> None:
        for 输出 in [
            "1 passed in 0.01s",
            "工作包并行门禁通过：1 个文件，并行数 1",
            "门禁通过：共 908 个测试全部成功（复用 12 个阶段缓存，总耗时 0.18 秒）",
            "---- 静态契约验证（447 个测试）----\nOK",
        ]:
            结果 = 门禁模块.判定验证结果(0, 输出)
            self.assertTrue(结果["成功"], 输出)
            self.assertEqual(结果["错误码"], "")


class 反馈门禁测试(unittest.TestCase):
    """反馈门禁：按开工id查询 MCP 使用反馈记录。"""

    def _反馈路径(self) -> Path:
        临时根 = Path(tempfile.mkdtemp(prefix="验证门禁反馈_"))
        return 临时根 / "反馈.jsonl"

    def test_无反馈记录阻断(self) -> None:
        反馈路径 = self._反馈路径()
        结果 = 门禁模块.反馈门禁("无此开工id", 反馈路径)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "未反馈阻断")
        self.assertIn("无此开工id", 结果["消息"])

    def test_已有反馈记录通过(self) -> None:
        反馈路径 = self._反馈路径()
        写入反馈(
            反馈路径, 开工id="fe79e7b4cc3e4e4f", 任务="验证门禁测试",
            角色="平台维护者", 总结="可用", 不满意="无", 多余="无",
            缺失="无", 升级建议="无",
        )
        结果 = 门禁模块.反馈门禁("fe79e7b4cc3e4e4f", 反馈路径)
        self.assertTrue(结果["成功"], 结果["消息"])
        self.assertEqual(结果["错误码"], "")

    def test_其他开工id反馈不影响本开工id(self) -> None:
        反馈路径 = self._反馈路径()
        写入反馈(
            反馈路径, 开工id="其他开工id", 任务="验证门禁测试",
            角色="平台维护者", 总结="可用", 不满意="无", 多余="无",
            缺失="无", 升级建议="无",
        )
        结果 = 门禁模块.反馈门禁("fe79e7b4cc3e4e4f", 反馈路径)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "未反馈阻断")


class 真实pytest最小调用测试(unittest.TestCase):
    """真实 pytest 最小调用：构造临时测试文件跑通通过路径。"""

    def test_临时测试文件跑通通过路径(self) -> None:
        with tempfile.TemporaryDirectory() as 临时目录:
            工作根 = Path(临时目录)
            测试文件 = 工作根 / "测试中心" / "test_临时通过.py"
            测试文件.parent.mkdir(parents=True)
            测试文件.write_text(
                "def test_通过():\n    assert 1 + 1 == 2\n", encoding="utf-8",
            )
            命令 = [
                "python3.14", "-m", "pytest",
                "测试中心/test_临时通过.py", "-q", "--timeout=60",
            ]
            校验结果 = 门禁模块.校验验证命令(命令, 工作根=工作根)
            self.assertTrue(校验结果["成功"], 校验结果["消息"])
            执行结果 = subprocess.run(
                命令, cwd=工作根, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(执行结果.returncode, 0, 执行结果.stderr)
            判定结果 = 门禁模块.判定验证结果(
                执行结果.returncode, 执行结果.stdout, 执行结果.stderr,
            )
            self.assertTrue(判定结果["成功"], 判定结果["消息"])
            self.assertEqual(判定结果["错误码"], "")


class 统一结果结构测试(unittest.TestCase):
    """统一结果结构与错误码集合。"""

    def test_错误码集合闭合(self) -> None:
        self.assertEqual(
            门禁模块.错误码集合,
            ("命令拒绝", "验证失败", "零测试", "未解释跳过", "未反馈阻断"),
        )
        self.assertEqual(len(set(门禁模块.错误码集合)), 5)

    def test_所有入口返回统一结构(self) -> None:
        结果表 = [
            门禁模块.校验验证命令(["bash", "-c", "x"]),
            门禁模块.判定验证结果(1, ""),
            门禁模块.判定验证结果(0, "no tests ran in 0.01s"),
            门禁模块.判定验证结果(0, "SKIPPED [1]"),
            门禁模块.反馈门禁("无此开工id", Path(tempfile.gettempdir()) / "无此反馈.jsonl"),
        ]
        for 结果 in 结果表:
            self.assertEqual(set(结果), {"成功", "错误码", "消息"}, 结果)


if __name__ == "__main__":
    unittest.main()
