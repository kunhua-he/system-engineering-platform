"""代码地图提供者 模板测试骨架：合法调用/错误码/超时/提供者不可用（真实可跑）。"""
from __future__ import annotations
import os, sys, unittest
from unittest import mock

for 目录 in ("支持库/适配层", "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"):
    if 目录 not in sys.path:
        sys.path.insert(0, 目录)

from 代码地图提供者 import 检查提供者, 查询项目地图状态, 重建项目地图索引
from 公共契约.基础类型.结果类型 import 结果


class Test代码地图提供者(unittest.TestCase):
    """代码地图提供者 骨架测试。"""

    def test_合法调用(self):
        结果对象 = 检查提供者()
        self.assertTrue(结果对象.成功, str(结果对象.错误说明))

    def test_参数不合法(self):
        结果对象 = 查询项目地图状态(项目根目录=None)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_超时(self):
        with mock.patch.dict(os.environ, {"代码地图提供者_测试超时": "1"}):
            结果对象 = 检查提供者(超时秒=0.2)
        self.assertEqual(结果对象.错误码, "超时")

    def test_提供者不可用(self):
        with mock.patch.dict(os.environ, {"代码地图提供者_禁用库": "1"}):
            结果对象 = 检查提供者()
        self.assertEqual(结果对象.错误码, "提供者不可用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
