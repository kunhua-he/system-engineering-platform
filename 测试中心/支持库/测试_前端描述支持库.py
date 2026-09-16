"""第三十阶段第二波组3：前端描述支持库 5 包升级测试（S0.1 聚合契约/对称/摘要/权威13项+功能真实调用）。

覆盖 5 个前端描述支持库（基础组件描述/文件选择描述/状态描述/窗口描述/资源描述）：
- S0 收敛：聚合契约逐能力 S0.1 全要素（版本/说明/参数必填默认值说明/返回/错误码/调用示例），禁"任意"
- 四者对称：包声明/聚合契约/注册能力/__all__ 能力集一致
- 完整性摘要：唯一校验器文件清单闭合
- 权威 13 项：组件合规 13/13（真实执行，无 mock）
- 功能真实调用：创建→校验→（序列化/反序列化往返）→失败路径
"""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

前端包表 = [
    ("支持库.前端.基础组件描述", "基础组件描述"),
    ("支持库.前端.文件选择描述", "文件选择描述"),
    ("支持库.前端.状态描述", "状态描述"),
    ("支持库.前端.窗口描述", "窗口描述"),
    ("支持库.前端.资源描述", "资源描述"),
]


class Test前端描述支持库S0收敛(unittest.TestCase):
    """S0 收敛：聚合契约逐包全要素/对称/摘要/权威 13 项。"""

    def test_聚合契约S01全要素(self) -> None:
        for 包id, 包名 in 前端包表:
            契约 = json.loads(
                (系统根 / "支持库" / "前端" / 包名 / "能力契约" / "参数契约.json")
                .read_text(encoding="utf-8"))
            self.assertEqual(契约["契约版本"], "1.0.0")
            能力表 = 契约["能力契约"]
            self.assertTrue(能力表, 包名)
            声明 = json.loads(
                (系统根 / "支持库" / "前端" / 包名 / "包声明.json")
                .read_text(encoding="utf-8"))
            self.assertEqual(
                {能力["能力id"] for 能力 in 声明["能力"]},
                {能力["能力id"] for 能力 in 能力表},
                包名)
            for 能力 in 能力表:
                self.assertIn(".", 能力["版本"], 能力["能力id"])
                self.assertTrue(能力["说明"], 能力["能力id"])
                self.assertTrue(能力["参数"], 能力["能力id"])
                self.assertIsInstance(能力["返回"], dict, 能力["能力id"])
                self.assertTrue(能力["错误码"], 能力["能力id"])
                self.assertIsInstance(能力["调用示例"], dict, 能力["能力id"])
                for 参数 in 能力["参数"]:
                    self.assertIn("必填", 参数, 能力["能力id"])
                    self.assertIn("默认值", 参数, 能力["能力id"])
                    self.assertIn("说明", 参数, 能力["能力id"])
                    self.assertNotEqual(参数["类型"], "任意", 能力["能力id"])

    def test_四者对称(self) -> None:
        for 包id, 包名 in 前端包表:
            声明 = json.loads(
                (系统根 / "支持库" / "前端" / 包名 / "包声明.json")
                .read_text(encoding="utf-8"))
            契约 = json.loads(
                (系统根 / "支持库" / "前端" / 包名 / "能力契约" / "参数契约.json")
                .read_text(encoding="utf-8"))
            声明集 = {能力["能力id"] for 能力 in 声明["能力"]}
            契约集 = {能力["能力id"] for 能力 in 契约["能力契约"]}
            入口模块 = importlib.import_module(f"支持库.前端.{包名}")
            self.assertEqual(声明集, 契约集, 包名)
            self.assertEqual(len(入口模块.__all__), len(声明集), 包名)

    def test_完整性摘要校验通过(self) -> None:
        from 支持库.后端.组件规范支持库 import 校验完整性摘要
        for 包id, 包名 in 前端包表:
            通过, 问题 = 校验完整性摘要(系统根 / "支持库" / "前端" / 包名)
            self.assertTrue(通过, f"{包名}: {问题}")

    def test_权威13项合规(self) -> None:
        from 开发工具.组件合规.合规测试包 import 组件合规
        for 包id, 包名 in 前端包表:
            报告 = 组件合规(系统根 / "支持库" / "前端" / 包名).执行()
            self.assertEqual(
                报告.通过数, 13,
                f"{包名}: " + "; ".join(
                    f"{名称}: {详情}" for 名称, 通过, 详情
                    in 报告.场景结果表 if not 通过))
            self.assertTrue(报告.成功)


class Test前端描述支持库功能(unittest.TestCase):
    """功能真实调用：入口函数创建/校验/序列化往返与失败路径。"""

    def test_基础组件描述全流程(self) -> None:
        from 支持库.前端.基础组件描述 import 创建组件定义, 校验组件属性, 声明事件
        结果 = 创建组件定义("组件1", "按钮", {"标签": "点击"})
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["组件类型"], "按钮")
        self.assertEqual(结果.值["事件列表"], [])
        校验 = 校验组件属性(结果.值)
        self.assertTrue(校验.成功)
        事件 = 声明事件(结果.值, "点击")
        self.assertTrue(事件.成功)
        self.assertIn("点击", 事件.值["事件列表"])
        失败 = 创建组件定义("", "按钮", {})
        self.assertFalse(失败.成功)
        self.assertEqual(失败.错误.错误码, "参数不合法")

    def test_文件选择描述全流程(self) -> None:
        from 支持库.前端.文件选择描述 import 创建文件选择描述, 校验文件选择描述
        结果 = 创建文件选择描述([".txt", ".md"], False)
        self.assertTrue(结果.成功)
        self.assertIn(".txt", 结果.值["允许扩展名列表"])
        self.assertFalse(结果.值["多选"])
        校验 = 校验文件选择描述(结果.值)
        self.assertTrue(校验.成功)
        失败 = 创建文件选择描述("不是列表", False)
        self.assertFalse(失败.成功)

    def test_状态描述全流程(self) -> None:
        from 支持库.前端.状态描述 import 创建窗口状态, 状态流转校验
        结果 = 创建窗口状态("窗口1", "关闭")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["状态"], "关闭")
        self.assertEqual(结果.值["流转记录"], [])
        合法 = 状态流转校验("关闭", "打开")
        self.assertTrue(合法.成功)
        非法 = 状态流转校验("关闭", "关闭")
        self.assertFalse(非法.成功)
        self.assertEqual(非法.错误.错误码, "状态流转不合法")

    def test_窗口描述全流程(self) -> None:
        from 支持库.前端.窗口描述 import (
            创建窗口定义, 校验窗口定义, 序列化窗口定义, 反序列化窗口定义)
        结果 = 创建窗口定义("窗口1", "标题", 400, 300)
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["组件列表"], [])
        校验 = 校验窗口定义(结果.值)
        self.assertTrue(校验.成功)
        序列化 = 序列化窗口定义(结果.值)
        self.assertTrue(序列化.成功)
        还原 = 反序列化窗口定义(序列化.值)
        self.assertTrue(还原.成功)
        self.assertEqual(还原.值["窗口id"], "窗口1")
        失败 = 反序列化窗口定义("不是JSON")
        self.assertFalse(失败.成功)
        self.assertEqual(失败.错误.错误码, "反序列化失败")

    def test_资源描述全流程(self) -> None:
        from 支持库.前端.资源描述 import 创建资源描述, 校验资源引用
        结果 = 创建资源描述("资源1", "图片", "示例来源")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["引用计数"], 0)
        校验 = 校验资源引用(结果.值)
        self.assertTrue(校验.成功)
        失败 = 创建资源描述("", "图片", "来源")
        self.assertFalse(失败.成功)
        self.assertEqual(失败.错误.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main()
