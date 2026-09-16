"""模块库.组件生成 定向测试：真实能力调用器（手动装配三个支持库包）+ 临时项目根。

不联网、不写系统目录、不依赖并发线的全树装配（半成品包会让 后端核心.启动() 失败）。
覆盖：正向真实生成（文件真落盘 + 真实文件清单）、路径逃逸拒绝（含越出项目根与
模块名含路径成分）、重复生成拒绝覆盖、参数不合法、目录不存在、依赖无提供者、
调用器未装配返回 提供者不可用、注册能力齐全。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[2]
if str(项目根) not in sys.path:
    sys.path.insert(0, str(项目根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.组件生成 import 生成模块脚手架, 注册能力

示例能力清单 = [
    {
        "名称": "示例能力",
        "说明": "测试用示例能力",
        # 参数类型必须是平台唯一类型集的正式名（文本型/整数型/列表型/…）：
        # 形状以模块模板生成器为准（组件生成 参数契约：「条目形状以模块模板生成器为准」），
        # 缩写的「文本」会被 校验输入 判 参数类型不合法。
        "参数": [{"名称": "输入文本", "类型": "文本型", "必填": True}],
        "返回": "结果",
        "错误码": ["参数不合法"],
    }
]


def 装配底座():
    """手动装配：只注册本模块真实依赖的支持库包，不依赖全树装配。

    依赖清单随「组件规范支持库」2026-09-16 由终端层下沉而更新：下沉前 组件生成
    直连终端层 开发工具/组件规范，下沉后只经唯一能力调用器调
    `组件规范支持库.生成模块模板`；装配漏登记该包会让正向用例退化成
    「能力未注册: 组件规范支持库.生成模块模板」，而不是测模块自身的边界行为。
    """
    from 公共契约.能力契约.调用器 import 设置惰性装配函数, 注册能力调用器
    from 公共契约.能力契约.契约 import 能力注册表
    from 运行核心.能力调用.唯一能力调用 import 唯一能力调用服务, 设置全局唯一服务
    原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
    设置惰性装配函数(None)
    注册表 = 能力注册表()
    from 支持库.后端.系统核心支持库.路径安全 import 注册能力 as 注册路径安全
    from 支持库.后端.文件系统支持库.文件操作 import 注册能力 as 注册文件操作
    from 支持库.后端.组件规范支持库 import 注册能力 as 注册组件规范
    注册路径安全(注册表)
    注册文件操作(注册表)
    注册组件规范(注册表)
    服务 = 唯一能力调用服务(注册表)
    注册能力调用器(服务)
    设置全局唯一服务(服务)
    return 原惰性装配


def 卸载底座(原惰性装配) -> None:
    from 公共契约.能力契约.调用器 import 注册能力调用器, 设置惰性装配函数
    from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
    注册能力调用器(None)
    设置全局唯一服务(None)
    设置惰性装配函数(原惰性装配)


class Test组件生成模块(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.原惰性装配 = 装配底座()

    @classmethod
    def tearDownClass(cls):
        卸载底座(cls.原惰性装配)

    def setUp(self):
        临时目录 = tempfile.mkdtemp(prefix="测试_组件生成_")
        self.addCleanup(shutil.rmtree, 临时目录, ignore_errors=True)
        self.项目根 = Path(临时目录) / "临时项目根"
        self.项目根.mkdir(parents=True, exist_ok=True)

    def test_正向真实生成并落盘(self):
        结果值 = 生成模块脚手架(
            项目根=str(self.项目根), 模块名="测试生成模块", 类型="基础模块",
            能力清单=示例能力清单, 依赖能力清单=[])
        self.assertTrue(结果值.成功, 结果值.错误说明)
        self.assertEqual(结果值.值["目标相对目录"], "模块库/测试生成模块")
        self.assertGreaterEqual(结果值.值["文件数"], 8)
        self.assertEqual(结果值.值["文件数"], len(结果值.值["文件清单"]))
        模块目录 = Path(结果值.值["模块目录"])
        骨架路径 = Path(结果值.值["测试骨架"])
        self.assertTrue(模块目录.is_dir(), 模块目录)
        self.assertTrue(骨架路径.is_file(), 骨架路径)
        self.assertTrue((模块目录 / "包声明.json").is_file())
        self.assertTrue((模块目录 / "能力契约" / "参数契约.json").is_file())
        self.assertTrue((模块目录 / "实现" / "测试生成模块.py").is_file())
        self.assertTrue((模块目录 / "完整性摘要.json").is_file())
        声明 = json.loads((模块目录 / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(声明["包id"], "模块库.测试生成模块")
        self.assertEqual(声明["类型"], "基础模块")
        self.assertEqual([能力["能力id"] for 能力 in 声明["能力"]], ["测试生成模块.示例能力"])
        # 清单里的每个相对路径都必须真实存在，且都落在项目根内
        for 相对路径 in 结果值.值["文件清单"]:
            self.assertTrue((self.项目根 / 相对路径).is_file(), 相对路径)
            self.assertTrue((self.项目根 / 相对路径).resolve().is_relative_to(self.项目根.resolve()))

    def test_功能模块类型也可生成(self):
        结果值 = 生成模块脚手架(项目根=str(self.项目根), 模块名="测试功能模块", 类型="功能模块",
                          能力清单=示例能力清单)
        self.assertTrue(结果值.成功, 结果值.错误说明)
        声明 = json.loads((Path(结果值.值["模块目录"]) / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(声明["类型"], "功能模块")

    def test_模块名含目录跳转被拒绝且不落盘(self):
        结果值 = 生成模块脚手架(项目根=str(self.项目根), 模块名="../越界模块",
                          能力清单=示例能力清单)
        self.assertFalse(结果值.成功)
        self.assertEqual(结果值.错误码, "路径逃逸")
        self.assertFalse((self.项目根.parent / "越界模块").exists())

    def test_模块名含路径分隔符被拒绝(self):
        for 越界名 in ("越界/模块", "/tmp/越界模块"):
            with self.subTest(模块名=越界名):
                结果值 = 生成模块脚手架(项目根=str(self.项目根), 模块名=越界名,
                                  能力清单=示例能力清单)
                self.assertFalse(结果值.成功)
                self.assertEqual(结果值.错误码, "路径逃逸")

    def test_重复生成拒绝覆盖(self):
        首次 = 生成模块脚手架(项目根=str(self.项目根), 模块名="测试重复模块",
                         能力清单=示例能力清单)
        self.assertTrue(首次.成功, 首次.错误说明)
        二次 = 生成模块脚手架(项目根=str(self.项目根), 模块名="测试重复模块",
                         能力清单=示例能力清单)
        self.assertFalse(二次.成功)
        self.assertEqual(二次.错误码, "已存在")

    def test_参数不合法(self):
        for 参数 in (
            dict(项目根="", 模块名="测试模块", 能力清单=示例能力清单),
            dict(项目根=str(self.项目根), 模块名="", 能力清单=示例能力清单),
            dict(项目根=str(self.项目根), 模块名="测试模块", 能力清单=[]),
            dict(项目根=str(self.项目根), 模块名="测试模块", 能力清单=示例能力清单,
                 依赖能力清单="不是列表"),
        ):
            with self.subTest(参数=参数):
                结果值 = 生成模块脚手架(**参数)
                self.assertFalse(结果值.成功)
                self.assertEqual(结果值.错误码, "参数不合法")
                self.assertIsInstance(结果值, 结果)

    def test_项目根不存在返回目录不存在(self):
        结果值 = 生成模块脚手架(项目根=str(self.项目根 / "不存在的根"), 模块名="测试模块",
                          能力清单=示例能力清单)
        self.assertFalse(结果值.成功)
        self.assertEqual(结果值.错误码, "目录不存在")
        self.assertFalse((self.项目根 / "不存在的根").exists(), "不应创建缺失的项目根")

    def test_依赖无提供者(self):
        结果值 = 生成模块脚手架(
            项目根=str(self.项目根), 模块名="测试依赖模块", 能力清单=示例能力清单,
            依赖能力清单=[{"能力": "不存在的支持库.某包.某能力", "版本": ">=1.0.0"}])
        self.assertFalse(结果值.成功)
        self.assertEqual(结果值.错误码, "无提供者")

    def test_调用器未装配返回提供者不可用(self):
        from 公共契约.能力契约.调用器 import 注册能力调用器
        from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
        注册能力调用器(None)
        设置全局唯一服务(None)
        try:
            结果值 = 生成模块脚手架(项目根=str(self.项目根), 模块名="测试离线模块",
                              能力清单=示例能力清单)
        finally:
            self.原惰性装配 = 装配底座()
        self.assertFalse(结果值.成功)
        self.assertEqual(结果值.错误码, "提供者不可用")

    def test_注册能力齐全(self):
        class 假注册表:
            def __init__(self):
                self.条目 = []

            def 注册(self, 能力):
                self.条目.append(能力)

        注册表 = 假注册表()
        注册能力(注册表)
        self.assertEqual({条目.能力id for 条目 in 注册表.条目}, {"组件生成.生成模块脚手架"})
        for 条目 in 注册表.条目:
            self.assertEqual(条目.包id, "模块库.组件生成")


if __name__ == "__main__":
    unittest.main()
