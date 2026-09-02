"""示例提供者 模板测试骨架：合法调用/错误码/超时/提供者不可用（真实可跑）。"""
from __future__ import annotations
import os, sys, unittest
from unittest import mock

for 目录 in ("/var/folders/hx/4zdx_n0s1tb0t1fl1q9zw4140000gn/T", "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"):
    if 目录 not in sys.path:
        sys.path.insert(0, 目录)

from 示例提供者 import 示例操作
from 公共契约.基础类型.结果类型 import 结果


class Test示例提供者(unittest.TestCase):
    """示例提供者 骨架测试。"""

    def test_合法调用(self):
        结果对象 = 示例操作(输入="样例")
        self.assertTrue(结果对象.成功, str(结果对象.错误说明))

    def test_参数不合法(self):
        结果对象 = 示例操作(输入=None)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_超时(self):
        with mock.patch.dict(os.environ, {"示例提供者_测试超时": "1"}):
            结果对象 = 示例操作(输入="样例", 超时秒=0.2)
        self.assertEqual(结果对象.错误码, "超时")

    def test_提供者不可用(self):
        with mock.patch.dict(os.environ, {"示例提供者_禁用库": "1"}):
            结果对象 = 示例操作(输入="样例")
        self.assertEqual(结果对象.错误码, "提供者不可用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
