"""平台准入测试：唯一入口必须拦住「正式支持矩阵」以外的环境（含反向验证与文档口径）。

覆盖：

1. 本机真实环境通过准入（`校验支持范围` 不抛错）；
2. **准入矩阵三态**：macOS/arm64、Linux/x86_64、Windows/AMD64 均放行；
   表外组合（macOS/x86_64、Linux/aarch64、Windows/ARM64…）一律拒绝；
3. **真实子进程真跑入口**：模拟一个**表外**环境 → 入口必须中文报错、退出码 1，
   且**停在准入**（不进入装配、不绑端口）；
4. **反向验证（故意弄坏）**：把入口那段准入换成一行 `sys.exit(0)` 后，
   同一模拟环境**不再出现准入文案** —— 证明上面几条红确实由准入判据产生；
5. 入口的准入调用必须排在装配导入（`后端核心`）**之前**，并翻译成中文报错 + 退出码 1；
6. 文档口径与代码同源：README 支持矩阵必须写明入表组合与「不在表内即拒」。

安全约束（实测教训，**2026-09-19 放开 Linux/Windows 后更严**）：
模拟平台判定**绝不允许放行到真实装配** —— 平台判定与实际解释器布局矛盾时会触发
真实破坏动作（删本机受管 venv）。因此：

- 表外平台：真跑入口是**安全**的，它在准入处就 `sys.exit(1)`，走不到装配；
- 表内平台：**不真跑入口**，只在一个子进程里单独调 `校验支持范围()` 判定放行/拒绝，
  绝不 `runpy` 入口脚本（放行后它会继续装配并触真实删改）。

两条路径都**不可能走到装配**。
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
    平台不支持错误, 校验支持范围, 正式支持矩阵, AppleSilicon架构表,
)
from 公共契约.基础类型.逻辑类型 import 真, 假

#: 入口里那段准入（反向样本按此精确替换；改入口时必须同步改这里，否则反向验证自己会报错）
准入代码块 = (
    'try:\n'
    '    校验支持范围(用途="启动运行核心网关")\n'
    'except 平台不支持错误 as 错误:\n'
    '    print(f"启动被拒绝（环境准入不通过）：{错误}")\n'
    '    sys.exit(1)\n'
)
反向替换块 = 'print("准入已移除（反向样本）")\nsys.exit(0)\n'

#: **安全模板**：只调准入判定，绝不 runpy 入口（放行后会继续装配，触真实删改）。
#: 平台名判定的事实源是 `sys.platform`（`平台适配.当前平台()` 按它判定），
#: 架构走 `platform.machine()`；两者一起打桩。
准入判定模板 = """
import platform, sys
# 2026-09-23 修夹具（判据一字未改）：**必须先 import 平台适配，再打桩 sys.platform**。
# 原因：`平台适配.py:48` 有模块级 `import shutil`（2026-09-21 只读删除收口引入），
# 而 CPython 3.14 的 shutil 在 `sys.platform == 'win32'` 时执行 `import _winapi`；
# macOS 上无该扩展 ⇒ 先改 sys.platform='win32' 再 import 必然 ModuleNotFoundError
# （实测：Windows/AMD64 与 Windows/ARM64 两条用例全红，Linux/macOS 不受影响）。
# `校验支持范围` / `当前平台` / `当前架构` 都是**调用期**才读 `sys.platform` /
# `platform.machine()`（`平台适配.py` 的 `当前平台`/`当前架构`），故先 import 后打桩，
# 准入判定读到的仍是桩值 —— 断言与覆盖面均不变，只是让 Windows 模拟不再自伤。
from 公共契约.运行时.平台适配 import 校验支持范围, 平台不支持错误
sys.platform = {平台标志!r}
platform.system = lambda: {系统!r}
platform.machine = lambda: {架构!r}
try:
    校验支持范围(用途="准入自测")
    print("准入通过")
except 平台不支持错误 as 错误:
    print("启动被拒绝（环境准入不通过）：" + str(错误))
    sys.exit(1)
"""

#: **真跑入口**模板（仅用于**表外**平台：入口会在准入处退出，走不到装配）。
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
平台标志表 = {"Windows": "win32", "Linux": "linux", "macOS": "darwin"}

#: 表外样本（必须被拒）：放开 Linux/Windows 后仍要有负向覆盖，否则准入等于放开全部。
表外样本 = [
    ("macOS", "x86_64"),    # Intel Mac：MLX 结构性不可用，未取证
    ("Linux", "aarch64"),   # Linux/ARM：未取证
    ("Windows", "ARM64"),   # Windows/ARM：未取证
]


def _跑准入判定(系统: str, 架构: str) -> subprocess.CompletedProcess:
    """**只**在子进程里跑准入判定（不碰入口脚本 → 不可能进入装配）。"""
    代码 = 准入判定模板.format(系统=系统, 架构=架构, 平台标志=平台标志表[系统])
    环境 = os.environ.copy()
    环境.pop("PYTHONPATH", None)  # 与仓库验收口径一致：不让外部 PYTHONPATH 污染
    环境["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", 代码], cwd=str(系统根), env=环境,
        capture_output=True, text=True, timeout=180,
    )


#: 行为级判定模板：真调 `是否AppleSilicon()`，并**先把 macOS 行撑到含 Intel**，
#: 模拟「将来准入矩阵放开 macOS/x86_64」这一情形。
#:
#: 为什么要这么造：今天 `正式支持矩阵["macOS"]` 恰好等于 `AppleSilicon架构表`，
#: 所以「实现是否真的用 MLX 表」在**当前数据下测不出来**（实测：把实现改回看准入矩阵，
#: 普通断言照样绿）。把 macOS 行撑到含 x86_64 后，两种实现才产生可观测差异 ——
#: 看 MLX 表的实现仍答「假」（Intel Mac 不能走 MLX），看准入矩阵的实现会答「真」（错）。
#: 安全：只读判定 + 进程内改内存字典，绝不触装配/写盘。
是否AppleSilicon模板 = """
import platform, sys
sys.platform = {平台标志!r}
platform.system = lambda: {系统!r}
platform.machine = lambda: {架构!r}
from 公共契约.运行时 import 平台适配
平台适配.正式支持矩阵["macOS"] = ("arm64", "aarch64", "x86_64")  # 模拟将来放开 Intel Mac
print("真" if 平台适配.是否AppleSilicon() else "假")
"""


def _跑是否AppleSilicon(系统: str, 架构: str) -> subprocess.CompletedProcess:
    代码 = 是否AppleSilicon模板.format(系统=系统, 架构=架构, 平台标志=平台标志表[系统])
    环境 = os.environ.copy()
    环境.pop("PYTHONPATH", None)
    环境["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", 代码], cwd=str(系统根), env=环境,
        capture_output=True, text=True, timeout=180,
    )


def _跑入口(系统: str, 架构: str, *, 反向: bool = 假) -> subprocess.CompletedProcess:
    """真跑入口（**只对表外平台**用：它在准入处退出，走不到装配）。"""
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
    """入口环境准入：按 `正式支持矩阵` 放行，表外一律拒绝。"""

    def test_本机环境通过准入(self) -> None:
        """当前开发机（macOS arm64）准入无异常，且入表。"""
        self.assertIn("macOS", 正式支持矩阵)
        self.assertIn("arm64", 正式支持矩阵["macOS"])
        校验支持范围(用途="自测")  # 不抛异常即通过

    def test_入表平台全部放行(self) -> None:
        """矩阵里每个「平台/架构」组合都必须真能放行（否则入表是空话）。"""
        for 平台, 架构表 in 正式支持矩阵.items():
            for 架构 in 架构表:
                with self.subTest(平台=平台, 架构=架构):
                    结果 = _跑准入判定(平台, 架构)
                    输出 = 结果.stdout + 结果.stderr
                    self.assertEqual(结果.returncode, 0, 输出)
                    self.assertIn("准入通过", 输出)

    def test_表外组合一律被拒并给出中文支持范围(self) -> None:
        """表外组合必须拒绝启动，且报错里给出当前入表范围与中文原因。"""
        for 平台, 架构 in 表外样本:
            with self.subTest(平台=平台, 架构=架构):
                结果 = _跑准入判定(平台, 架构)
                输出 = 结果.stdout + 结果.stderr
                self.assertEqual(结果.returncode, 1, 输出)
                self.assertIn("启动被拒绝", 输出)
                self.assertIn(平台, 输出)
                self.assertIn(架构, 输出)
                # 报错必须点明入表范围，否则用户不知道往哪加证据
                self.assertIn("macOS/arm64", 输出)
                self.assertIn("Linux/x86_64", 输出)
                self.assertIn("Windows/AMD64", 输出)

    def test_表外环境真跑入口被拦在准入(self) -> None:
        """表外平台真跑入口：退出码 1、中文报错，且**停在准入**（不进入装配）。"""
        结果 = _跑入口("macOS", "x86_64")
        输出 = 结果.stdout + 结果.stderr
        self.assertEqual(结果.returncode, 1, 输出)
        self.assertIn("启动被拒绝", 输出)
        self.assertIn("x86_64", 输出)
        # 必须停在准入：不得继续装配（放行后再崩不算拦住）
        self.assertNotIn("后端核心装配成功", 输出)

    def test_反向验证_去掉入口准入后同一环境不再被拦(self) -> None:
        """故意弄坏入口准入 → 同一模拟环境不再出现准入文案。

        判据故意用「不再出现准入文案」而不是「装配成功」：模拟平台下后续必然
        不可用，而且**不允许**放行到真实装配（会触发真实破坏动作）。
        用**表外**平台做样本，保证入口在改坏前也停在准入、改坏后立刻退出，两次都不到装配。
        """
        结果 = _跑入口("macOS", "x86_64", 反向=真)
        输出 = (结果.stdout or "") + (结果.stderr or "")
        self.assertIn("准入已移除（反向样本）", 输出, 输出)
        self.assertNotIn("启动被拒绝", 输出)
        self.assertNotIn("当前环境不在支持范围内", 输出)

    def test_AppleSilicon判定与准入矩阵分开(self) -> None:
        """MLX 判定必须只看 Apple Silicon，不被准入矩阵放大（**行为级**判据）。

        放开 Linux/Windows 后，若 `是否AppleSilicon()` 改成看准入矩阵，Linux/Windows
        的机器会被误判成「可走 MLX」——MLX 运行时走 Metal，在那些平台结构性不可用
        （实测 Linux x86_64 装完闭包仍缺 `libmlx.so`）。

        判据故意用**真跑 `是否AppleSilicon()`**而不是只读常量：只读 `AppleSilicon架构表`
        测不出实现是否真的用它（实测：把实现改成看准入矩阵，只读常量的断言照样通过）。
        """
        # 静态面：MLX 表只含 Apple Silicon
        self.assertEqual(set(AppleSilicon架构表), {"arm64", "aarch64"})
        # 准入矩阵里的非 Apple Silicon 组合，绝不进 MLX 表
        for 平台 in ("Linux", "Windows"):
            for 架构 in 正式支持矩阵.get(平台, ()):
                with self.subTest(平台=平台, 架构=架构):
                    self.assertNotIn(架构, AppleSilicon架构表)
        # 行为面：模拟「将来准入放开 macOS/x86_64」后，真跑判定必须仍答「非 Apple Silicon」
        # （若实现改回看准入矩阵，x86_64 会被答成「真」→ 误选 MLX 后端，本断言即红）
        结果 = _跑是否AppleSilicon("macOS", "x86_64")
        self.assertEqual((结果.stdout or "").strip(), "假",
                         "实现没有用 AppleSilicon架构表：Intel Mac 会被误判成可走 MLX")
        # 对照：真 Apple Silicon 必须仍答「真」（确认上面不是恒假）
        结果2 = _跑是否AppleSilicon("macOS", "arm64")
        self.assertEqual((结果2.stdout or "").strip(), "真")

    def test_准入调用排在任何装配导入之前(self) -> None:
        """准入必须早于装配导入（含 后端核心）与全部业务代码。"""
        源码 = 入口文件.read_text(encoding="utf-8")
        树 = ast.parse(源码)

        def _含校验支持范围(节点: ast.stmt) -> bool:
            for 子 in ast.walk(节点):
                if (isinstance(子, ast.Call) and isinstance(子.func, ast.Name)
                        and 子.func.id == "校验支持范围"):
                    return 真
            return 假

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
        self.assertIn("校验支持范围", 文本)
        # 入表组合必须写进 README（否则代码放行而文档说只支持 macOS，两边打架）
        self.assertIn("macOS", 文本)
        self.assertIn("Linux", 文本)
        self.assertIn("Windows", 文本)
        # 不得再出现「只支持 macOS / arm64」的旧口径
        self.assertNotIn("只支持 macOS / arm64", 文本)


if __name__ == "__main__":
    unittest.main(verbosity=2)
