"""依赖防火墙口径测试：三张表（允许依赖 / 文件级豁免 / 预留授权）必须与头注释、现场同源。

覆盖 E-a（豁免表驱动、运行核心→后端核心 只放行启动脚本）、E-c（头注释镜像块与表同源）、
E-h（模块库→支持库 预留标注与实际使用一致）、以及新增的豁免表失效体检。
每个用例都带反向破坏：判据若写成恒真（例如体检函数永远返回空清单），反向断言必须失败。
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心 import 依赖防火墙
from 运行核心.依赖防火墙 import (
    允许依赖表, 文件级豁免表, 预留授权表, 层名称表,
    审计依赖, 检查依赖口径, 检查头注释与表同源, 检查预留授权, 检查豁免表,
    同包实现导入, 剥制品根前缀,
)


class 依赖防火墙口径测试(unittest.TestCase):
    """三张表 + 头注释 + 现场三方同源；判据空转与恒真都判红。"""

    def setUp(self) -> None:
        # 每个用例都改模块级表做反向破坏，先整体深拷贝，tearDown 原样还原。
        self.原允许 = copy.deepcopy(允许依赖表)
        self.原豁免 = copy.deepcopy(文件级豁免表)
        self.原预留 = copy.deepcopy(预留授权表)
        self.原文档 = 依赖防火墙.__doc__

    def tearDown(self) -> None:
        允许依赖表.clear(); 允许依赖表.update(self.原允许)
        文件级豁免表.clear(); 文件级豁免表.update(self.原豁免)
        预留授权表.clear(); 预留授权表.update(self.原预留)
        依赖防火墙.__doc__ = self.原文档

    # ---- 正向：现状必须干净 ----
    def test_头注释镜像块与允许依赖表同源(self) -> None:
        self.assertEqual(检查头注释与表同源(), [], "头注释与表必须同源（E-c）")

    def test_预留授权与实际使用一致(self) -> None:
        self.assertEqual(检查预留授权(), [], "预留标注必须与实际状态一致（E-h / E-b）")

    def test_文件级豁免都指向真实文件(self) -> None:
        self.assertEqual(检查豁免表(), [], "每条豁免都必须指向真实文件（E-a 表驱动的前提）")

    def test_聚合体检入口全绿(self) -> None:
        self.assertEqual(检查依赖口径(), [], "三张表体检必须整体干净")

    # ---- 反向：每条判据都必须真的会变红 ----
    def test_反向_头注释被改一处必须报差异(self) -> None:
        依赖防火墙.__doc__ = (self.原文档 or "").replace(
            '"运行核心": ["公共契约", "支持库"]', '"运行核心": ["公共契约"]')
        问题 = 检查头注释与表同源()
        self.assertTrue(问题, "镜像块与表不一致时必须报差异（改表不改正本块=E-c 复发）")
        self.assertTrue(any("运行核心" in 项 for 项 in 问题), 问题)

    def test_反向_豁免指向不存在文件必须报失效(self) -> None:
        文件级豁免表["运行核心"]["运行核心/不存在的外来脚本.py"] = frozenset({"后端核心"})
        问题 = 检查豁免表()
        self.assertTrue(问题, "豁免指向已删除文件时必须报失效（规范不得指向已删的东西）")
        self.assertTrue(any("文件不存在" in 项 for 项 in 问题), 问题)

    def test_反向_豁免目标层未登记必须报违规(self) -> None:
        文件级豁免表["运行核心"]["运行核心/启动运行核心网关.py"] = frozenset({"不存在的层"})
        问题 = 检查豁免表()
        self.assertTrue(any("目标层未登记" in 项 for 项 in 问题), 问题)

    def test_反向_预留项被撤表必须报预留失效(self) -> None:
        允许依赖表["模块库"].discard("支持库")
        问题 = 检查预留授权()
        self.assertTrue(any("预留失效" in 项 for 项 in 问题), 问题)

    def test_反向_预留项被真实使用必须报转正(self) -> None:
        # 造一个语义上已被使用的预留项：运行核心 确实大量 import 支持库。
        预留授权表[("运行核心", "支持库")] = "反向：本项其实已被真实使用，必须被判「应转正」"
        问题 = 检查预留授权()
        self.assertTrue(any("预留授权已被实际使用" in 项 for 项 in 问题), 问题)

    def test_反向_撤掉层授权必须真的出现越层违规(self) -> None:
        """判定真的读表，不是恒绿：撤掉 运行核心→支持库 授权后必须报出一批越层依赖。"""
        基线 = 审计依赖()
        self.assertEqual(len(基线.违规列表), 0, f"前提：现状必须 0 违规，实际 {len(基线.违规列表)}")
        允许依赖表["运行核心"].discard("支持库")
        破坏后 = 审计依赖()
        越层 = [项 for 项 in 破坏后.违规列表 if "越层依赖" in 项.规则]
        self.assertTrue(越层, "撤掉授权后必须报越层依赖（否则判定恒绿/不读表）")
        self.assertTrue(all(项.来源层 == "运行核心" for 项 in 越层), 越层[:3])

    def test_反向_单文件豁免只放行那一个文件(self) -> None:
        """运行核心→后端核心 只该放行启动脚本（E-a 的「不许整层开放」口径）。"""
        self.assertNotIn("后端核心", 允许依赖表["运行核心"],
                         "运行核心 整层不得依赖 后端核心（否则启动编排这条边被推广成普遍依赖）")
        豁免 = 文件级豁免表["运行核心"]
        self.assertEqual(list(豁免), ["运行核心/启动运行核心网关.py"], 豁免)
        self.assertIn("后端核心", 豁免["运行核心/启动运行核心网关.py"])

    def test_层名称表与允许依赖表键集一致(self) -> None:
        self.assertEqual(set(层名称表), set(允许依赖表),
                         "层名称表 与 允许依赖表 必须等宽（少一层就是一条不校验的缝）")

    # ---- 制品根前缀：制品态模块名带制品包名前缀，层判定必须先把前缀剥干净 ----
    def test_制品态模块名剥前缀后同包实现导入仍成立(self) -> None:
        """制品态「包级入口导自身 实现/」是合法模式，不得因前缀被判跨包（2026-09-17 实测）。"""
        原前缀 = 依赖防火墙.制品根前缀
        依赖防火墙.制品根前缀 = "平台客户端"
        try:
            self.assertEqual(剥制品根前缀("平台客户端.运行核心.甲.实现.提供者"),
                             "运行核心.甲.实现.提供者")
            self.assertEqual(剥制品根前缀("运行核心.甲.实现.提供者"),
                             "运行核心.甲.实现.提供者", "源码态无前缀，必须原样返回")
            self.assertEqual(剥制品根前缀("平台客户端.第三方名.模块"),
                             "平台客户端.第三方名.模块", "前缀后不是层名时不得误剥")
            self.assertTrue(同包实现导入("运行核心/甲/__init__.py",
                                        "平台客户端.运行核心.甲.实现.提供者"),
                            "同包导自身 实现/ 必须放行")
            self.assertFalse(同包实现导入("运行核心/甲/__init__.py",
                                         "平台客户端.运行核心.乙.实现.提供者"),
                             "真跨包导 实现/ 必须照旧报红")
        finally:
            依赖防火墙.制品根前缀 = 原前缀

    def test_反向_不剥制品前缀时必须重现误判(self) -> None:
        """反向破坏：前缀剥不干净（等同修前）时，同包实现导入必须真被判跨包。"""
        原前缀 = 依赖防火墙.制品根前缀
        依赖防火墙.制品根前缀 = ""
        try:
            self.assertFalse(同包实现导入("运行核心/甲/__init__.py",
                                         "平台客户端.运行核心.甲.实现.提供者"),
                             "不剥前缀却仍放行 ⇒ 本判据恒真，等于没判")
        finally:
            依赖防火墙.制品根前缀 = 原前缀


if __name__ == "__main__":
    unittest.main()
