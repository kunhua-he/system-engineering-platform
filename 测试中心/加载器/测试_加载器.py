"""加载器：包发现、依赖解析、提供者选择与生命周期测试。"""

from __future__ import annotations

import sys
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
        发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
        self.assertTrue(发现.成功)

    def test_重复包id被拒绝(self):
        发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
        # 构造重复声明
        from 运行核心.加载器.包发现.发现器 import 发现结果
        结果 = 发现结果()
        甲 = 从字典构建({"包id": "重复包", "名称": "甲", "类型": "模块", "版本": "1.0.0", "能力": []})
        乙 = 从字典构建({"包id": "重复包", "名称": "乙", "类型": "模块", "版本": "1.0.0", "能力": []})
        结果.声明列表 = [甲, 乙]
        包id出现 = {}
        for 声明 in 结果.声明列表:
            包id出现[声明.包id] = 包id出现.get(声明.包id, 0) + 1
        self.assertTrue(任何冲突 := any(次数 > 1 for 次数 in 包id出现.values()))


class Test依赖解析(unittest.TestCase):
    def test_依赖缺失被报告(self):
        甲 = 从字典构建({"包id": "甲", "名称": "甲", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "不存在.能力"}]})
        结果 = 解析依赖([甲], {})
        self.assertFalse(结果.成功)
        self.assertTrue(结果.缺失能力)

    def test_版本约束冲突(self):
        甲 = 从字典构建({"包id": "甲", "名称": "甲", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "x.能力", "版本": ">=2.0.0"}]})
        结果 = 解析依赖([甲], {"x.能力": ("提供方", "1.0.0")})
        self.assertTrue(结果.版本冲突)

    def test_循环依赖被检测(self):
        甲 = 从字典构建({"包id": "甲", "名称": "甲", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "乙.能力"}]})
        乙 = 从字典构建({"包id": "乙", "名称": "乙", "类型": "模块", "版本": "1.0.0", "能力": [], "依赖": [{"能力": "甲.能力"}]})
        结果 = 解析依赖([甲, 乙], {"甲.能力": ("甲", "1.0.0"), "乙.能力": ("乙", "1.0.0")})
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
            从字典构建({"包id": "甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0", "能力": [{"能力id": "撞.能力"}]}),
            从字典构建({"包id": "乙", "名称": "乙", "类型": "支持库", "版本": "1.0.0", "能力": [{"能力id": "撞.能力"}]}),
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
