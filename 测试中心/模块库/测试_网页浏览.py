"""网页浏览模块：只通过能力连接器编排浏览器支持库。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))


class 测试网页浏览模块(unittest.TestCase):
    def test_成功流程按创建导航读取关闭顺序调用(self) -> None:
        from 模块库.网页浏览.实现 import 网页浏览

        class 连接器:
            def __init__(self):
                self.调用表 = []

            def 调用能力(self, 能力id, 参数=None, **关键字):
                """实现按 `能力调用器` 协议调用（含 `调用方=` 关键字），假件须同签名。"""
                from 公共契约.基础类型.结果类型 import 结果 as 统一结果
                self.调用表.append((能力id, 参数))
                if 能力id.endswith("创建会话"):
                    return 统一结果.成功结果({"句柄": 123})
                if 能力id.endswith("导航页面"):
                    return 统一结果.成功结果({"地址": 参数["地址"], "标题": "测试"})
                if 能力id.endswith("读取页面"):
                    return 统一结果.成功结果({"地址": "about:blank", "标题": "测试", "内容": "正文"})
                return 统一结果.成功结果({"状态": "已关闭", "已释放": True})

        连接器实例 = 连接器()
        _注入假连接器(连接器实例)
        结果 = 网页浏览.打开并读取网页("about:blank")
        self.assertTrue(结果.成功)
        self.assertEqual([x[0] for x in 连接器实例.调用表], [
            "浏览器自动化.创建会话", "浏览器自动化.导航页面",
            "浏览器自动化.读取页面", "浏览器自动化.关闭会话",
        ])

    def test_导航失败仍然关闭会话(self) -> None:
        from 模块库.网页浏览.实现 import 网页浏览

        class 连接器:
            def __init__(self):
                self.调用表 = []

            def 调用能力(self, 能力id, 参数=None, **关键字):
                """实现按 `能力调用器` 协议调用（含 `调用方=` 关键字），假件须同签名。"""
                from 公共契约.基础类型.结果类型 import 结果 as 统一结果
                self.调用表.append(能力id)
                if 能力id.endswith("创建会话"):
                    return 统一结果.成功结果({"句柄": 456})
                if 能力id.endswith("导航页面"):
                    return 统一结果.失败("导航失败", "测试失败")
                return 统一结果.成功结果({"已释放": True})

        连接器实例 = 连接器()
        _注入假连接器(连接器实例)
        结果 = 网页浏览.打开并读取网页("https://example.com")
        self.assertFalse(结果.成功)
        self.assertEqual(连接器实例.调用表[-1], "浏览器自动化.关闭会话")


def _注入假连接器(连接器实例) -> None:
    """把假连接器注册为模块唯一的调用器（None 表示卸下）。

    2026-09-19（开工-20260919-193541-2a8e）：12 个模块包按「断第二条腿」删掉了
    模块级 `设置HTTP连接器` 第二入口，改经 `获取能力调用器()` 组合公开能力。
    故假连接器改为经 `注册能力调用器` 注入（模块可见的唯一通道）。
    """
    from 公共契约.能力契约.调用器 import 注册能力调用器
    注册能力调用器(连接器实例)


if __name__ == "__main__":
    unittest.main(verbosity=2)
