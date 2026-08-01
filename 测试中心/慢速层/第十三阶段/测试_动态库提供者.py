"""第十三阶段：动态库真实提供者测试（ctypes 真实加载与真实调用）。

真实场景（全部真实执行，禁止模拟）：
1. 真实加载 libsqlite3 并调用 sqlite3_libversion，断言返回非空版本字符串；
2. 真实调用 libc strlen 计算 UTF-8 字节长度，与 Python 真实字节数一致；
3. 不存在的库 → HOST_UNAVAILABLE（当前宿主不可用，禁止伪造成功）；
4. 宿主可用性/可用库列表真实探测：可用库必须给出真实路径；
5. 不存在的函数 → 明确失败（签名未登记），不猜测调用。

注意：动态库提供者所在包 __init__.py 正由并行任务填充（数据库/进程等
提供者同包开发中），本测试按文件路径直接加载目标模块，不依赖共享包
入口的当前导入链。
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

_提供者路径 = 系统根 / "平台控制面" / "提供者" / "动态库提供者.py"
_规格 = importlib.util.spec_from_file_location("平台控制面_提供者_动态库提供者", _提供者路径)
_动态库提供者模块 = importlib.util.module_from_spec(_规格)
_规格.loader.exec_module(_动态库提供者模块)

宿主不可用状态 = _动态库提供者模块.宿主不可用状态
宿主可用状态 = _动态库提供者模块.宿主可用状态
宿主可用性 = _动态库提供者模块.宿主可用性
调用 = _动态库提供者模块.调用
可用库列表 = _动态库提供者模块.可用库列表


class Test动态库真实提供者(unittest.TestCase):
    """真实加载、真实调用、失败明确返回宿主不可用。"""

    def test_真实加载sqlite3并返回非空版本字符串(self):
        结果 = 调用("sqlite3", "sqlite3_libversion", [])
        self.assertTrue(结果.成功, f"sqlite3_libversion 应真实成功：{结果.错误说明}")
        self.assertIsInstance(结果.值, str)
        self.assertTrue(结果.值.strip(), "版本字符串不得为空")
        self.assertTrue(结果.值.split(".")[0].isdigit(),
                        f"版本应以数字开头，实际为：{结果.值}")

    def test_真实调用libc的strlen计算字节长度(self):
        文本 = "系统级支持库动态库提供者"
        结果 = 调用("libc", "strlen", [文本])
        self.assertTrue(结果.成功, f"strlen 应真实成功：{结果.错误说明}")
        self.assertEqual(结果.值, len(文本.encode("utf-8")),
                         "strlen 必须返回 UTF-8 真实字节数")
        self.assertGreater(结果.值, 0)

    def test_不存在的库返回宿主不可用(self):
        结果 = 调用("不存在的动态库", "某函数", [])
        self.assertFalse(结果.成功, "不存在的库不得伪装成功")
        self.assertEqual(结果.错误码, 宿主不可用状态)
        self.assertTrue(结果.错误说明, "必须给出中文错误说明")

    def test_宿主可用性与可用库列表真实探测(self):
        宿主 = 宿主可用性()
        self.assertTrue(宿主["可用"], f"当前宿主应可提供动态库调用：{宿主['说明']}")
        self.assertEqual(宿主["状态"], 宿主可用状态)
        self.assertTrue(宿主["平台"])
        库表 = 可用库列表()
        名称表 = [项["库名"] for 项 in 库表]
        self.assertIn("sqlite3", 名称表)
        self.assertIn("c", 名称表)
        for 项 in 库表:
            if 项["状态"] == 宿主可用状态:
                self.assertTrue(项["路径"], "可用库必须给出真实路径")

    def test_不存在的函数明确失败不猜测调用(self):
        结果 = 调用("sqlite3", "不存在的函数_xyz", [])
        self.assertFalse(结果.成功, "不存在的函数不得伪装成功")
        self.assertEqual(结果.错误码, "签名未登记")


if __name__ == "__main__":
    unittest.main(verbosity=2)
