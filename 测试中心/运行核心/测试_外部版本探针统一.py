"""外部应用版本探针统一测试（第二十二阶段-工作包一）。

背景：环境指纹.探测外部应用版本 与 系统探针.检查系统工具 原为两套
独立逻辑；本测试锁定统一后行为：

- 统一版本来源：探测外部应用版本 经 检查系统工具 获取版本，
  不再独立 subprocess 逻辑（只替换外部命令层，生产探针本体原样执行）
- 探针结果字段完整：成功/版本/退出码/耗时秒/错误摘要/可重试
- 失败语义：工具缺失/探针超时/退出码非零 → "失败:<错误码>" 明确失败，
  绝不返回伪造版本（如"未知"或路径冒充）
- 版本漂移：证据记录指纹（锁版本）vs 当前探针版本不符 → 校验证据有效 失败
- 主进程不加载原生扩展：fitz/PyMuPDF 不进入 sys.modules
- 真实 LibreOffice/textutil 探针成功（缺工具跳过）

桩纪律：一律「只替换外部命令层」——把受控真实可执行桩目录前置到 PATH，
生产入口（探测外部应用版本/计算环境指纹/校验证据有效/检查系统工具）
原样执行，不 patch 任何生产符号。
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.环境指纹 import 计算环境指纹, 生成证据记录, 校验证据有效
from 支持库.适配层.系统探针 import 检查系统工具, 探针结果
from 公共契约.基础类型.逻辑类型 import 真, 假

macOSsoffice路径 = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")


def _查找soffice() -> str | None:
    """soffice 路径探测：PATH 或 /Applications 固定路径。"""
    return shutil.which("soffice") or (
        str(macOSsoffice路径) if macOSsoffice路径.is_file() else None
    )


def _macOS版本() -> str:
    return platform.mac_ver()[0] or platform.release()


def _成功探针(版本: str) -> 探针结果:
    return 探针结果(真, 退出码=0, 版本=版本, 耗时秒=0.05,
                    诊断="探针成功")


def _前置桩路径(桩目录: Path) -> mock._patch_dict:
    """把受控真实命令目录前置到 PATH 的上下文（只改外部命令层）。"""
    return mock.patch.dict(os.environ, {
        "PATH": f"{桩目录}{os.pathsep}{os.environ.get('PATH', '')}",
    })


def _造外部命令层(目录: Path, 输出表: dict[str, str],
                  退出码: int = 0, 标准错误: str = "") -> None:
    """在 目录 下写受控真实可执行桩（PATH 注入用）。

    桩只接受生产清单里给该工具的版本参数（`--version` / `-help`），
    参数不符即以退出码 2 失败——这样「版本参数透传」由真实行为验证。
    """
    目录.mkdir(parents=True, exist_ok=True)
    for 工具, 版本参数 in (("soffice", "--version"), ("textutil", "-help")):
        主体 = (f'echo "{标准错误}" 1>&2\nexit {退出码}\n' if 退出码
                else f'echo "{输出表[工具]}"\n')
        脚本 = 目录 / 工具
        脚本.write_text(
            "#!/bin/sh\n"
            f'if [ "$1" != "{版本参数}" ]; then echo "参数错误" 1>&2; exit 2; fi\n'
            + 主体,
            encoding="utf-8",
        )
        脚本.chmod(0o755)


def _造挂起命令层(目录: Path) -> None:
    """在 目录 下写只挂起的真实可执行桩：触发生产探针 5 秒超时强杀。"""
    目录.mkdir(parents=True, exist_ok=True)
    for 工具 in ("soffice", "textutil"):
        脚本 = 目录 / 工具
        脚本.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
        脚本.chmod(0o755)


def _探测(桩目录: Path) -> dict[str, str]:
    """把受控命令目录前置到 PATH 后真调生产入口 探测外部应用版本。"""
    from 运行核心.环境指纹 import 探测外部应用版本
    with _前置桩路径(桩目录):
        return 探测外部应用版本()


def _在桩环境计算指纹(桩目录: Path):
    """把受控命令目录前置到 PATH 后真调生产入口 计算环境指纹。"""
    with _前置桩路径(桩目录):
        return 计算环境指纹()


class Test统一版本来源(unittest.TestCase):
    """探测外部应用版本 经 系统探针 获取版本：只替换外部命令层。"""

    def test_探测外部应用版本经系统探针(self):
        """只替换外部命令层，生产探针本体（参数校验/退出码/版本提取）原样执行。"""
        with tempfile.TemporaryDirectory(prefix=f"外部命令_{os.getpid()}_") as 临时:
            成功目录 = Path(临时) / "成功"
            失败目录 = Path(临时) / "失败"
            _造外部命令层(成功目录, {
                "soffice": "LibreOffice 26.2.2.2 (X86_64)",
                "textutil": "textutil 桩输出 9.9.9",
            })
            _造外部命令层(失败目录, {}, 退出码=3, 标准错误="boom")
            成功结果 = _探测(成功目录)
            失败结果 = _探测(失败目录)
        # 版本字符串由受控真实命令输出经生产探针解析得到（桩只在参数正确时成功）
        self.assertEqual(成功结果["LibreOffice"], "26.2.2.2")
        self.assertEqual(成功结果["textutil"], _macOS版本())
        self.assertNotIn("9.9.9", 成功结果["textutil"],
                         "textutil 版本必须取 macOS 系统版本，不得采信探针输出")
        # 生产探针逻辑未被改写：同一入口退出码非零必须收敛为明确失败，绝不伪造版本
        self.assertEqual(失败结果["LibreOffice"], "失败:退出码非零")
        self.assertEqual(失败结果["textutil"], "失败:退出码非零")

    def test_环境指纹详情含统一版本(self):
        """环境指纹的外部应用版本同样由真实探针产出（外部命令层受控）。"""
        with tempfile.TemporaryDirectory(prefix=f"外部命令_{os.getpid()}_") as 临时:
            桩目录 = Path(临时) / "成功"
            _造外部命令层(桩目录, {
                "soffice": "LibreOffice 26.2.2.2 (X86_64)",
                "textutil": "textutil 桩输出 9.9.9",
            })
            指纹 = _在桩环境计算指纹(桩目录)
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
        结果 = 探针结果(假, 错误码="退出码非零", 退出码=3,
                        标准错误摘要="错误明细XYZ", 耗时秒=0.1,
                        诊断="soffice 退出码 3")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误摘要, "soffice 退出码 3")
        self.assertIn("错误明细XYZ", 结果.标准错误摘要)

    def test_超时标记可重试(self):
        结果 = 探针结果(假, 错误码="探针超时", 诊断="卡住已强杀",
                        可重试=真)
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
        """空 PATH：真实 which 找不到任何候选命令 → 工具缺失。"""
        from 运行核心.环境指纹.环境指纹 import 探测外部应用版本
        with tempfile.TemporaryDirectory(prefix=f"空路径_{os.getpid()}_") as 空目录:
            with mock.patch.dict(os.environ, {"PATH": str(空目录)}):
                结果 = 探测外部应用版本()
        self.assertEqual(结果["LibreOffice"], "失败:工具缺失")
        self.assertEqual(结果["textutil"], "失败:工具缺失")
        # 失败标记不是伪造版本
        for 值 in 结果.values():
            self.assertNotEqual(值, "未知")
            self.assertFalse(值.startswith("/"))  # 不以路径冒充版本

    def test_探针超时明确失败(self):
        """真实挂起命令 → 生产探针 5 秒超时强杀 → 失败:探针超时。"""
        with tempfile.TemporaryDirectory(prefix=f"挂起_{os.getpid()}_") as 临时:
            挂起目录 = Path(临时) / "挂起"
            _造挂起命令层(挂起目录)
            结果 = _探测(挂起目录)
        self.assertEqual(结果["LibreOffice"], "失败:探针超时")
        self.assertEqual(结果["textutil"], "失败:探针超时")

    def test_退出码非零明确失败(self):
        """真实命令退出码 3 → 失败:退出码非零，绝不伪造版本。"""
        with tempfile.TemporaryDirectory(prefix=f"退出码_{os.getpid()}_") as 临时:
            失败目录 = Path(临时) / "失败"
            _造外部命令层(失败目录, {}, 退出码=3, 标准错误="boom")
            结果 = _探测(失败目录)
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
        锁定目录 = 临时 / "锁定"
        漂移目录 = 临时 / "漂移"
        _造外部命令层(锁定目录, {
            "soffice": "LibreOffice 26.2.2.2 (X86_64)",
            "textutil": "textutil 桩输出 9.9.9",
        })
        _造外部命令层(漂移目录, {
            "soffice": "LibreOffice 26.2.3.0 (X86_64)",
            "textutil": "textutil 桩输出 9.9.9",
        })
        with _前置桩路径(锁定目录):
            生成证据记录(证据文件, {"测试": "锁定"})
        记录 = json.loads(证据文件.read_text(encoding="utf-8"))
        self.assertEqual(记录["指纹详情"]["外部应用"]["LibreOffice"],
                         "26.2.2.2")
        # 探针版本漂移（真实命令输出不同）→ 指纹变化 → 证据失效
        with _前置桩路径(漂移目录):
            校验 = 校验证据有效(证据文件)
        self.assertFalse(校验.成功)
        self.assertTrue(any("环境指纹漂移" in 问题
                            for 问题 in 校验.问题列表))

    def test_探针失败后证据失效不伪造(self):
        """探针失败（版本变失败标记）→ 指纹变化 → 证据失效。"""
        临时 = Path(tempfile.mkdtemp())
        证据文件 = 临时 / "证据.json"
        成功目录 = 临时 / "成功"
        失败目录 = 临时 / "失败"
        _造外部命令层(成功目录, {
            "soffice": "LibreOffice 26.2.2.2 (X86_64)",
            "textutil": "textutil 桩输出 9.9.9",
        })
        _造外部命令层(失败目录, {}, 退出码=3, 标准错误="boom")
        with _前置桩路径(成功目录):
            生成证据记录(证据文件)
        with _前置桩路径(失败目录):
            校验 = 校验证据有效(证据文件)
        self.assertFalse(校验.成功)
        self.assertTrue(any("环境指纹漂移" in 问题
                            for 问题 in 校验.问题列表))


class Test主进程不加载原生扩展(unittest.TestCase):
    """fitz/PyMuPDF 等原生扩展禁止主进程加载（版本走发行包元数据）。"""

    def _子进程计算指纹(self, 含外部应用: bool) -> dict:
        """在全新解释器验证原生扩展未进入主进程，避免套件顺序污染。"""
        脚本 = (
            "import json, sys; "
            "from 运行核心.环境指纹 import 计算环境指纹; "
            f"结果=计算环境指纹(含外部应用={含外部应用!r}); "
            "print(json.dumps({'成功':结果.成功,'详细信息':结果.详细信息,"
            "'加载fitz':'fitz' in sys.modules,'加载PyMuPDF':'PyMuPDF' in sys.modules},"
            "ensure_ascii=False))"
        )
        环境 = {键: 值 for 键, 值 in __import__('os').environ.items() if 键 != "PYTHONPATH"}
        环境["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        运行 = subprocess.run(
            [sys.executable, "-c", 脚本], cwd=str(Path(__file__).resolve().parents[2]),
            env=环境, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(运行.returncode, 0, 运行.stderr[-1000:])
        return json.loads(运行.stdout)

    def test_计算指纹不加载fitz(self):
        数据 = self._子进程计算指纹(真)
        self.assertTrue(数据["成功"])
        self.assertFalse(数据["加载fitz"])
        self.assertFalse(数据["加载PyMuPDF"])

    def test_第三方版本经元数据非import(self):
        数据 = self._子进程计算指纹(假)
        第三方 = 数据["详细信息"]["第三方"]
        self.assertIn("PyMuPDF", 第三方)
        self.assertTrue(第三方["PyMuPDF"])
        self.assertFalse(数据["加载fitz"])
        self.assertFalse(数据["加载PyMuPDF"])


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
