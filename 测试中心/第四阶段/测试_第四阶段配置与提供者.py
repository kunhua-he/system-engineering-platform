"""第四阶段：配置体系与提供者运行闭环测试（18 场景）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.能力契约.契约 import 能力注册表
from 支持库.适配层.提供者注册表.提供者注册表 import 提供者声明, 提供者注册表
from 支持库.适配层.提供者注册表.标准提供者 import 注册全部标准提供者
from 运行核心.加载器.生命周期管理.管理器 import 装配系统, 停止系统, 卸载系统
from 项目适配层.配置适配.配置合并 import 合并配置, 解析环境配置
from 项目适配层.配置适配.配置读取 import 读取JSON配置
from 项目适配层.配置适配.配置校验 import 校验配置
from 项目适配层.运行入口.项目入口 import 项目入口


def 临时项目配置() -> tuple[Path, dict]:
    """创建带默认/开发配置的临时项目配置目录。"""
    临时目录 = Path(tempfile.mkdtemp(prefix="第四阶段配置_"))
    项目配置目录 = 临时目录 / "项目配置"
    项目配置目录.mkdir(parents=True)
    (项目配置目录 / "默认配置.json").write_text(
        json.dumps({"默认超时秒": 30, "环境名称": "默认", "重试次数": 1}, ensure_ascii=False),
        encoding="utf-8",
    )
    (项目配置目录 / "开发配置.json").write_text(
        json.dumps({"默认超时秒": 10, "环境名称": "开发", "调试开关": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    return 临时目录, 项目配置目录


class Test配置层级与覆盖(unittest.TestCase):
    """场景1-4：默认读取与三级覆盖。"""

    def test_默认配置读取成功(self):
        临时目录, 项目配置目录 = 临时项目配置()
        默认 = 读取JSON配置(项目配置目录 / "默认配置.json")
        self.assertEqual(默认["默认超时秒"], 30)
        self.assertEqual(默认["环境名称"], "默认")

    def test_项目配置覆盖默认配置(self):
        临时目录, 项目配置目录 = 临时项目配置()
        结果 = 合并配置(
            支持库默认={"默认超时秒": 60, "默认编码": "utf-8"},
            项目默认=读取JSON配置(项目配置目录 / "默认配置.json"),
        )
        self.assertTrue(结果.成功)
        self.assertEqual(结果.配置["默认超时秒"], 30)  # 项目覆盖支持库
        self.assertEqual(结果.来源表["默认超时秒"], "项目默认配置")

    def test_环境配置覆盖项目配置(self):
        临时目录, 项目配置目录 = 临时项目配置()
        环境 = 解析环境配置("开发", 项目配置目录)
        结果 = 合并配置(
            支持库默认={"默认超时秒": 60},
            项目默认=读取JSON配置(项目配置目录 / "默认配置.json"),
            环境配置=环境,
        )
        self.assertEqual(结果.配置["默认超时秒"], 10)  # 环境覆盖项目
        self.assertEqual(结果.配置["环境名称"], "开发")
        self.assertEqual(结果.来源表["默认超时秒"], "当前环境配置")

    def test_外部提供者配置覆盖项目配置(self):
        临时目录, 项目配置目录 = 临时项目配置()
        结果 = 合并配置(
            支持库默认={"默认超时秒": 60},
            项目默认=读取JSON配置(项目配置目录 / "默认配置.json"),
            环境配置={"默认超时秒": 10},
            提供者配置={"默认超时秒": 5, "数据库驱动": "模拟"},
            显式覆盖={"默认超时秒": 2},  # 运行入口显式覆盖最高
        )
        self.assertEqual(结果.配置["默认超时秒"], 2)
        self.assertEqual(结果.来源表["默认超时秒"], "运行入口显式覆盖")
        # 去掉显式覆盖：提供者配置生效
        结果2 = 合并配置(
            支持库默认={"默认超时秒": 60},
            项目默认={"默认超时秒": 30},
            环境配置={"默认超时秒": 10},
            提供者配置={"默认超时秒": 5},
        )
        self.assertEqual(结果2.配置["默认超时秒"], 5)
        self.assertEqual(结果2.来源表["默认超时秒"], "外部提供者配置")


class Test配置校验(unittest.TestCase):
    """场景5-9：类型/缺失/未知项/敏感/来源追踪。"""

    声明表 = {
        "默认超时秒": {"类型": "整数", "必填": True},
        "环境名称": {"类型": "文本", "必填": True},
        "缓存策略": {"类型": "文本", "必填": False},
    }

    def test_配置类型错误失败(self):
        结果 = 校验配置({"默认超时秒": "不是整数", "环境名称": "开发"}, 声明表=self.声明表)
        self.assertFalse(结果.成功)
        self.assertTrue(any("类型错误" in 问题 for 问题 in 结果.问题列表))

    def test_配置缺失失败(self):
        结果 = 校验配置({"默认超时秒": 10}, 声明表=self.声明表)
        self.assertFalse(结果.成功)
        self.assertTrue(any("必填配置缺失" in 问题 for 问题 in 结果.问题列表))

    def test_未知配置项失败(self):
        结果 = 校验配置(
            {"默认超时秒": 10, "环境名称": "开发", "未知项": 1},
            声明表=self.声明表,
        )
        self.assertFalse(结果.成功)
        self.assertTrue(any("未知配置项" in 问题 for 问题 in 结果.问题列表))

    def test_敏感配置不泄露(self):
        # 疑似明文密钥 → 失败
        结果 = 校验配置({"数据库连接密钥": "sk-真实密钥值123456"})
        self.assertFalse(结果.成功)
        self.assertTrue(any("疑似明文密钥" in 问题 for 问题 in 结果.问题列表))
        # 环境变量引用 → 通过
        结果2 = 校验配置({"数据库连接密钥": "数据库连接密钥环境变量"})
        self.assertTrue(结果2.成功)
        self.assertIn("数据库连接密钥", 结果2.敏感配置名列表)

    def test_配置来源可追踪(self):
        临时目录, 项目配置目录 = 临时项目配置()
        结果 = 合并配置(
            支持库默认={"默认编码": "gbk"},
            项目默认=读取JSON配置(项目配置目录 / "默认配置.json"),
        )
        self.assertEqual(结果.来源表["默认编码"], "支持库默认配置")
        self.assertEqual(结果.来源表["默认超时秒"], "项目默认配置")
        self.assertIn("默认超时秒", 结果.来源表)


class Test提供者闭环(unittest.TestCase):
    """场景10-12：唯一选择/不可用失败/初始化失败回滚。"""

    def setUp(self):
        self.注册表 = 提供者注册表()
        self.已注册 = 注册全部标准提供者(self.注册表)
        self.assertEqual(len(self.已注册), 4)

    def test_提供者唯一选择(self):
        结果 = self.注册表.选择提供者("数据库.执行查询")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值.名称, "标准数据库提供者")

    def test_同一能力多提供者注册失败(self):
        from 支持库.适配层.配置契约.提供者配置契约 import 提供者配置需求
        声明 = 提供者声明(
            名称="重复提供者", 版本="1.0.0",
            能力列表=["数据库.执行查询"], 配置需求=[],
            创建函数=lambda 配置: None,
        )
        结果 = self.注册表.注册提供者(声明)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者冲突")

    def test_提供者不可用失败(self):
        结果 = self.注册表.选择提供者("不存在的.能力")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "外部未安装")

    def test_提供者初始化失败回滚(self):
        临时注册表 = 提供者注册表()
        from 支持库.适配层.数据库适配器.数据库适配器 import 数据库适配器
        临时注册表.注册提供者(提供者声明(
            名称="坏驱动提供者", 版本="1.0.0", 能力列表=["坏.能力"],
            配置需求=[],
            创建函数=lambda 配置: 数据库适配器(驱动可用=False),
        ))
        结果 = 临时注册表.初始化提供者("坏.能力")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "外部未安装")
        self.assertFalse(临时注册表.已初始化("坏.能力"))  # 回滚后无残留

    def test_提供者初始化和停止释放(self):
        结果 = self.注册表.初始化提供者("数据库.执行查询")
        self.assertTrue(结果.成功)
        self.assertTrue(self.注册表.已初始化("数据库.执行查询"))
        调用结果 = self.注册表.调用提供者("数据库.执行查询", {"查询": "SELECT 1"})
        self.assertTrue(调用结果.成功)
        停止结果 = self.注册表.停止提供者("数据库.执行查询")
        self.assertTrue(停止结果.成功)
        self.assertFalse(self.注册表.已初始化("数据库.执行查询"))  # 已释放
        # 重复停止幂等
        停止结果2 = self.注册表.停止提供者("数据库.执行查询")
        self.assertTrue(停止结果2.成功)
        # 停止后调用失败
        调用结果2 = self.注册表.调用提供者("数据库.执行查询")
        self.assertFalse(调用结果2.成功)
        self.assertEqual(调用结果2.错误码, "外部不可访问")


class Test卸载流程(unittest.TestCase):
    """场景13-17：停止/卸载/幂等/卸载后调用失败/资源释放。"""

    def setUp(self):
        self.注册表 = 能力注册表()
        self.装配 = 装配系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        self.assertTrue(self.装配.成功, str(self.装配.问题列表))
        self.入口 = 项目入口(self.注册表)

    def test_可运行后停止(self):
        结果 = 停止系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.入口.停止()
        self.assertEqual(self.入口.状态, "已停止")

    def test_停止后卸载(self):
        停止系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        结果 = 卸载系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.入口.停止()
        self.入口.卸载()
        self.assertEqual(self.入口.状态, "已卸载")

    def test_重复卸载幂等(self):
        停止系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        结果1 = 卸载系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        结果2 = 卸载系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        self.assertTrue(结果1.成功)
        self.assertTrue(结果2.成功)  # 重复卸载幂等
        self.入口.停止()
        self.入口.卸载()
        self.入口.卸载()  # 重复卸载幂等
        self.assertEqual(self.入口.状态, "已卸载")

    def test_卸载后调用失败(self):
        停止系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        卸载系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        self.入口.停止()
        self.入口.卸载()
        结果 = self.入口.调用("读取文件", {"文件路径": "/tmp/x"})
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "资源已卸载")

    def test_资源全部释放(self):
        卸载前能力数 = len(self.注册表.能力id列表)
        self.assertGreater(卸载前能力数, 0)
        停止系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        卸载系统(系统根 / "支持库", 系统根 / "模块库", self.注册表)
        # 卸载后注册表不得残留任何能力
        self.assertEqual(len(self.注册表.能力id列表), 0)


class Test验收退出码(unittest.TestCase):
    """场景18：测试失败返回非零。"""

    def test_失败套件主函数返回非零(self):
        import 测试中心.运行测试 as 运行测试

        class _必失败测试(unittest.TestCase):
            def test_必然失败(self):
                self.assertTrue(False)

        失败套件 = unittest.TestSuite()
        失败套件.addTest(_必失败测试("test_必然失败"))
        退出码 = 运行测试.主函数(失败套件)
        self.assertEqual(退出码, 1)  # 失败套件 → 非零


if __name__ == "__main__":
    unittest.main()
