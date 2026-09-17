"""提供者依赖锁强制校验测试：正向真实提供者/缺锁/空锁/范围版本/闭包/环境漂移/隔离环境/错误回滚。

风格与 测试_运行环境管理器.py / 测试_环境指纹.py 一致：
sys.path 注入系统根、unittest 用例、临时目录构造隔离场景；
反向场景必须真实失败（非恒真断言）。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.环境指纹 import 计算环境指纹
from 运行核心.运行环境管理器.环境管理器 import 计算环境摘要, 环境目录
from 运行核心.运行环境管理器.强制校验 import 校验提供者环境
from 公共契约.基础类型.逻辑类型 import 真, 假

系统根 = Path(__file__).resolve().parents[2]
真实提供者目录 = 系统根 / "支持库" / "适配层" / "reportlab提供者"


def 合法锁(提供者id: str = "临时提供者", *, 版本: str = "5.0.0") -> dict:
    """构造通过全部规则的合法锁（环境指纹取当前运行环境）。"""
    指纹 = 计算环境指纹(含外部应用=假).详细信息
    系统名 = "macOS" if 指纹["os"] == "Darwin" else 指纹["os"]
    return {
        "包": [{"名称": "reportlab", "版本": 版本, "模块名": "reportlab"}],
        "提供者id": 提供者id,
        "直接依赖": [{"名称": "reportlab", "版本": 版本}],
        "依赖闭包": [
            {"名称": "reportlab", "版本": 版本, "来源": "PyPI", "许可证": "BSD"},
        ],
        "环境": {"Python": 指纹["python"], "操作系统": 系统名, "CPU": 指纹["架构"]},
        "生成时间": "",
        "说明": "测试用合法锁",
    }


class Test提供者依赖锁强制校验(unittest.TestCase):
    """提供者依赖锁强制校验闭环测试（fail-closed）。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp())
        self.提供者目录 = self.临时 / "临时提供者"
        self.提供者目录.mkdir()

    def tearDown(self):
        shutil.rmtree(self.临时, ignore_errors=True)

    def _写锁(self, 锁: dict) -> None:
        (self.提供者目录 / "依赖锁.json").write_text(
            json.dumps(锁, ensure_ascii=False), encoding="utf-8"
        )

    def _伪隔离环境(self, 锁: dict, 提供者id: str = "临时提供者") -> Path:
        """构造通过导入校验的伪隔离环境：bin/python3 符号链接到系统解释器。"""
        摘要 = 计算环境摘要(锁, 提供者id)
        目录 = 环境目录(self.提供者目录, 摘要)
        解释器 = 目录 / "bin" / "python3"
        解释器.parent.mkdir(parents=True, exist_ok=True)
        解释器.symlink_to(sys.executable)
        return 目录

    def test_真实提供者锁校验通过(self):
        """正向：真实 reportlab提供者 依赖锁 全规则通过（隔离环境就绪时）。"""
        真实锁 = json.loads((真实提供者目录 / "依赖锁.json").read_text(encoding="utf-8"))
        摘要 = 计算环境摘要(真实锁, "reportlab提供者")
        目标 = 环境目录(真实提供者目录, 摘要)
        解释器 = 目标 / "bin" / "python3"
        已构建 = 解释器.is_file()
        if not 已构建:
            # 工程缓存未构建 → 构造伪隔离环境（本机已装 reportlab，导入校验真实执行）
            解释器.parent.mkdir(parents=True, exist_ok=True)
            解释器.symlink_to(sys.executable)

            def _清理伪环境():
                if 解释器.is_symlink():
                    解释器.unlink(missing_ok=True)
                if 目标.exists():
                    shutil.rmtree(目标, ignore_errors=True)

            self.addCleanup(_清理伪环境)
        结果 = 校验提供者环境(真实提供者目录)
        self.assertTrue(结果.成功, [问题.原因 for 问题 in 结果.问题列表])

    def test_缺锁拒绝(self):
        """缺 依赖锁.json → 拒绝运行（问题携带 提供者id 与 锁文件路径）。"""
        结果 = 校验提供者环境(self.提供者目录, "缺锁提供者")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.问题列表[0].提供者id, "缺锁提供者")
        self.assertTrue(any("缺少 依赖锁.json" in 问题.原因 for 问题 in 结果.问题列表))
        self.assertTrue(结果.问题列表[0].路径.endswith("依赖锁.json"))

    def test_空锁拒绝(self):
        """锁存在但 包 与 直接依赖 均为空 → 拒绝运行。"""
        self._写锁({"包": [], "直接依赖": [], "提供者id": "空锁提供者", "环境": {}})
        结果 = 校验提供者环境(self.提供者目录, "空锁提供者")
        self.assertFalse(结果.成功)
        self.assertTrue(any("空锁" in 问题.原因 for 问题 in 结果.问题列表))

    def test_范围版本拒绝(self):
        """版本为 范围/通配/占位 写法 → 拒绝运行（包 与 直接依赖 同时被拒）。"""
        for 版本 in (">=1.0", ">1.0", "*", "待定", "1.0.*", "==1.0", "latest"):
            with self.subTest(版本=版本):
                self._写锁(合法锁(版本=版本))
                结果 = 校验提供者环境(self.提供者目录)
                self.assertFalse(结果.成功)
                self.assertTrue(
                    any("不是精确版本" in 问题.原因 for 问题 in 结果.问题列表),
                    f"版本 {版本!r} 未被拒绝: {[问题.原因 for 问题 in 结果.问题列表]}",
                )

    def test_闭包缺失拒绝(self):
        """锁内无 依赖闭包 键 → 拒绝运行。"""
        锁 = 合法锁()
        锁.pop("依赖闭包")
        self._写锁(锁)
        结果 = 校验提供者环境(self.提供者目录)
        self.assertFalse(结果.成功)
        self.assertTrue(any("依赖闭包 缺失" in 问题.原因 for 问题 in 结果.问题列表))

    def test_闭包未覆盖拒绝(self):
        """直接依赖未全部纳入闭包（闭包为空/版本不符）→ 拒绝运行。"""
        for 闭包 in ([], [{"名称": "reportlab", "版本": "9.9.9", "来源": "PyPI"}]):
            with self.subTest(闭包=闭包):
                锁 = 合法锁()
                锁["依赖闭包"] = 闭包
                self._写锁(锁)
                结果 = 校验提供者环境(self.提供者目录)
                self.assertFalse(结果.成功)
                self.assertTrue(
                    any("未纳入 依赖闭包" in 问题.原因 for 问题 in 结果.问题列表),
                    f"闭包 {闭包!r} 未触发拒绝: {[问题.原因 for 问题 in 结果.问题列表]}",
                )

    def test_闭包内范围版本拒绝(self):
        """闭包条目版本为范围写法 → 拒绝运行。"""
        锁 = 合法锁()
        锁["依赖闭包"] = [{"名称": "reportlab", "版本": ">=5.0.0", "来源": "PyPI"}]
        self._写锁(锁)
        结果 = 校验提供者环境(self.提供者目录)
        self.assertFalse(结果.成功)
        self.assertTrue(
            any("闭包依赖 reportlab 版本" in 问题.原因 and "不是精确版本" in 问题.原因
                for 问题 in 结果.问题列表),
            f"闭包范围版本未被拒绝: {[问题.原因 for 问题 in 结果.问题列表]}",
        )

    def test_环境漂移拒绝(self):
        """锁内 环境（Python/操作系统/CPU）与当前不符 → 拒绝运行。"""
        指纹 = 计算环境指纹(含外部应用=假).详细信息
        变体表 = [
            {"Python": "2.7.18"},
            {"操作系统": "Windows"},
            {"CPU": "x86_64" if 指纹["架构"] != "x86_64" else "arm64"},
        ]
        for 变体 in 变体表:
            with self.subTest(变体=变体):
                锁 = 合法锁()
                锁["环境"].update(变体)
                self._写锁(锁)
                结果 = 校验提供者环境(self.提供者目录)
                self.assertFalse(结果.成功)
                self.assertTrue(
                    any("环境指纹不符" in 问题.原因 for 问题 in 结果.问题列表),
                    f"漂移 {变体!r} 未被拒绝: {[问题.原因 for 问题 in 结果.问题列表]}",
                )

    def test_隔离环境缺失拒绝(self):
        """锁合法但独立受管环境未构建 → 拒绝并提示重建。"""
        self._写锁(合法锁())
        结果 = 校验提供者环境(self.提供者目录)
        self.assertFalse(结果.成功)
        self.assertTrue(
            any("独立受管环境缺失" in 问题.原因 for 问题 in 结果.问题列表),
            f"未提示环境缺失: {[问题.原因 for 问题 in 结果.问题列表]}",
        )

    def test_损坏环境回滚清理(self):
        """隔离环境存在但无效 → 校验失败且半态环境被废弃清理（不留残留）。"""
        with self.subTest(场景="空壳目录"):
            self._写锁(合法锁())
            目标 = 环境目录(self.提供者目录, 计算环境摘要(合法锁(), "临时提供者"))
            目标.mkdir(parents=True, exist_ok=True)
            结果 = 校验提供者环境(self.提供者目录)
            self.assertFalse(结果.成功)
            self.assertFalse(目标.exists(), "空壳半态环境目录应被废弃清理")

        with self.subTest(场景="依赖导入失败"):
            锁 = 合法锁()
            锁["包"] = [{"名称": "虚构包", "版本": "1.0.0", "模块名": "不存在的模块xyz"}]
            锁["直接依赖"] = [{"名称": "虚构包", "版本": "1.0.0"}]
            锁["依赖闭包"] = [{"名称": "虚构包", "版本": "1.0.0", "来源": "PyPI"}]
            self._写锁(锁)
            self._伪隔离环境(锁)
            结果 = 校验提供者环境(self.提供者目录)
            self.assertFalse(结果.成功)
            目标 = 环境目录(self.提供者目录, 计算环境摘要(锁, "临时提供者"))
            self.assertFalse(目标.exists(), "导入失败的环境应被废弃清理")

    def test_锁文件损坏拒绝(self):
        """依赖锁.json 非合法 JSON → 拒绝运行。"""
        (self.提供者目录 / "依赖锁.json").write_text("不是JSON{{{", encoding="utf-8")
        结果 = 校验提供者环境(self.提供者目录)
        self.assertFalse(结果.成功)
        self.assertTrue(any("无法解析" in 问题.原因 for 问题 in 结果.问题列表))


if __name__ == "__main__":
    unittest.main()
