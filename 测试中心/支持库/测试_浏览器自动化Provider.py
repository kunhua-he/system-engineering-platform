"""浏览器自动化 Provider 与会话资源边界回归。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))


from 公共契约.基础类型.逻辑类型 import 真, 假
class 测试浏览器自动化Provider(unittest.TestCase):
    def test_provider超时有界(self) -> None:
        from 支持库.适配层.浏览器自动化提供者.实现.提供者 import 浏览器自动化提供者

        提供者 = 浏览器自动化提供者(
            命令=[sys.executable, "-c", "import time; time.sleep(2)"]
        )
        结果 = 提供者.执行("# timeout", 会话名="测试", 超时秒=0.1)
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "超时")

    def test_会话句柄闭环与重复关闭幂等(self) -> None:
        from 支持库.后端.浏览器自动化支持库.实现 import 浏览器自动化 as 模块

        class 假Provider:
            def 建立连接(self, **参数):
                return {"成功": 真, "值": {"会话名": "测试会话"}}

            def 导航(self, **参数):
                return {"成功": 真, "值": {"地址": 参数["地址"], "标题": "测试"}}

            def 读取(self, **参数):
                return {"成功": 真, "值": {"地址": "about:blank", "标题": "测试", "内容": "正文"}}

            def 操作(self, **参数):
                return {"成功": 真, "值": {"状态": "已完成", "地址": "about:blank"}}

            def 截图(self, **参数):
                return {"成功": 真, "值": {"路径": 参数["路径"], "字节数": 1, "格式": "png"}}

            def 关闭会话(self, **参数):
                return {"成功": 真, "值": {"状态": "已关闭"}}

        原Provider = 模块._提供者
        模块._提供者 = 假Provider()
        try:
            创建 = 模块.创建会话()
            self.assertTrue(创建.成功)
            句柄 = 创建.值["句柄"]
            self.assertTrue(模块.导航页面(句柄, "about:blank").成功)
            self.assertTrue(模块.读取页面(句柄).成功)
            self.assertTrue(模块.页面操作(句柄, "等待").成功)
            第一次 = 模块.关闭会话(句柄)
            第二次 = 模块.关闭会话(句柄)
            self.assertTrue(第一次.成功)
            self.assertTrue(第二次.成功)
            self.assertIn(第二次.值["状态"], {"未找到且已幂等", "已释放"})
        finally:
            模块._提供者 = 原Provider

    def test_Provider失败不包装成成功(self) -> None:
        from 支持库.后端.浏览器自动化支持库.实现 import 浏览器自动化 as 模块

        class 失败Provider:
            def 建立连接(self, **参数):
                return {"成功": 假, "错误码": "提供者不可用", "错误说明": "测试失败"}

        原Provider = 模块._提供者
        模块._提供者 = 失败Provider()
        try:
            结果 = 模块.创建会话()
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            模块._提供者 = 原Provider


if __name__ == "__main__":
    unittest.main(verbosity=2)
