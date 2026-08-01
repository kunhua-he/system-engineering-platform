"""第十四阶段工作包14：提供者直连规则注册表真实测试（真实 ast 解析）。

覆盖：内置五类结构化规则、HTTP 直连审计（真实 ast + 行号）、grpc 未登记
阻断 / 登记放行、sqlite3 未登记阻断 / 登记放行、thrift 未登记阻断、
正常源码不阻断、导出规则 JSON 可序列化。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
from 开发工具.复用审计.提供者直连规则 import 内置规则, 直连规则注册表

grpc源码 = 'import grpc\n通道 = grpc.insecure_channel("localhost:50051")\n'
sqlite3源码 = 'import sqlite3\n连接 = sqlite3.connect("库.db")\n'


class Test内置规则(unittest.TestCase):
    """内置规则包含五类结构化规则（模块 + 函数名/属性名）。"""

    def test_内置规则包含五类结构化规则(self):
        for 模式 in ("HTTP", "数据库", "动态库", "进程", "grpc"):
            self.assertIn(模式, 内置规则, f"缺少内置直连模式: {模式}")
            self.assertIn("模块", 内置规则[模式], f"{模式} 缺少模块列表")
            self.assertIn("函数名", 内置规则[模式], f"{模式} 缺少函数名列表")
            self.assertTrue(内置规则[模式]["模块"], f"{模式} 模块列表为空")
        self.assertIn("urlopen", 内置规则["HTTP"]["函数名"])
        self.assertIn("HTTPConnection", 内置规则["HTTP"]["函数名"])
        self.assertIn("sqlite3", 内置规则["数据库"]["模块"])
        self.assertIn("psycopg2", 内置规则["数据库"]["模块"])
        self.assertIn("CDLL", 内置规则["动态库"]["函数名"])
        self.assertIn("ctypes", 内置规则["动态库"]["模块"])
        self.assertIn("Popen", 内置规则["进程"]["函数名"])
        self.assertIn("subprocess", 内置规则["进程"]["模块"])
        self.assertIn("insecure_channel", 内置规则["grpc"]["函数名"])
        self.assertIn("grpc", 内置规则["grpc"]["模块"])


class Test审计源码(unittest.TestCase):
    """真实 ast 解析检测直连调用，命中项含模式、模块或函数、源码行号。"""

    def test_审计源码命中HTTP直连并带真实行号(self):
        注册表 = 直连规则注册表()
        源码 = 'import json\nimport urllib.request\n\n数据 = urllib.request.urlopen("http://x")\n'
        命中 = 注册表.审计源码(源码)
        self.assertTrue(命中, "必须命中 HTTP 直连")
        http命中 = [项 for 项 in 命中 if 项["模式"] == "HTTP"]
        self.assertTrue(http命中, "必须命中 HTTP 模式")
        for 项 in http命中:
            self.assertIn("模块或函数", 项)
            self.assertIsInstance(项["行号"], int)
        self.assertIn(2, {项["行号"] for 项 in http命中}, "import urllib.request 行号为 2")
        self.assertIn(4, {项["行号"] for 项 in http命中}, "urlopen 调用行号为 4")
        self.assertTrue(any(项["模块或函数"] == "urlopen" for 项 in http命中))
        self.assertTrue(any(项["模块或函数"] == "urllib.request" for 项 in http命中))


class Test门禁判定(unittest.TestCase):
    """未登记直连模式发布阻断；登记后视为已声明放行。"""

    def test_grpc未登记时门禁阻断(self):
        注册表 = 直连规则注册表()
        阻断, 未声明 = 注册表.门禁判定(grpc源码)
        self.assertTrue(阻断, "grpc 未登记必须阻断发布")
        self.assertTrue(未声明, "未声明直连列表不能为空")
        self.assertTrue(any(项["模式"] == "grpc" for 项 in 未声明))
        self.assertIn(1, {项["行号"] for 项 in 未声明})

    def test_登记grpc规则后门禁放行(self):
        注册表 = 直连规则注册表()
        注册表.登记规则("grpc提供者", "grpc",
                         {"模块": ["grpc", "grpc.aio"],
                          "函数名": ["secure_channel", "insecure_channel"]})
        阻断, 未声明 = 注册表.门禁判定(grpc源码)
        self.assertFalse(阻断, "登记 grpc 后视为已声明，必须放行")
        self.assertEqual(未声明, [])

    def test_sqlite3未登记阻断登记后放行(self):
        注册表 = 直连规则注册表()
        阻断, 未声明 = 注册表.门禁判定(sqlite3源码)
        self.assertTrue(阻断, "sqlite3 未登记必须阻断")
        self.assertTrue(any(项["模式"] == "数据库" for 项 in 未声明))
        注册表.登记规则("数据库提供者", "数据库",
                         {"模块": ["sqlite3"], "函数名": ["connect"]})
        阻断2, 未声明2 = 注册表.门禁判定(sqlite3源码)
        self.assertFalse(阻断2, "登记数据库模式后 sqlite3 必须放行")
        self.assertEqual(未声明2, [])

    def test_thrift未登记时门禁阻断(self):
        注册表 = 直连规则注册表()
        源码 = 'import thrift\n客户端 = thrift.client("localhost:9090")\n'
        阻断, 未声明 = 注册表.门禁判定(源码)
        self.assertTrue(阻断, "thrift 未登记必须阻断发布")
        self.assertTrue(any(项["模式"] == "thrift" for 项 in 未声明))

    def test_正常源码无直连不阻断(self):
        注册表 = 直连规则注册表()
        源码 = "def 求和(数表):\n    return sum(数表)\n\nprint(求和([1, 2, 3]))\n"
        阻断, 未声明 = 注册表.门禁判定(源码)
        self.assertFalse(阻断, "无直连的正常源码必须放行")
        self.assertEqual(未声明, [])


class Test导出规则(unittest.TestCase):
    """导出规则 返回 JSON 可序列化结构。"""

    def test_导出规则JSON可序列化(self):
        注册表 = 直连规则注册表()
        注册表.登记规则("grpc提供者", "grpc",
                         {"模块": ["grpc"], "函数名": ["insecure_channel"]})
        规则 = 注册表.导出规则()
        json.dumps(规则, ensure_ascii=False)  # 必须 JSON 可序列化，不抛异常
        文本 = json.dumps(规则, ensure_ascii=False, sort_keys=True)
        self.assertIn("内置规则", 文本)
        self.assertIn("已登记规则", 文本)
        self.assertIn("HTTP", 文本)
        self.assertEqual(规则["已登记规则"]["grpc"]["提供者id"], "grpc提供者")
        self.assertEqual(规则["已登记规则"]["grpc"]["模块"], ["grpc"])
        self.assertEqual(规则["内置规则"]["数据库"]["模块"], 内置规则["数据库"]["模块"])


if __name__ == "__main__":
    unittest.main()
