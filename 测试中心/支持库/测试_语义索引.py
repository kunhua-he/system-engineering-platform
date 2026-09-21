"""语义索引 模板测试骨架：合法调用/错误码/超时/提供者不可用（真实可跑）。"""
from __future__ import annotations
import os, sys, unittest
from unittest import mock

for 目录 in ("/Users/hekunhua/Documents/Agent/PHP/系统工程平台/支持库/后端/代码解析支持库", "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"):
    if 目录 not in sys.path:
        sys.path.insert(0, 目录)

from 语义索引 import 建代码索引, 查代码块
from 公共契约.基础类型.结果类型 import 结果


class Test语义索引(unittest.TestCase):
    """语义索引 骨架测试。"""

    def test_合法调用(self):
        结果对象 = 建代码索引(索引根="样例")
        self.assertTrue(结果对象.成功, str(结果对象.错误说明))

    def test_参数不合法(self):
        结果对象 = 建代码索引(索引根=None)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_超时(self):
        with mock.patch.dict(os.environ, {"语义索引_测试超时": "1"}):
            结果对象 = 建代码索引(索引根="样例", 超时秒=0.2)
        self.assertEqual(结果对象.错误码, "超时")

    def test_提供者不可用(self):
        with mock.patch.dict(os.environ, {"语义索引_禁用库": "1"}):
            结果对象 = 建代码索引(索引根="样例")
        self.assertEqual(结果对象.错误码, "提供者不可用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
