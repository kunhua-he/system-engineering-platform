"""加载器：包发现、依赖解析、提供者选择与生命周期测试。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from 公共契约.包声明.声明 import 从字典构建
from 运行核心.加载器.包发现.发现器 import 发现全部, 扫描目录
from 运行核心.加载器.依赖解析.解析器 import 解析依赖
from 运行核心.加载器.生命周期管理.管理器 import 装配系统
from 运行核心.加载器.提供者选择.选择器 import 选择提供者

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))


class Test包发现(unittest.TestCase):
    def test_发现支持库与模块(self):
        发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
        self.assertTrue(发现.成功, str(发现.问题列表))
        类型表 = {声明.类型 for 声明 in 发现.声明列表}
        self.assertIn("支持库", 类型表)
        self.assertIn("基础模块", 类型表)
        self.assertIn("功能模块", 类型表)
        self.assertGreaterEqual(len(发现.声明列表), 8)

    def test_能力id唯一(self):
        """唯一性由生产发现器判定：真数据必须零重复，且规模不为零。"""
        发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
        self.assertTrue(发现.成功, str(发现.问题列表))
        # 生产发现器的重复检测结论必须为空（重复只能在此暴露）
        self.assertEqual(发现.问题列表, [])
        包id列表 = [声明.包id for 声明 in 发现.声明列表]
        self.assertEqual(len(包id列表), len(set(包id列表)), "包id 必须全局唯一")
        能力id列表 = [
            能力.能力id
            for 声明 in 发现.声明列表
            if not getattr(声明, "已废弃", False)
            for 能力 in 声明.能力
        ]
        self.assertEqual(len(能力id列表), len(set(能力id列表)), "能力id 必须全局唯一")
        # 计数量级守卫：唯一性断言必须建立在真实规模上，禁止空扫描空过
        self.assertGreaterEqual(len(能力id列表), 100, "能力id 规模异常偏小，唯一性断言失效")
        self.assertGreaterEqual(len(包id列表), 50, "包规模异常偏小，唯一性断言失效")

    def test_重复包id被拒绝(self):
        """真调生产发现器：同 包id 的两份声明必须被拒绝并写入问题列表。

        对照根（仅 包id 不同）必须通过，证明断言不是「夹具形状导致的恒真/恒假」。
        """
        with tempfile.TemporaryDirectory(prefix=f"重复包夹具_{os.getpid()}_", dir="/tmp") as 临时:
            迷你根 = Path(临时)

            def 造根(名字: str, 包id列表: list[str]) -> tuple[Path, Path]:
                根 = 迷你根 / 名字
                支持库根, 模块根 = 根 / "支持库", 根 / "模块库"
                模块根.mkdir(parents=True)
                for 序号, 包id in enumerate(包id列表, start=1):
                    包目录 = 支持库根 / f"夹包{序号}"
                    包目录.mkdir(parents=True)
                    (包目录 / "包声明.json").write_text(json.dumps({
                        "包id": 包id, "名称": f"夹包{序号}", "类型": "支持库",
                        "版本": "1.0.0", "入口": "入口.py", "能力": [],
                    }, ensure_ascii=False), encoding="utf-8")
                return 支持库根, 模块根

            重复支持库, 重复模块 = 造根("重复根", ["夹具.重复包", "夹具.重复包"])
            唯一支持库, 唯一模块 = 造根("唯一根", ["夹具.包1", "夹具.包2"])
            重复发现 = 发现全部(重复支持库, 重复模块)
            唯一发现 = 发现全部(唯一支持库, 唯一模块)
        # 两份声明都必须真的被发现，否则「成功」可能只是漏扫造成的恒真
        self.assertEqual(
            sorted(声明.包id for 声明 in 重复发现.声明列表),
            ["夹具.重复包", "夹具.重复包"],
            "同 包id 的两份声明都必须被发现",
        )
        self.assertFalse(重复发现.成功, "同 包id 的两份声明必须被生产发现器拒绝")
        self.assertTrue(
            any("包 id 重复" in 问题 and "夹具.重复包" in 问题 for 问题 in 重复发现.问题列表),
            f"问题列表必须记录重复包id: {重复发现.问题列表}",
        )
        self.assertTrue(唯一发现.成功, f"仅 包id 不同即应通过，问题列表: {唯一发现.问题列表}")


class Test依赖解析(unittest.TestCase):
    def test_依赖缺失被报告(self):
        包1 = 从字典构建({"包id": "示例包1", "名称": "示例包1", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "不存在.能力"}]})
        结果 = 解析依赖([包1], {})
        self.assertFalse(结果.成功)
        self.assertTrue(结果.缺失能力)

    def test_版本约束冲突(self):
        包1 = 从字典构建({"包id": "示例包1", "名称": "示例包1", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "x.能力", "版本": ">=2.0.0"}]})
        结果 = 解析依赖([包1], {"x.能力": ("提供方", "1.0.0")})
        self.assertTrue(结果.版本冲突)

    def test_循环依赖被检测(self):
        包1 = 从字典构建({"包id": "示例包1", "名称": "示例包1", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "示例包2.能力"}]})
        包2 = 从字典构建({"包id": "示例包2", "名称": "示例包2", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "示例包1.能力"}]})
        结果 = 解析依赖([包1, 包2], {"示例包1.能力": ("示例包1", "1.0.0"), "示例包2.能力": ("示例包2", "1.0.0")})
        self.assertTrue(结果.循环)

    def test_拓扑顺序支持库在前(self):
        支持库 = 从字典构建({"包id": "库", "名称": "库", "类型": "支持库", "版本": "1.0.0", "能力": []})
        模块 = 从字典构建({"包id": "模", "名称": "模", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "库.能力"}]})
        结果 = 解析依赖([模块, 支持库], {"库.能力": ("库", "1.0.0")})
        self.assertTrue(结果.成功)
        self.assertEqual(结果.顺序列表[0], "库")


class Test提供者选择(unittest.TestCase):
    def test_唯一提供者成功(self):
        声明 = [从字典构建({"包id": "库", "名称": "库", "类型": "支持库", "版本": "1.0.0", "能力": [{"能力id": "库.能力"}]})]
        选择 = 选择提供者("库.能力", 声明)
        self.assertTrue(选择.成功)
        self.assertEqual(选择.提供包id, "库")

    def test_多提供者冲突(self):
        声明 = [
            从字典构建({"包id": "示例包1", "名称": "示例包1", "类型": "支持库", "版本": "1.0.0", "能力": [{"能力id": "撞.能力"}]}),
            从字典构建({"包id": "示例包2", "名称": "示例包2", "类型": "支持库", "版本": "1.0.0", "能力": [{"能力id": "撞.能力"}]}),
        ]
        选择 = 选择提供者("撞.能力", 声明)
        self.assertFalse(选择.成功)
        self.assertTrue(选择.冲突列表)

    def test_缺失提供者(self):
        选择 = 选择提供者("不存在.能力", [])
        self.assertTrue(选择.缺失)


class Test装配系统(unittest.TestCase):
    def test_完整装配成功(self):
        结果 = 装配系统(系统根 / "支持库", 系统根 / "模块库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertGreater(结果.已注册能力数, 20)

    def test_生命周期记录存在(self):
        结果 = 装配系统(系统根 / "支持库", 系统根 / "模块库")
        self.assertTrue(结果.生命周期记录)
        状态集合 = {记录.当前状态 for 记录 in 结果.生命周期记录}
        self.assertIn("已装配", 状态集合)
        self.assertIn("可运行", 状态集合)
        # 记录必须包含：包id/版本/操作名称/成功/错误码/错误说明
        记录 = 结果.生命周期记录[0]
        self.assertTrue(记录.包id)
        self.assertTrue(记录.版本)
        self.assertTrue(记录.操作名称)
        self.assertIsInstance(记录.成功, bool)
        self.assertIsInstance(记录.错误码, str)
        self.assertIsInstance(记录.错误说明, str)


if __name__ == "__main__":
    unittest.main()
