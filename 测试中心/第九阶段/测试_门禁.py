"""第九阶段：反向破坏验证测试（反向破坏阶段）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.能力调用.控制调用.证据链 import 证据链, 版本锁定
from 运行核心.能力调用.控制调用.控制面 import 面分离器


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

