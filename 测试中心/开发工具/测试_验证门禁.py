"""验证门禁（三个只读检查器）的回归测试。

覆盖五组判据：
1. **各检查器自证三拍**：干净样 → 绿；注入变异样本 → 必红；撤除 → 回绿
   （每条判据都有自己的变异样本，见各检查器文件内的 `变异样本表`）。
2. **空扫描面必判红**（哲学 1.4 空转即杀）：拿一个空目录当项目根跑，
   必须退出 1，且结论里出现「扫描面为 0」。
3. **基线不可用必判红**（fail-closed）：基线文件不存在 / 坏 JSON → 必须退出 1。
4. **真实仓库基线内为绿**：三个检查器对真实仓库跑，退出码 0（存量只报不拦）。
5. **统一入口唯一 0/1**：三个检查器全绿 → 入口 0；把某个检查器的脚本换成
   必判红的夹具根 → 入口 1。

跑法：`python3.14 -m unittest 测试中心.开发工具.测试_验证门禁`
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

门禁目录 = 系统根 / "开发工具" / "验证门禁"
检查器表 = ("同动作双路径检测.py", "调用腿唯一性检测.py", "技能库绕网关检测.py")
单项超时秒 = 300


def _跑(脚本: Path, 参数表: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(脚本), *(参数表 or [])],
        capture_output=True, text=True, timeout=单项超时秒, cwd=str(系统根),
    )


class 检查器自证测试(unittest.TestCase):
    """每条判据的反向验证都住在检查器自己的 `--自证` 里（三拍）。"""

    def test_三拍自证全通过(self) -> None:
        for 文件名 in 检查器表:
            脚本 = 门禁目录 / 文件名
            self.assertTrue(脚本.is_file(), f"检查器不存在：{脚本}")
            完成 = _跑(脚本, ["--自证"])
            输出 = (完成.stdout or "") + (完成.stderr or "")
            with self.subTest(检查器=文件名):
                self.assertEqual(完成.returncode, 0, f"{文件名} 自证未通过：\n{输出}")
                self.assertIn("自证结论：通过", 输出)
                # 三拍都必须真的跑过（不能只报一句「通过」）
                for 拍 in ("第一拍", "第二拍", "第三拍"):
                    self.assertIn(拍, 输出)


class 空转即杀测试(unittest.TestCase):
    """扫描面为 0 必须判红（否则「没扫到」会被当成「没问题」）。"""

    def test_空目录必判红(self) -> None:
        夹具 = Path(tempfile.mkdtemp(prefix="验证门禁_空目录_"))
        try:
            基线 = 夹具 / "基线.json"
            基线.write_text(
                json.dumps(
                    {"检查器": {名.replace(".py", ""): {} for 名 in 检查器表}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for 文件名 in 检查器表:
                完成 = _跑(门禁目录 / 文件名, ["--根", str(夹具), "--基线", str(基线)])
                输出 = (完成.stdout or "") + (完成.stderr or "")
                with self.subTest(检查器=文件名):
                    self.assertEqual(完成.returncode, 1, f"{文件名} 空目录未判红：\n{输出}")
                    self.assertIn("扫描面为 0", 输出)
        finally:
            shutil.rmtree(夹具, ignore_errors=True)


class 基线不可用测试(unittest.TestCase):
    """基线缺失 / 坏 JSON 必须判红（fail-closed，不得当作无违规）。"""

    def test_基线缺失必判红(self) -> None:
        夹具 = Path(tempfile.mkdtemp(prefix="验证门禁_无基线_"))
        try:
            for 文件名 in 检查器表:
                完成 = _跑(
                    门禁目录 / 文件名,
                    ["--根", str(系统根), "--基线", str(夹具 / "不存在.json")],
                )
                输出 = (完成.stdout or "") + (完成.stderr or "")
                with self.subTest(检查器=文件名):
                    self.assertEqual(完成.returncode, 1, f"{文件名} 基线缺失未判红：\n{输出}")
                    self.assertIn("存量基线不存在", 输出)
        finally:
            shutil.rmtree(夹具, ignore_errors=True)

    def test_基线坏JSON必判红(self) -> None:
        夹具 = Path(tempfile.mkdtemp(prefix="验证门禁_坏基线_"))
        try:
            坏 = 夹具 / "坏.json"
            坏.write_text("{ 这不是 JSON", encoding="utf-8")
            for 文件名 in 检查器表:
                完成 = _跑(门禁目录 / 文件名, ["--根", str(系统根), "--基线", str(坏)])
                输出 = (完成.stdout or "") + (完成.stderr or "")
                with self.subTest(检查器=文件名):
                    self.assertEqual(完成.returncode, 1, f"{文件名} 坏基线未判红：\n{输出}")
                    self.assertIn("存量基线不可解析", 输出)
        finally:
            shutil.rmtree(夹具, ignore_errors=True)


class 真实仓库测试(unittest.TestCase):
    """真实仓库：三个检查器在基线内应为绿（存量只报不拦，只减不增）。"""

    def test_真实仓库基线内为绿(self) -> None:
        for 文件名 in 检查器表:
            完成 = _跑(门禁目录 / 文件名)
            输出 = (完成.stdout or "") + (完成.stderr or "")
            with self.subTest(检查器=文件名):
                self.assertEqual(完成.returncode, 0, f"{文件名} 真实仓库判红：\n{输出}")
                # 扫描面必须非 0（空转即杀的反向断言：真的扫到了东西）
                self.assertIn("扫描面：", 输出)


class 统一入口测试(unittest.TestCase):
    """入口只做合成：全绿 → 0；任一非 0 → 1（含未核验）。"""

    def test_入口全绿返回0(self) -> None:
        入口 = 门禁目录 / "运行验证门禁.py"
        self.assertTrue(入口.is_file(), f"入口不存在：{入口}")
        完成 = _跑(入口)
        输出 = (完成.stdout or "") + (完成.stderr or "")
        self.assertEqual(完成.returncode, 0, f"入口未绿：\n{输出}")
        self.assertIn("结论：绿", 输出)
        for _文件名, 中文名 in (
            ("", "同动作两条路"),
            ("", "调用腿唯一性"),
            ("", "技能库绕网关"),
        ):
            self.assertIn(中文名, 输出)

    def test_入口遇未核验返回1(self) -> None:
        """入口脚本对一个不存在的检查器文件必须记未核验并退出 1（不能静默跳过）。"""
        import importlib.util

        规格 = importlib.util.spec_from_file_location(
            "运行验证门禁_夹具", 门禁目录 / "运行验证门禁.py"
        )
        self.assertIsNotNone(规格)
        模块 = importlib.util.module_from_spec(规格)
        规格.loader.exec_module(模块)
        原表 = 模块.检查器表
        try:
            模块.检查器表 = (("不存在的检查器.py", "夹具检查器"),)
            码 = 模块.main([])
        finally:
            模块.检查器表 = 原表
        self.assertEqual(码, 1, "入口对「脚本不存在」必须退 1（未核验不算通过）")


if __name__ == "__main__":
    unittest.main()
