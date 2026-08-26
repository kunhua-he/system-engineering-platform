"""第九阶段：反向破坏验证测试（反向破坏阶段）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.复用审计.反向破坏.破坏验证 import 破坏验证器, 破坏场景表
from 运行核心.能力调用.控制调用.证据链 import 证据链, 版本锁定
from 运行核心.能力调用.控制调用.控制面 import 面分离器


class Test反向破坏(unittest.TestCase):
    """反向破坏：13 种破坏全部被拒绝。"""

    def test_破坏场景表完整(self):
        self.assertEqual(len(破坏场景表), 13)
        self.assertIn("提供者崩溃", 破坏场景表)
        self.assertIn("激活路由指向不存在版本", 破坏场景表)

    def test_13种破坏全部验证失败(self):
        报告 = 破坏验证器().执行()
        # 每个破坏场景都必须让验证器失败
        self.assertEqual(报告.通过数, 13,
                         [f"{证据.场景名}: 验证结果={证据.验证结果} {证据.详情}"
                          for 证据 in 报告.证据列表 if not 证据.验证结果])
        # 恒真检查：不允许全部失败仍通过
        self.assertTrue(报告.恒真检查)

    def test_发布阻断证明(self):
        报告 = 破坏验证器().执行()
        阻断场景 = [证据.场景名 for 证据 in 报告.证据列表 if 证据.发布阻断]
        self.assertIn("完整性摘要篡改", 阻断场景)
        self.assertIn("实现文件删除", 阻断场景)

    def test_旧版本恢复证明(self):
        报告 = 破坏验证器().执行()
        恢复场景 = [证据.场景名 for 证据 in 报告.证据列表 if 证据.旧版本恢复]
        self.assertIn("新版本健康失败", 恢复场景)
        self.assertIn("提供者崩溃", 恢复场景)

    def test_失败证据保留证明(self):
        报告 = 破坏验证器().执行()
        证据场景 = [证据.场景名 for 证据 in 报告.证据列表 if 证据.证据保留]
        self.assertGreaterEqual(len(证据场景), 8)

    def test_资源全部释放证明(self):
        报告 = 破坏验证器().执行()
        释放场景 = [证据.场景名 for 证据 in 报告.证据列表 if 证据.资源释放]
        self.assertIn("客户端断开", 释放场景)

class Test证据链(unittest.TestCase):
    """调用证据链：九问回答。"""

    def test_九问回答(self):
        链 = 证据链()
        证据 = 链.开始调用(
            项目="示例项目", 功能模块="文件管理", 基础模块="文档读取",
            支持库="文件系统", 提供者="本地进程", 能力id="文件系统支持库.文件操作.读取文件",
            版本="1.0.0",
        )
        链.记录结果(证据, 成功=False, 错误码="外部不可访问")
        回答 = 链.回答九问(证据)
        self.assertEqual(回答["哪个能力失败"], "文件系统支持库.文件操作.读取文件")
        self.assertEqual(回答["使用哪个版本"], "1.0.0")
        self.assertEqual(回答["使用哪个提供者"], "本地进程")
        self.assertEqual(回答["上层来自哪个模块"], "文件管理")
        self.assertEqual(回答["是否可以重试"], "是")
        self.assertEqual(回答["推荐哪个验证场景"], "反向破坏-提供者崩溃")
        self.assertEqual(回答["是否可以回滚"], "是")

    def test_参数错误不可重试(self):
        链 = 证据链()
        证据 = 链.开始调用(能力id="示例.能力", 版本="1.0.0")
        链.记录结果(证据, 成功=False, 错误码="参数不合法")
        回答 = 链.回答九问(证据)
        self.assertEqual(回答["是否可以重试"], "否")
        self.assertEqual(回答["是否可以回滚"], "否")
        self.assertEqual(回答["哪一层失败"], "契约/参数层")

    def test_查询证据(self):
        链 = 证据链()
        证据 = 链.开始调用(能力id="示例.能力")
        self.assertIsNotNone(链.查询(证据.请求id))



class Test版本锁定(unittest.TestCase):
    """版本锁定：请求结束后才减少旧版本引用。"""

    def test_锁定与释放(self):
        锁定 = 版本锁定()
        锁定.锁定(请求id="请求1", 包id="文件系统", 版本="1.0.0")
        self.assertEqual(锁定.引用数(包id="文件系统", 版本="1.0.0"), 1)
        self.assertFalse(锁定.可删除(包id="文件系统", 版本="1.0.0"))
        锁定.释放(请求id="请求1")
        self.assertEqual(锁定.引用数(包id="文件系统", 版本="1.0.0"), 0)
        self.assertTrue(锁定.可删除(包id="文件系统", 版本="1.0.0"))

    def test_重复释放幂等(self):
        锁定 = 版本锁定()
        锁定.锁定(请求id="请求1", 包id="文本处理", 版本="2.0.0")
        锁定.释放(请求id="请求1")
        self.assertFalse(锁定.释放(请求id="请求1"))  # 幂等返回 False

    def test_多请求引用计数(self):
        锁定 = 版本锁定()
        锁定.锁定(请求id="请求1", 包id="数据交换", 版本="1.0.0")
        锁定.锁定(请求id="请求2", 包id="数据交换", 版本="1.0.0")
        self.assertEqual(锁定.引用数(包id="数据交换", 版本="1.0.0"), 2)
        锁定.释放(请求id="请求1")
        self.assertFalse(锁定.可删除(包id="数据交换", 版本="1.0.0"))
        锁定.释放(请求id="请求2")
        self.assertTrue(锁定.可删除(包id="数据交换", 版本="1.0.0"))



class Test面分离(unittest.TestCase):
    """控制面/调用面分离。"""

    def test_控制面故障不影响调用面(self):
        分离 = 面分离器()
        分离.记录调用操作("网关", 成功=True)
        分离.控制面故障("安装失败")
        self.assertFalse(分离.控制面可用())
        self.assertTrue(分离.调用面可用())  # 已激活能力不受拖累

    def test_调用面高负载不阻止控制面(self):
        分离 = 面分离器()
        分离.调用面高负载()
        self.assertTrue(分离.控制面可用())  # 诊断和回滚仍可执行
        分离.记录控制操作("回滚", 成功=True)
        self.assertEqual(分离.控制面.操作计数["回滚"], 1)

    def test_未知操作拒绝(self):
        分离 = 面分离器()
        with self.assertRaises(ValueError):
            分离.记录控制操作("未知操作")




if __name__ == "__main__":
    unittest.main()

