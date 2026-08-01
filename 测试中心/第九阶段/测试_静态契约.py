"""第九阶段：契约编译器与漂移检测测试（静态契约阶段）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.契约编译.契约编译器 import (
    编译契约, 生成Python入口, 生成前端调用入口, 生成网关参数校验,
    生成说明书, 生成契约测试, 生成能力搜索数据, 生成Agent查询数据,
    校验契约结构, 读取契约,
)
from 开发工具.契约编译.漂移检测 import (
    检测声明无实现, 检测实现无声明, 检测参数漂移, 检测错误码漂移,
    检测说明书一致, 检测契约升级, 检测生成文件被改, 全面漂移检测, 生成标记,
)


def 示例契约() -> dict:
    return {
        "能力id": "示例.分割", "名称": "分割", "版本": "1.0.0",
        "说明": "按分隔符分割文本", "包id": "示例.包", "核心": "后端",
        "参数": [{"名称": "文本", "类型": "文本", "必填": True, "说明": "待分割文本"}],
        "返回": "普通返回", "错误码": ["参数不合法", "内部错误"],
    }


class Test契约编译(unittest.TestCase):
    """契约编译器：7 类产物生成。"""

    def setUp(self):
        self.契约 = 示例契约()
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第九阶段编译_"))

    def test_校验契约结构合法(self):
        self.assertEqual(校验契约结构(self.契约), [])

    def test_校验契约结构拒绝缺字段(self):
        坏契约 = {"能力id": "缺字段"}  # 无 版本/参数/返回/错误码
        问题 = 校验契约结构(坏契约)
        self.assertGreaterEqual(len(问题), 4)

    def test_生成Python入口(self):
        产物 = 生成Python入口(self.契约)
        self.assertIn("示例.分割", 产物)
        self.assertIn("文本", 产物)
        self.assertIn(生成标记, 产物)

    def test_生成前端调用入口(self):
        产物 = 生成前端调用入口(self.契约)
        self.assertIn("/网关/请求", 产物)
        self.assertIn("示例.分割", 产物)

    def test_生成网关参数校验(self):
        产物 = 生成网关参数校验(self.契约)
        self.assertIn("文本", 产物)
        self.assertIn("参数不合法", 产物)

    def test_生成说明书(self):
        产物 = 生成说明书(self.契约)
        self.assertIn("示例.分割", 产物)
        self.assertIn("文本", 产物)
        self.assertIn("参数不合法", 产物)

    def test_生成契约测试(self):
        产物 = 生成契约测试(self.契约)
        self.assertIn("unittest", 产物)
        self.assertIn("示例分割", 产物)

    def test_生成能力搜索数据(self):
        数据 = 生成能力搜索数据(self.契约)
        self.assertEqual(数据["能力id"], "示例.分割")
        self.assertIn("文本", 数据["参数"])

    def test_生成Agent查询数据(self):
        数据 = 生成Agent查询数据(self.契约)
        self.assertEqual(数据["提供方"], "示例.包")
        self.assertFalse(数据["是否异步"])
        self.assertFalse(数据["是否流式"])

    def test_编译契约全产物落盘(self):
        契约文件 = self.临时目录 / "示例契约.json"
        契约文件.write_text(json.dumps(self.契约, ensure_ascii=False), encoding="utf-8")
        结果 = 编译契约(契约文件, self.临时目录 / "产物")
        self.assertTrue(结果.成功, 结果.问题列表)
        产物类型表 = {产物.产物类型 for 产物 in 结果.产物列表}
        self.assertIn("Python入口", 产物类型表)
        self.assertIn("前端调用入口", 产物类型表)
        self.assertIn("网关参数校验", 产物类型表)
        self.assertIn("说明书", 产物类型表)
        self.assertIn("契约测试", 产物类型表)
        self.assertIn("能力搜索数据", 产物类型表)
        self.assertIn("Agent查询数据", 产物类型表)
        self.assertEqual(len(结果.产物列表), 7)


class Test漂移检测(unittest.TestCase):
    """漂移检测：8 类漂移全部拒绝。"""

    def setUp(self):
        self.契约 = 示例契约()
        self.临时目录 = Path(tempfile.mkdtemp(prefix="第九阶段漂移_"))
        (self.临时目录 / "实现").mkdir()

    def test_声明能力但无实现(self):
        问题 = 检测声明无实现(self.契约, self.临时目录 / "实现")
        self.assertIsNotNone(问题)
        self.assertIn("声明能力但无实现", 问题)

    def test_有实现但无声明(self):
        (self.临时目录 / "实现" / "实现.py").write_text(
            "def 未声明函数():\n    return 1\n", encoding="utf-8")
        问题 = 检测实现无声明(self.临时目录 / "实现", [self.契约])
        self.assertTrue(any("未声明函数" in 问题 for 问题 in 问题))

    def test_参数顺序漂移(self):
        入口 = self.临时目录 / "入口.py"
        入口.write_text("def 分割(分隔符, 文本):\n    pass\n", encoding="utf-8")
        问题 = 检测参数漂移(self.契约, 入口)
        self.assertIsNotNone(问题)
        self.assertIn("参数顺序漂移", 问题)

    def test_错误码漂移(self):
        实现 = self.临时目录 / "实现" / "分割.py"
        实现.write_text('def 分割(文本):\n    return {"错误码": "超时"}\n', encoding="utf-8")
        问题 = 检测错误码漂移(self.契约, 实现)
        self.assertTrue(any("超时" in 问题 for 问题 in 问题))

    def test_说明书与入口不一致(self):
        说明书 = self.临时目录 / "说明书.md"
        说明书.write_text("# 说明书\n\n缺参数缺错误码\n", encoding="utf-8")
        问题 = 检测说明书一致(self.契约, 说明书)
        self.assertIsNotNone(问题)

    def test_契约破坏未升主版本(self):
        新契约 = dict(self.契约)
        新契约["参数"] = [{"名称": "强制新参数", "类型": "文本", "必填": True}]
        新契约["版本"] = "1.1.0"  # 主版本未升
        问题 = 检测契约升级(self.契约, 新契约)
        self.assertIsNotNone(问题)
        self.assertIn("未升级主版本", 问题)

    def test_契约破坏且升主版本通过(self):
        新契约 = dict(self.契约)
        新契约["参数"] = [{"名称": "强制新参数", "类型": "文本", "必填": True}]
        新契约["版本"] = "2.0.0"  # 主版本已升
        问题 = 检测契约升级(self.契约, 新契约)
        self.assertIsNone(问题)

    def test_生成文件被手工修改(self):
        产物目录 = self.临时目录 / "产物"
        产物目录.mkdir()
        (产物目录 / "手动文件.py").write_text(
            "def 手工函数():\n    pass\n", encoding="utf-8")  # 无生成标记
        问题 = 检测生成文件被改(产物目录)
        self.assertTrue(any("手动文件.py" in 问题 for 问题 in 问题))

    def test_全面漂移检测汇总(self):
        (self.临时目录 / "实现" / "分割.py").write_text(
            'def 分割(文本):\n    return {}\n', encoding="utf-8")
        (self.临时目录 / "说明书.md").write_text(
            "# 说明书\n\n版本 1.0.0\n参数: 文本\n错误码: 参数不合法\n内部错误\n",
            encoding="utf-8")
        入口 = self.临时目录 / "入口.py"
        入口.write_text("def 分割(文本):\n    pass\n", encoding="utf-8")
        结果 = 全面漂移检测(
            契约=self.契约, 实现目录=self.临时目录 / "实现",
            入口文件=入口, 说明书文件=self.临时目录 / "说明书.md",
            旧契约=dict(self.契约),
        )
        self.assertTrue(结果.成功, 结果.问题列表)


if __name__ == "__main__":
    unittest.main()
