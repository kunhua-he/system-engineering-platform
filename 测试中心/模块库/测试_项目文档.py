"""项目文档 模块定向回归：路径越界拦截、登记边界、写文档两段式、查文档可回溯。

口径（AGENTS.md 分级验证）：本文件属「工作包」级定向入口。模块必须由加载器装配后
才能经统一调用腿工作，故本文件只跑**不依赖调用器**的纯逻辑与边界分支；端到端的
真实链路验收走 40007 统一网关的 HTML 黑盒（见 说明/设计说明.md 第六节）。
"""

from __future__ import annotations

import os
import sys
import unittest

根 = "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"
if 根 not in sys.path:
    sys.path.insert(0, 根)
os.environ.pop("PYTHONPATH", None)

from 模块库.项目文档.实现 import 项目边界, 写文档 as 写文档模块  # noqa: E402


class 测试路径组合(unittest.TestCase):
    """组合路径：去尾斜杠拼接、空段剔除，不做文件系统判定。"""

    def test_拼接两段(self):
        self.assertEqual(项目边界.组合路径("/a/b", "开发文档"), "/a/b/开发文档")

    def test_项目根尾斜杠被去重(self):
        self.assertEqual(项目边界.组合路径("/a/b/", "开发文档"), "/a/b/开发文档")

    def test_空段被剔除(self):
        self.assertEqual(项目边界.组合路径("/a/b", "", "x.md"), "/a/b/x.md")


class 测试判据文件推导(unittest.TestCase):
    """判据文件路径推导：调用方给值优先，否则按唯一约定落在文档根下。"""

    def test_给值优先(self):
        档案 = {"项目根目录": "/项目", "文档根相对路径": "开发文档"}
        self.assertEqual(项目边界.判据文件路径(档案, "/自定义/判据.json"), "/自定义/判据.json")

    def test_未给值时按约定推导(self):
        档案 = {"项目根目录": "/项目", "文档根相对路径": "开发文档"}
        self.assertEqual(
            项目边界.判据文件路径(档案),
            "/项目/开发文档/规范/Markdown 文档体例判据.json",
        )

    def test_文档根留空回退到开发文档(self):
        档案 = {"项目根目录": "/项目", "文档根相对路径": ""}
        self.assertEqual(项目边界.文档根绝对路径(档案), "/项目/开发文档")


class 测试写文档前置校验(unittest.TestCase):
    """写文档的入参守卫：必填缺失与空白正文一律在触达调用器之前就拒绝。"""

    def test_项目名缺失(self):
        结果对象 = 写文档模块.写文档(项目名=" ", 文档相对路径="a.md", 正文="# x\n")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_文档相对路径缺失(self):
        结果对象 = 写文档模块.写文档(项目名="示例项目", 文档相对路径="  ", 正文="# x\n")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_正文空白(self):
        结果对象 = 写文档模块.写文档(项目名="示例项目", 文档相对路径="a.md", 正文="\n\n  ")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_正文非文本(self):
        结果对象 = 写文档模块.写文档(项目名="示例项目", 文档相对路径="a.md", 正文=None)
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")


class 测试登记前置校验(unittest.TestCase):
    """登记项目：项目名/项目根必填、根必须是绝对路径（相对路径会以进程 cwd 为基准）。"""

    def test_项目名缺失(self):
        from 模块库.项目文档.实现.登记项目 import 登记项目
        结果对象 = 登记项目(项目名="", 项目根目录="/tmp")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_项目根相对路径被拒(self):
        from 模块库.项目文档.实现.登记项目 import 登记项目
        结果对象 = 登记项目(项目名="示例项目", 项目根目录="相对/路径")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")


class 测试查文档守卫(unittest.TestCase):
    """查文档/查记忆：必填缺失在触达调用器之前拒绝。"""

    def test_查文档关键词缺失(self):
        from 模块库.项目文档.实现.查文档 import 查文档
        结果对象 = 查文档(项目名="示例项目", 关键词="  ")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")

    def test_查记忆项目名缺失(self):
        from 模块库.项目文档.实现.查文档 import 查记忆
        结果对象 = 查记忆(项目名="", 关键词="x")
        self.assertFalse(结果对象.成功)
        self.assertEqual(结果对象.错误码, "参数不合法")


class 测试路径越界双保险(unittest.TestCase):
    """落盘目标必须落在文档根内：这道自核不依赖上游判定，是越界写的最后一道闸。"""

    def test_越界目标被自核拦下(self):
        文档根 = "/tmp/项目文档测试根/开发文档"
        越界候选 = ["/tmp/项目文档测试根/逃逸.md", "/tmp/逃逸.md", "/etc/passwd",
                   "/tmp/项目文档测试根/开发文档备份/x.md", "/tmp/项目文档测试根/开发文档/../逃逸.md"]
        for 目标 in 越界候选:
            self.assertFalse(项目边界.目标在根内(文档根, 目标), f"越界目标不应判为在根内: {目标}")

    def test_根内目标通过自核(self):
        文档根 = "/tmp/项目文档测试根/开发文档"
        for 目标 in [文档根 + "/a.md", 文档根 + "/子目录/b.md", 文档根]:
            self.assertTrue(项目边界.目标在根内(文档根, 目标), f"根内目标应判为在根内: {目标}")

    def test_前缀相同的兄弟目录不算根内(self):
        文档根 = "/tmp/项目文档测试根/开发文档"
        仿冒 = "/tmp/项目文档测试根/开发文档备份/x.md"
        self.assertFalse(项目边界.目标在根内(文档根, 仿冒), "同前缀的兄弟目录不能被误判为根内")

    def test_空值与根尾斜杠(self):
        self.assertFalse(项目边界.目标在根内("", "/tmp/x.md"))
        self.assertFalse(项目边界.目标在根内("/tmp/根", ""))
        self.assertTrue(项目边界.目标在根内("/tmp/根/", "/tmp/根/x.md"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
