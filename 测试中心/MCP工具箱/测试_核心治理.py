"""核心治理工具真实测试：临时目录搭建 运行核心/公共契约 副本，全链路验证。

绝不修改 worktree 真实 运行核心/公共契约 文件；所有快照与篡改都在
TemporaryDirectory 临时根内进行，tearDown 自动清理，零残留。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import MCP工具箱.核心治理 as 核心治理模块
from MCP工具箱.核心治理 import (
    创建核心快照,
    兼容性检查,
    查询核心快照,
    回滚门禁,
)


class 核心治理测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        根 = Path(self._临时.name)
        self.项目根 = 根 / "项目"
        运行核心子目录 = self.项目根 / "运行核心" / "能力调用"
        公共契约子目录 = self.项目根 / "公共契约" / "能力契约"
        运行核心子目录.mkdir(parents=True)
        公共契约子目录.mkdir(parents=True)
        (self.项目根 / "运行核心" / "__init__.py").write_text("", encoding="utf-8")
        (self.项目根 / "公共契约" / "__init__.py").write_text("", encoding="utf-8")
        (运行核心子目录 / "能力调用.py").write_text(
            "def 调用():\n    返回 1\n", encoding="utf-8")
        (公共契约子目录 / "能力契约.py").write_text("契约 = {}\n", encoding="utf-8")
        self.快照根 = (self.项目根 / "工程缓存" / "核心快照").resolve()
        self.核心文件 = self.项目根 / "运行核心" / "能力调用" / "能力调用.py"

    def tearDown(self) -> None:
        self._临时.cleanup()

    def test_创建核心快照生成时间戳目录清单摘要与文件副本(self) -> None:
        结果 = 创建核心快照(self.项目根, 说明="测试快照1")
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["错误码"], "")
        快照路径 = Path(结果["快照路径"])
        self.assertTrue(快照路径.is_dir())
        self.assertTrue(快照路径.name.startswith("2026"))
        self.assertEqual(结果["文件数"], 4)
        self.assertTrue(结果["摘要"])
        # 清单与摘要文件
        self.assertTrue((快照路径 / "清单.json").is_file())
        self.assertTrue((快照路径 / "摘要.json").is_file())
        清单 = json.loads((快照路径 / "清单.json").read_text(encoding="utf-8"))
        self.assertEqual(清单["摘要"], 结果["摘要"])
        self.assertEqual(清单["文件数"], 4)
        self.assertEqual(清单["说明"], "测试快照1")
        self.assertEqual(清单["范围"], ["运行核心", "公共契约"])
        摘要文件 = json.loads((快照路径 / "摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要文件["摘要"], 结果["摘要"])
        # 不可变文件副本存在且与来源一致
        for 相对路径 in 清单["文件表"]:
            副本 = 快照路径 / 相对路径
            self.assertTrue(副本.is_file(), 相对路径)
            self.assertEqual(副本.read_bytes(), (self.项目根 / 相对路径).read_bytes())

    def test_查询核心快照列出时间摘要文件数(self) -> None:
        创建核心快照(self.项目根, 说明="快照1")
        创建核心快照(self.项目根, 说明="快照2")
        结果 = 查询核心快照(self.项目根)
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["错误码"], "")
        self.assertEqual(结果["数量"], 2)
        时间戳表 = [项["时间戳"] for 项 in 结果["快照列表"]]
        self.assertEqual(len(set(时间戳表)), 2)
        for 项 in 结果["快照列表"]:
            self.assertTrue(项["快照路径"].startswith(str(self.快照根)))
            self.assertEqual(项["文件数"], 4)
            self.assertTrue(项["摘要"])

    def test_兼容性检查篡改运行核心文件检出漂移(self) -> None:
        创建 = 创建核心快照(self.项目根, 说明="漂移基线")
        self.assertTrue(创建["成功"], 创建)
        # 在临时副本上篡改，绝不改 worktree 真实核心文件
        self.核心文件.write_text("def 调用():\n    返回 2  # 篡改\n", encoding="utf-8")
        结果 = 兼容性检查(Path(创建["快照路径"]).name, self.项目根)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "漂移")
        self.assertEqual(结果["问题列表"], ["漂移"])
        self.assertEqual(结果["漂移数"], 1)
        差异 = 结果["差异列表"][0]
        self.assertEqual(差异["类型"], "修改")
        self.assertEqual(差异["路径"], "运行核心/能力调用/能力调用.py")
        self.assertEqual(结果["超限列表"], [])

    def test_兼容性检查删除文件检出漂移(self) -> None:
        创建 = 创建核心快照(self.项目根, 说明="删除基线")
        目标 = self.项目根 / "公共契约" / "能力契约" / "能力契约.py"
        目标.unlink()
        结果 = 兼容性检查(Path(创建["快照路径"]).name, self.项目根)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "漂移")
        self.assertEqual(结果["差异列表"][0]["类型"], "删除")

    def test_兼容性检查新增正式文件资源预算审计(self) -> None:
        创建 = 创建核心快照(self.项目根, 说明="预算基线")
        短文件 = self.项目根 / "公共契约" / "能力契约" / "短契约.py"
        短文件.write_text("\n".join(f"行{i}" for i in range(10)), encoding="utf-8")
        结果 = 兼容性检查(Path(创建["快照路径"]).name, self.项目根)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "漂移")
        self.assertEqual(结果["超限列表"], [])  # 短文件未超限
        # 新增超限正式文件 → 错误码 超限，超限列表列出
        超长文件 = self.项目根 / "公共契约" / "能力契约" / "超长契约.py"
        超长文件.write_text("\n".join(f"行{i}" for i in range(170)), encoding="utf-8")
        结果2 = 兼容性检查(Path(创建["快照路径"]).name, self.项目根)
        self.assertFalse(结果2["成功"])
        self.assertEqual(结果2["错误码"], "超限")
        self.assertIn("超限", 结果2["问题列表"])
        self.assertEqual(len(结果2["超限列表"]), 1)
        超限项 = 结果2["超限列表"][0]
        self.assertEqual(超限项["路径"], "公共契约/能力契约/超长契约.py")
        self.assertEqual(超限项["行数"], 170)
        self.assertEqual(超限项["上限"], 160)
        self.assertTrue(any(项["类型"] == "新增" for 项 in 结果2["差异列表"]))

    def test_回滚门禁损坏快照拒绝(self) -> None:
        创建 = 创建核心快照(self.项目根, 说明="回滚基线")
        快照路径 = Path(创建["快照路径"])
        # 篡改快照内文件副本 → 快照损坏
        副本 = 快照路径 / "运行核心" / "能力调用" / "能力调用.py"
        副本.write_text("def 调用():\n    返回 999\n", encoding="utf-8")
        结果 = 回滚门禁(Path(创建["快照路径"]).name, self.项目根)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "快照损坏")
        self.assertFalse(结果["可回滚"])
        # 兼容性检查同样拒绝损坏快照
        结果2 = 兼容性检查(Path(创建["快照路径"]).name, self.项目根)
        self.assertEqual(结果2["错误码"], "快照损坏")
        self.assertFalse(结果2["可检查"])
        # 篡改清单摘要 → 聚合摘要不匹配，仍判损坏
        清单路径 = 快照路径 / "清单.json"
        清单 = json.loads(清单路径.read_text(encoding="utf-8"))
        清单["摘要"] = "篡改摘要"
        清单路径.write_text(json.dumps(清单, ensure_ascii=False), encoding="utf-8")
        结果3 = 回滚门禁(Path(创建["快照路径"]).name, self.项目根)
        self.assertEqual(结果3["错误码"], "快照损坏")

    def test_回滚门禁与兼容性检查快照不存在(self) -> None:
        不存在的路径 = "20260101-000000-000"
        结果 = 回滚门禁(不存在的路径, self.项目根)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "快照不存在")
        self.assertFalse(结果["可回滚"])
        结果2 = 兼容性检查(不存在的路径, self.项目根)
        self.assertEqual(结果2["错误码"], "快照不存在")
        self.assertFalse(结果2["可检查"])

    def test_绝对路径与穿越快照标识拒绝参数无效(self) -> None:
        创建 = 创建核心快照(self.项目根, 说明="路径穿越基线")
        self.assertTrue(创建["成功"], 创建)
        快照绝对路径 = str(创建["快照路径"])
        for 非法标识 in [快照绝对路径, "../工程缓存/核心快照", "20260101/../../秘密"]:
            结果 = 兼容性检查(非法标识, self.项目根)
            self.assertFalse(结果["成功"], f"{非法标识!r} 应被拒绝")
            self.assertEqual(结果["错误码"], "参数无效", f"{非法标识!r}")
            结果2 = 回滚门禁(非法标识, self.项目根)
            self.assertEqual(结果2["错误码"], "参数无效", f"{非法标识!r}")
            self.assertFalse(结果2["可回滚"])

    def test_执行回滚切换激活指针且不覆盖源码(self) -> None:
        创建 = 创建核心快照(self.项目根, 说明="回滚执行")
        原内容 = self.核心文件.read_text(encoding="utf-8")
        结果 = 回滚门禁(Path(创建["快照路径"]).name, self.项目根, 执行回滚=True)
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["错误码"], "")
        self.assertTrue(结果["已执行回滚"])
        self.assertEqual(结果["激活快照"], 创建["快照路径"])
        激活指针 = self.快照根 / "当前.json"
        self.assertTrue(激活指针.is_file())
        数据 = json.loads(激活指针.read_text(encoding="utf-8"))
        self.assertEqual(数据["激活快照"], 创建["快照路径"])
        self.assertEqual(数据["摘要"], 创建["摘要"])
        # 回滚不覆盖源码：运行核心文件内容保持不变
        self.assertEqual(self.核心文件.read_text(encoding="utf-8"), 原内容)
        self.assertIn("未覆盖源码", 结果["消息"])
        # 再次回滚门禁可读到当前激活指针
        结果2 = 回滚门禁(Path(创建["快照路径"]).name, self.项目根)
        self.assertTrue(结果2["成功"])
        self.assertEqual(结果2["当前激活"], 创建["快照路径"])

    def test_执行回滚激活指针复核失败拒绝(self) -> None:
        创建 = 创建核心快照(self.项目根, 说明="回滚失败场景")
        激活指针 = self.快照根 / "当前.json"
        激活指针.mkdir(parents=True)  # 用目录顶住激活指针位置，制造复核失败
        结果 = 回滚门禁(Path(创建["快照路径"]).name, self.项目根, 执行回滚=True)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "陈旧令牌")
        self.assertIn("切换失败", 结果["消息"])
        self.assertTrue(结果["可回滚"])  # 门禁本身校验通过

    def test_执行回滚CAS拒绝并发切换(self) -> None:
        """CAS：复核期间激活指针被其他方切换，回滚被拒绝且指针保持新值。"""
        创建 = 创建核心快照(self.项目根, 说明="CAS并发")
        激活指针 = self.快照根 / "当前.json"
        激活指针.parent.mkdir(parents=True, exist_ok=True)
        激活指针.write_text('{"激活快照": "其他方已切换"}\n', encoding="utf-8")
        # 直接调用底层 CAS：期望旧文本与当前不一致 → 拒绝
        错误 = 核心治理模块._写激活指针CAS(
            激活指针, Path(创建["快照路径"]), {"时间戳": "t", "摘要": "s", "文件数": 1},
            期望旧文本="旧内容",
        )
        self.assertIn("陈旧令牌", 错误)
        self.assertEqual(
            json.loads(激活指针.read_text(encoding="utf-8"))["激活快照"], "其他方已切换")

    def test_时间戳标识解析且快照零残留于真实工程缓存(self) -> None:
        创建 = 创建核心快照(self.项目根, 说明="标识解析")
        时间戳 = Path(创建["快照路径"]).name
        结果 = 兼容性检查(时间戳, self.项目根)
        self.assertTrue(结果["成功"], 结果)
        # 测试快照全部位于临时根，绝不写入真实工程缓存
        系统根 = Path(__file__).resolve().parents[2]
        真实快照根 = 系统根 / "工程缓存" / "核心快照"
        self.assertFalse(str(Path(创建["快照路径"])).startswith(str(真实快照根)))
        查询 = 查询核心快照(self.项目根)
        self.assertEqual(查询["数量"], 1)


if __name__ == "__main__":
    unittest.main()
