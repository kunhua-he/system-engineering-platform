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

            def 调用能力(self, 能力id, 参数):
                self.调用表.append((能力id, 参数))
                if 能力id.endswith("创建会话"):
                    return {"成功": True, "值": {"句柄": 123}}
                if 能力id.endswith("导航页面"):
                    return {"成功": True, "值": {"地址": 参数["地址"], "标题": "测试"}}
                if 能力id.endswith("读取页面"):
                    return {"成功": True, "值": {"地址": "about:blank", "标题": "测试", "内容": "正文"}}
                return {"成功": True, "值": {"状态": "已关闭", "已释放": True}}

        连接器实例 = 连接器()
        网页浏览.设置HTTP连接器(连接器实例)
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

            def 调用能力(self, 能力id, 参数):
                self.调用表.append(能力id)
                if 能力id.endswith("创建会话"):
                    return {"成功": True, "值": {"句柄": 456}}
                if 能力id.endswith("导航页面"):
                    return {"成功": False, "错误码": "导航失败", "错误说明": "测试失败"}
                return {"成功": True, "值": {"已释放": True}}

        连接器实例 = 连接器()
        网页浏览.设置HTTP连接器(连接器实例)
        结果 = 网页浏览.打开并读取网页("https://example.com")
        self.assertFalse(结果.成功)
        self.assertEqual(连接器实例.调用表[-1], "浏览器自动化.关闭会话")


if __name__ == "__main__":
    unittest.main(verbosity=2)
