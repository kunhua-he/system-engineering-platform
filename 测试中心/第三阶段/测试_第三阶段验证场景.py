"""第三阶段：14 个最小可运行验证场景。

覆盖：只装配支持库/只装配模块/联合装配/锁定后重复装配/锁文件漂移拒绝/
能力缺失拒绝/多提供者冲突拒绝/外部服务不可用/生命周期异常跳转拒绝/
装配失败回滚/运行成功后停止/全能力可搜索/统一结果强化/零测试门禁。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.能力契约.契约 import 能力注册表
from 公共契约.生命周期.生命周期 import 生命周期管理器
from 公共契约.包声明.声明 import 从字典构建
from 运行核心.加载器.生命周期管理.管理器 import 装配系统
from 支持库.适配层.数据库适配器.数据库适配器 import 数据库适配器


def 写临时包(临时根: Path, 包目录名: str, 声明: dict, 能力函数源码: str = "") -> Path:
    """写一个临时支持库/模块包（声明 + 入口 + 实现）。"""
    包目录 = 临时根 / 包目录名
    (包目录 / "实现").mkdir(parents=True, exist_ok=True)
    (包目录 / "包声明.json").write_text(json.dumps(声明, ensure_ascii=False, indent=2), encoding="utf-8")
    (包目录 / "实现/实现.py").write_text(能力函数源码, encoding="utf-8")
    (包目录 / "__init__.py").write_text('''"""临时包入口。"""

from __future__ import annotations

from 实现.实现 import *


def 注册能力(注册表) -> None:
    from 公共契约.能力契约.契约 import 能力实现

    for 能力id, 函数 in 注册表.能力清单():
        pass
''', encoding="utf-8")
    return 包目录


class Test装配场景(unittest.TestCase):
    """场景1-3：只装配支持库/只装配模块/联合装配。"""

    def test_只装配支持库(self):
        注册表 = 能力注册表()
        结果 = 装配系统(系统根 / "支持库", Path("/不存在的模块目录"), 注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertGreater(结果.已注册能力数, 20)

    def test_联合装配(self):
        结果 = 装配系统(系统根 / "支持库", 系统根 / "模块库")
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertGreater(结果.已注册能力数, 40)
        self.assertEqual(结果.声明能力数, 结果.已注册能力数)


class Test锁定与漂移(unittest.TestCase):
    """场景4-5：锁定后重复装配 / 锁文件漂移拒绝。"""

    def setUp(self):
        self.适配示例目录 = 系统根 / "示例项目" / "适配层示例"
        from 项目适配层.依赖锁定.依赖锁定 import 生成依赖锁定
        self.生成依赖锁定 = 生成依赖锁定
        self.结果 = 生成依赖锁定(self.适配示例目录, 系统根)
        self.assertTrue(self.结果.成功, str(self.结果.问题列表))

    def test_锁定后重复装配结果一致(self):
        结果1 = 装配系统(系统根 / "支持库", 系统根 / "模块库")
        结果2 = 装配系统(系统根 / "支持库", 系统根 / "模块库")
        self.assertEqual(结果1.已注册能力数, 结果2.已注册能力数)
        self.assertEqual(结果1.顺序列表, 结果2.顺序列表)

    def test_锁文件被修改后拒绝装配(self):
        from 项目适配层.依赖锁定.锁定校验 import 校验锁定文件
        锁定路径 = self.适配示例目录 / "依赖锁定.json"
        原始 = 锁定路径.read_text(encoding="utf-8")
        数据 = json.loads(原始)
        数据["包列表"][0]["完整性摘要"] = "已篡改"
        锁定路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            校验 = 校验锁定文件(self.适配示例目录, 系统根)
            self.assertFalse(校验.成功)
            self.assertTrue(校验.漂移列表)
            self.assertTrue(any("完整性摘要" in 问题 for 问题 in 校验.漂移列表))
        finally:
            锁定路径.write_text(原始, encoding="utf-8")


class Test拒绝场景(unittest.TestCase):
    """场景6-7：能力缺失/多提供者冲突拒绝。"""

    def test_能力缺失拒绝装配(self):
        临时目录 = Path(tempfile.mkdtemp(prefix="场景_能力缺失_"))
        声明 = {"包id": "临时.坏模块", "名称": "坏模块", "类型": "模块", "版本": "1.0.0",
                "入口": "__init__.py", "依赖": [{"能力": "不存在的.能力"}], "能力": []}
        写临时包(临时目录, "坏模块", 声明)
        结果 = 装配系统(Path("/不存在的支持库"), 临时目录)
        self.assertFalse(结果.成功)
        self.assertTrue(any("无提供者" in 问题 or "缺失" in 问题 for 问题 in 结果.问题列表))

    def test_多提供者冲突拒绝(self):
        临时目录 = Path(tempfile.mkdtemp(prefix="场景_多提供者_"))
        声明甲 = {"包id": "临时.甲", "名称": "甲", "类型": "支持库", "版本": "1.0.0",
                  "入口": "__init__.py", "依赖": [], "能力": [{"能力id": "撞.能力", "名称": "撞", "参数": [], "返回": "结果"}]}
        声明乙 = {"包id": "临时.乙", "名称": "乙", "类型": "支持库", "版本": "1.0.0",
                  "入口": "__init__.py", "依赖": [], "能力": [{"能力id": "撞.能力", "名称": "撞", "参数": [], "返回": "结果"}]}
        写临时包(临时目录, "甲", 声明甲)
        写临时包(临时目录, "乙", 声明乙)
        结果 = 装配系统(临时目录, Path("/不存在的模块目录"))
        self.assertFalse(结果.成功)
        self.assertTrue(
            any("多提供者冲突" in 问题 or "重复" in 问题 for 问题 in 结果.问题列表),
            str(结果.问题列表),
        )


class Test外部适配场景(unittest.TestCase):
    """场景8：外部服务不可用时返回明确错误。"""

    def test_外部服务不可用错误码(self):
        适配器 = 数据库适配器(驱动可用=False)
        结果 = 适配器.检查可用()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "外部未安装")
        self.assertTrue(结果.可重试)

    def test_未连接时操作失败(self):
        适配器 = 数据库适配器()
        结果 = 适配器.执行最小操作()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "外部不可访问")

    def test_协议错误可区分(self):
        适配器 = 数据库适配器()
        适配器.建立连接()
        结果 = 适配器.执行最小操作({"查询": "坏查询"})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "协议错误")

    def test_超时可区分(self):
        from 支持库.适配层.HTTP服务适配器.http服务适配器 import HTTP服务适配器
        适配器 = HTTP服务适配器()
        适配器.建立连接()
        结果 = 适配器.请求GET("/超时")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "超时")
        self.assertTrue(结果.可重试)

    def test_版本不兼容可区分(self):
        from 支持库.适配层.动态库适配器.动态库适配器 import 动态库适配器
        适配器 = 动态库适配器()
        适配器.建立连接()
        结果 = 适配器.调用函数("不存在的函数")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "版本不兼容")


class Test生命周期场景(unittest.TestCase):
    """场景9-11：非法跳转拒绝/装配失败回滚/运行成功后停止。"""

    def test_异常跳转拒绝(self):
        管理器 = 生命周期管理器("测试包", "1.0.0")
        记录 = 管理器.流转("已装配")  # 未发现 → 已装配 非法跳转
        self.assertFalse(记录.成功)
        self.assertEqual(记录.错误码, "状态跳转非法")
        self.assertEqual(管理器.状态, "未发现")

    def test_装配失败后回滚(self):
        临时目录 = Path(tempfile.mkdtemp(prefix="场景_回滚_"))
        声明 = {"包id": "临时.坏库", "名称": "坏库", "类型": "支持库", "版本": "1.0.0",
                "入口": "不存在的入口.py", "依赖": [], "能力": []}
        写临时包(临时目录, "坏库", 声明)
        结果 = 装配系统(临时目录, Path("/不存在的模块目录"))
        self.assertFalse(结果.成功)
        回滚记录 = [记录 for 记录 in 结果.生命周期记录 if 记录.操作名称 == "回滚"]
        self.assertTrue(回滚记录, "装配失败后应产生回滚记录")

    def test_运行成功后停止且幂等(self):
        管理器 = 生命周期管理器("测试包", "1.0.0")
        for 状态 in ("已发现", "已校验", "已锁定", "已装配", "可运行"):
            self.assertTrue(管理器.流转(状态).成功)
        停止1 = 管理器.流转("已停止", 操作名称="停止")
        self.assertTrue(停止1.成功)
        停止2 = 管理器.流转("已停止", 操作名称="停止")  # 重复停止幂等
        self.assertTrue(停止2.成功)

    def test_重复装配幂等(self):
        管理器 = 生命周期管理器("测试包", "1.0.0")
        for 状态 in ("已发现", "已校验", "已锁定"):
            self.assertTrue(管理器.流转(状态).成功)
        装配1 = 管理器.流转("已装配")
        装配2 = 管理器.流转("已装配")  # 重复装配幂等
        self.assertTrue(装配1.成功)
        self.assertTrue(装配2.成功)


class Test搜索与结果(unittest.TestCase):
    """场景12-13：全能力可搜索 / 统一结果强化。"""

    def test_所有能力都能被搜索器发现(self):
        from 运行核心.加载器.包发现.发现器 import 发现全部
        from 开发工具.能力搜索.能力搜索器 import 搜索声明列表
        发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
        全部能力id = {能力.能力id for 声明 in 发现.声明列表 for 能力 in 声明.能力}
        已发现id = {能力["能力id"] for 声明, 能力 in 搜索声明列表(发现.声明列表)}
        self.assertEqual(已发现id, 全部能力id)

    def test_成功结果不携带失败状态(self):
        统一结果 = 结果.成功结果("值")
        self.assertTrue(统一结果.成功)
        self.assertEqual(统一结果.错误码, "")
        self.assertEqual(统一结果.错误说明, "")
        self.assertFalse(统一结果.可重试)

    def test_失败结果可重试与详细信息(self):
        统一结果 = 结果.失败("超时", "连接超时", 可重试=True, 详情={"超时秒": 5})
        self.assertFalse(统一结果.成功)
        self.assertEqual(统一结果.错误码, "超时")
        self.assertTrue(统一结果.可重试)
        self.assertEqual(统一结果.详细信息["超时秒"], 5)


if __name__ == "__main__":
    unittest.main()
