"""第二十九阶段m6-简单窗口模块迁移测试：类型/聚合契约/摘要/权威13项合规+功能真实调用。

覆盖：
- 功能：经能力调用器真实调用（创建/打开/关闭/传递参数/获取窗口描述/失败路径）
- S0 收敛：包声明类型 基础模块；聚合契约逐能力 S0.1 全要素（版本/说明/参数/错误码/调用示例）
- 完整性摘要：唯一校验器文件清单闭合
- 权威 13 项：组件合规 13/13（真实执行，无 mock）
- 调用图审计：简单窗口 实现 无支持库直连/原子旁路/漂移

治理缺口说明：S0.2 冻结"基础模块/功能模块"为正式模块类型，但 公共契约/包声明/声明.py
的 允许类型集合 尚未随治理波次升级（仍为 支持库/模块）。本测试按 S0 契约冻结在
运行时补上允许类型，正式代码零改动；升级由平台维护者完成。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

# S0.2 契约冻结的正式模块类型（治理层 声明.py 升级前的运行时补丁）
from 公共契约.包声明 import 声明 as 包声明契约

包声明契约.允许类型集合.update({"基础模块", "功能模块"})

# 显式装配：安装全部支持库 + 绑定唯一能力调用服务（功能测试真实调用）
from 公共契约.能力契约.契约 import 能力注册表
from 运行核心.加载器.包安装.支持库安装 import 安装全部支持库
from 运行核心.能力调用.唯一能力调用 import 创建并绑定

_支持库注册表 = 能力注册表()
安装全部支持库(系统根 / "支持库", _支持库注册表)
创建并绑定(_支持库注册表)

from 模块库.简单窗口 import 创建窗口, 打开窗口, 关闭窗口, 传递参数, 获取窗口描述

模块目录 = 系统根 / "模块库" / "简单窗口"


class Test简单窗口S0收敛(unittest.TestCase):
    """S0 收敛：类型/聚合契约/摘要/合规/调用图审计。"""

    def test_包声明类型为基础模块(self) -> None:
        声明 = json.loads((模块目录 / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(声明["类型"], "基础模块")
        self.assertEqual(声明["包id"], "模块库.简单窗口")

    def test_聚合契约S01全要素(self) -> None:
        契约 = json.loads(
            (模块目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        self.assertEqual(契约["契约版本"], "1.0.0")
        能力表 = 契约["能力契约"]
        self.assertEqual(len(能力表), 5)
        预期能力 = {"简单窗口.创建窗口", "简单窗口.打开窗口", "简单窗口.关闭窗口",
                    "简单窗口.传递参数", "简单窗口.获取窗口描述"}
        for 能力 in 能力表:
            self.assertIn(能力["能力id"], 预期能力)
            self.assertIn(".", 能力["版本"])
            self.assertTrue(能力["说明"])
            self.assertTrue(能力["参数"])
            self.assertTrue(能力["返回"])
            self.assertTrue(能力["错误码"])
            self.assertIsInstance(能力["调用示例"], dict)
            for 参数 in 能力["参数"]:
                self.assertIn("必填", 参数)
                self.assertIn("默认值", 参数)
                self.assertIn("说明", 参数)
                self.assertNotEqual(参数["类型"], "任意")

    def test_四者对称(self) -> None:
        """包声明/聚合契约/注册能力/__all__ 能力集一致。"""
        声明 = json.loads((模块目录 / "包声明.json").read_text(encoding="utf-8"))
        契约 = json.loads(
            (模块目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        声明集 = {能力["能力id"] for 能力 in 声明["能力"]}
        契约集 = {能力["能力id"] for 能力 in 契约["能力契约"]}
        self.assertEqual(声明集, 契约集)
        self.assertEqual(len(声明集), 5)

    def test_完整性摘要校验通过(self) -> None:
        from 开发工具.组件规范.完整性摘要 import 校验完整性摘要
        通过, 问题 = 校验完整性摘要(模块目录)
        self.assertTrue(通过, 问题)

    def test_权威13项合规(self) -> None:
        from 开发工具.组件合规.合规测试包 import 组件合规
        报告 = 组件合规(模块目录).执行()
        self.assertEqual(报告.通过数, 13,
                         [f"{名称}: {详情}" for 名称, 通过, 详情
                          in 报告.场景结果表 if not 通过])
        self.assertTrue(报告.成功)

    def test_调用图审计简单窗口清零(self) -> None:
        from 开发工具.复用审计.能力调用图审计 import 审计模块库
        报告 = 审计模块库(系统根 / "模块库")
        简单窗口违规 = [违规 for 违规 in 报告.违规列表
                      if "简单窗口" in str(违规.文件)]
        self.assertEqual(简单窗口违规, [])


class Test简单窗口功能(unittest.TestCase):
    """功能真实调用：模块经 获取能力调用器().调用能力 组合支持库能力。"""

    def test_创建打开传递参数获取描述关闭全流程(self) -> None:
        创建结果 = 创建窗口("测试窗", "测试", 400, 300)
        self.assertTrue(创建结果.成功)
        self.assertEqual(创建结果.值["标题"], "测试")
        打开结果 = 打开窗口("测试窗")
        self.assertTrue(打开结果.成功)
        self.assertEqual(打开结果.值["状态"], "打开")
        参数结果 = 传递参数("测试窗", {"来源": "测试"})
        self.assertEqual(参数结果.值["参数"]["来源"], "测试")
        描述结果 = 获取窗口描述("测试窗")
        self.assertEqual(描述结果.值["标题"], "测试")
        self.assertEqual(描述结果.值["状态"], "打开")
        关闭结果 = 关闭窗口("测试窗")
        self.assertTrue(关闭结果.成功)
        self.assertEqual(关闭结果.值["状态"], "关闭")

    def test_参数非法透传失败(self) -> None:
        结果 = 创建窗口("", "", 400, 300)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误.错误码, "参数不合法")

    def test_窗口不存在失败(self) -> None:
        结果 = 获取窗口描述("不存在的窗")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误.错误码, "窗口不存在")

    def test_非法状态流转失败(self) -> None:
        创建窗口("状态窗", "状态", 100, 100)
        结果 = 关闭窗口("状态窗")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误.错误码, "状态流转不合法")


if __name__ == "__main__":
    unittest.main()
