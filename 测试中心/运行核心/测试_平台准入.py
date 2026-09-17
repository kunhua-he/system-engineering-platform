"""平台准入测试：唯一入口必须拦住 macOS / arm64 以外的环境（含反向验证与文档口径）。

覆盖：

1. 本机真实环境通过准入（`校验支持范围` 不抛错）；
2. **真实子进程真跑入口**：把 `platform.system()/machine()` monkeypatch 成
   Windows / Linux / x86_64 → 入口必须中文报错、退出码 1，且**停在准入**
   （不进入装配、不绑端口）；
3. **反向验证（故意弄坏）**：把入口那段准入换成一行 `sys.exit(0)` 后，
   同一模拟环境**不再出现准入文案** —— 证明上面几条红确实由准入判据产生；
4. 入口的准入调用必须排在装配导入（`后端核心`）**之前**，并翻译成中文报错 + 退出码 1；
5. 文档口径与代码同源：README 支持矩阵必须写明只支持 macOS arm64 且会拦。

安全约束（实测教训）：模拟平台判定**绝不允许放行到真实装配** —— 平台判定与实际
解释器布局矛盾时会触发真实破坏动作（删本机受管 venv）。因此负向样本要么在准入处
就被拒（正向用例），要么把准入那一行本身换成 `sys.exit(0)`（反向用例），
两种写法都**不可能走到装配**。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
入口相对路径 = "运行核心/启动运行核心网关.py"
入口文件 = 系统根 / 入口相对路径
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.运行时.平台适配 import (  # noqa: E402
    平台不支持错误, 校验支持范围, 正式支持架构表, 正式支持平台,
)

#: 入口里那段准入（反向样本按此精确替换；改入口时必须同步改这里，否则反向验证自己会报错）
准入代码块 = (
    'try:\n'
    '    校验支持范围(用途="启动运行核心网关")\n'
    'except 平台不支持错误 as 错误:\n'
    '    print(f"启动被拒绝（环境准入不通过）：{错误}")\n'
    '    sys.exit(1)\n'
)
反向替换块 = 'print("准入已移除（反向样本）")\nsys.exit(0)\n'

#: 子进程里先 monkeypatch 平台判定，再 runpy 执行入口脚本。
#: 平台名判定的事实源是 `sys.platform`（`平台适配.当前平台()` 按它判定，且模块 docstring
#: 明确不调 `platform.system()`），架构走 `platform.machine()`；因此两者一起打桩，
#: `platform.system()` 也一并打桩（防空转断言）。
#: 正向用例：入口在准入处 sys.exit(1)，不会继续到装配与端口绑定。
#: 反向用例：临时副本把准入替换为 sys.exit(0)，同样不会进入装配。
子进程模板 = """
import platform, runpy, sys
sys.platform = {平台标志!r}
platform.system = lambda: {系统!r}
platform.machine = lambda: {架构!r}
sys.argv = [{入口!r}]
runpy.run_path({入口!r}, run_name="__main__")
"""

反向子进程模板 = """
import platform, pathlib, runpy, sys, tempfile
sys.platform = {平台标志!r}
platform.system = lambda: {系统!r}
platform.machine = lambda: {架构!r}
_原始 = pathlib.Path({入口!r}).read_text(encoding="utf-8")
_改后 = _原始.replace({旧块!r}, {新块!r})
assert _改后 != _原始, "反向验证未能改到入口准入块"
_临时目录 = pathlib.Path(tempfile.mkdtemp(prefix="准入反向_"))
_副本 = _临时目录 / {入口名!r}
_副本.write_text(_改后, encoding="utf-8")
sys.argv = [str(_副本)]
runpy.run_path(str(_副本), run_name="__main__")
"""

#: 模拟环境名 → `sys.platform` 标志（平台判定的唯一事实源）
平台标志表 = {"Windows": "win32", "Linux": "linux", "Darwin": "darwin"}


def _跑入口(系统: str, 架构: str, *, 反向: bool = False) -> subprocess.CompletedProcess:
    模板 = 反向子进程模板 if 反向 else 子进程模板
    填入 = {"系统": 系统, "架构": 架构, "入口": str(入口文件),
            "平台标志": 平台标志表[系统]}
    if 反向:
        填入.update({"旧块": 准入代码块, "新块": 反向替换块,
                      "入口名": Path(入口相对路径).name})
    代码 = 模板.format(**填入)
    环境 = os.environ.copy()
    环境.pop("PYTHONPATH", None)  # 与仓库验收口径一致：不让外部 PYTHONPATH 污染
    环境["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", 代码], cwd=str(系统根), env=环境,
        capture_output=True, text=True, timeout=180,
    )


class 测试平台准入(unittest.TestCase):
    """入口环境准入：非 macOS arm64 必须明确拒绝启动。"""

    def test_本机环境通过准入(self) -> None:
        """当前开发机（macOS arm64）准入无异常，且口径只声明这两项。"""
        self.assertEqual(正式支持平台, "macOS")
        self.assertIn("arm64", 正式支持架构表)
        校验支持范围(用途="自测")  # 不抛异常即通过

    def test_Windows被拒并给出中文支持范围(self) -> None:
        结果 = _跑入口("Windows", "AMD64")
        输出 = 结果.stdout + 结果.stderr
        self.assertEqual(结果.returncode, 1, 输出)
        self.assertIn("启动被拒绝", 输出)
        self.assertIn("只支持 macOS / arm64", 输出)
        self.assertIn("Windows", 输出)
        # 必须停在准入：不得继续装配（放行后再崩不算拦住）
        self.assertNotIn("后端核心装配成功", 输出)

    def test_Linux被拒_未顺便宣布支持(self) -> None:
        结果 = _跑入口("Linux", "x86_64")
        输出 = 结果.stdout + 结果.stderr
        self.assertEqual(结果.returncode, 1, 输出)
        self.assertIn("只支持 macOS / arm64", 输出)
        self.assertIn("Linux", 输出)

    def test_macOS非arm64被拒(self) -> None:
        结果 = _跑入口("Darwin", "x86_64")
        输出 = 结果.stdout + 结果.stderr
        self.assertEqual(结果.returncode, 1, 输出)
        self.assertIn("x86_64", 输出)

    def test_反向验证_去掉入口准入后同一环境不再被拦(self) -> None:
        """故意弄坏入口准入 → 同一模拟环境不再出现准入文案。

        判据故意用「不再出现准入文案」而不是「装配成功」：模拟平台下后续必然
        不可用，而且**不允许**放行到真实装配（会触发真实破坏动作）。
        """
        结果 = _跑入口("Windows", "AMD64", 反向=True)
        输出 = (结果.stdout or "") + (结果.stderr or "")
        self.assertIn("准入已移除（反向样本）", 输出, 输出)
        self.assertNotIn("启动被拒绝", 输出)
        self.assertNotIn("只支持 macOS / arm64", 输出)

    def test_准入调用排在任何装配导入之前(self) -> None:
        """准入必须早于装配导入（含 后端核心）与全部业务代码。"""
        源码 = 入口文件.read_text(encoding="utf-8")
        树 = ast.parse(源码)

        def _含校验支持范围(节点: ast.stmt) -> bool:
            for 子 in ast.walk(节点):
                if (isinstance(子, ast.Call) and isinstance(子.func, ast.Name)
                        and 子.func.id == "校验支持范围"):
                    return True
            return False

        def _导入位置(模块名: str) -> int:
            return next((下标 for 下标, 节点 in enumerate(树.body)
                         if isinstance(节点, ast.ImportFrom) and 节点.module == 模块名), -1)

        准入位置 = next(
            (下标 for 下标, 节点 in enumerate(树.body) if _含校验支持范围(节点)), -1)
        适配位置 = _导入位置("公共契约.运行时.平台适配")
        装配位置 = _导入位置("后端核心.后端核心")
        self.assertGreaterEqual(适配位置, 0, "入口应导入 公共契约.运行时.平台适配")
        self.assertGreaterEqual(准入位置, 0, "入口未调用 校验支持范围")
        self.assertGreaterEqual(装配位置, 0, "入口应导入 后端核心.后端核心")
        self.assertLess(适配位置, 准入位置, "准入必须在 平台适配 导入之后调用")
        self.assertLess(准入位置, 装配位置, "准入必须早于 后端核心 的导入")
        # 准入必须被翻译成中文报错 + 退出码 1
        self.assertIn("except 平台不支持错误", 源码)
        self.assertIn("sys.exit(1)", 源码)
        self.assertIn("启动被拒绝", 源码)
        # 反向样本必须与入口现文一致，否则反向验证会自己失效
        self.assertIn(准入代码块, 源码, "入口准入块变了：请同步更新测试里的 准入代码块")

    def test_README支持矩阵与代码同源(self) -> None:
        文本 = (系统根 / "README.md").read_text(encoding="utf-8")
        self.assertIn("只支持 macOS / arm64", 文本)
        self.assertIn("校验支持范围", 文本)
        # 不得出现「顺手宣布支持 Linux」的表述
        self.assertNotIn("只支持 macOS / arm64 与 Linux", 文本)


if __name__ == "__main__":
    unittest.main(verbosity=2)
