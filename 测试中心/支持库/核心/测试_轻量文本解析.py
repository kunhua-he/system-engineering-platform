import unittest

from 公共契约.基础类型.逻辑类型 import 真, 假
from 支持库.后端.办公文档支持库.轻量文本解析 import 解析Markdown块, 解析纯文本块


class 测试完整语法集(unittest.TestCase):
    def test_标题分级与降级(self):
        块 = 解析Markdown块("# 一级").值["块列表"]
        self.assertEqual(块, [{"类型": "heading", "文本": "一级", "行起": 1, "行止": 1,
                              "属性": {"章节": "heading", "level": 1}}])

        降级 = 解析Markdown块("### 三级").值["块列表"]
        self.assertEqual(降级[0]["类型"], "paragraph")
        self.assertEqual(降级[0]["属性"], {"章节": "heading", "level": 3})

    def test_井号无空格按段落(self):
        块 = 解析Markdown块("#标题").值["块列表"]
        self.assertEqual(块[0]["类型"], "paragraph")
        self.assertEqual(块[0]["属性"], {"章节": "paragraph"})

    def test_代码围栏带语言(self):
        块 = 解析Markdown块("```python\nprint(1)\n```").值["块列表"]
        self.assertEqual(块, [{"类型": "code", "文本": "print(1)", "行起": 1, "行止": 3,
                              "属性": {"章节": "code", "language": "python"}}])

    def test_代码围栏无语言(self):
        块 = 解析Markdown块("```\ncode\n```").值["块列表"]
        self.assertEqual(块[0]["属性"], {"章节": "code"})

    def test_未闭合围栏仍产出(self):
        块 = 解析Markdown块("```\ncode").值["块列表"]
        self.assertEqual(块, [{"类型": "code", "文本": "code", "行起": 1, "行止": 2,
                              "属性": {"章节": "code"}}])

    def test_语言带横线不识别围栏(self):
        块 = 解析Markdown块("```objective-c\ncode\n```").值["块列表"]
        self.assertEqual(块[0]["类型"], "paragraph")

    def test_表格分隔行静默丢弃(self):
        块 = 解析Markdown块("| a | b |\n| --- | --- |\n| 1 | 2 |").值["块列表"]
        self.assertEqual(块, [{"类型": "表格", "文本": "| a | b |\n| 1 | 2 |",
                             "行起": 1, "行止": 3, "属性": {"章节": "表格"}}])

    def test_列表合成单块(self):
        块 = 解析Markdown块("- a\n- b\n1. c").值["块列表"]
        self.assertEqual(len(块), 1)
        self.assertEqual(块[0]["文本"], "- a\n- b\n1. c")
        self.assertEqual(块[0]["属性"], {"章节": "列表项"})

    def test_列表被空行截断(self):
        块 = 解析Markdown块("- a\n\n段落").值["块列表"]
        self.assertEqual([项["类型"] for 项 in 块], ["列表项", "paragraph"])

    def test_引用与分隔线(self):
        块 = 解析Markdown块("> 引用\n\n---").值["块列表"]
        self.assertEqual([项["类型"] for 项 in 块], ["quote", "divider"])
        self.assertEqual(块[1]["文本"], "")

    def test_图像仅整行识别(self):
        块 = 解析Markdown块("![alt](u.png)").值["块列表"]
        self.assertEqual(块, [{"类型": "图像", "文本": "alt", "行起": 1, "行止": 1,
                             "属性": {"章节": "图像", "url": "u.png"}}])

        行内 = 解析Markdown块("看 ![alt](u.png) 图").值["块列表"]
        self.assertEqual(行内[0]["类型"], "paragraph")
        self.assertIn("![alt](u.png)", 行内[0]["文本"])

    def test_空文本占位(self):
        块 = 解析Markdown块("").值["块列表"]
        self.assertEqual(块, [{"类型": "paragraph", "文本": "(empty markdown file)",
                             "行起": None, "行止": None,
                             "属性": {"章节": "body", "empty": 真}}])

    def test_换行归一化(self):
        块 = 解析Markdown块("a\r\n\rb").值["块列表"]
        self.assertEqual([项["文本"] for 项 in 块], ["a", "b"])


class 测试简化语法集(unittest.TestCase):
    def test_井号无空格也算标题(self):
        块 = 解析Markdown块("#标题", "简化").值["块列表"]
        self.assertEqual(块[0]["类型"], "heading")
        self.assertEqual(块[0]["属性"], {"章节": "heading"})

    def test_非标题非代码一律按段落(self):
        块 = 解析Markdown块("> 引用\n\n---\n\n- 项", "简化").值["块列表"]
        self.assertEqual([项["类型"] for 项 in 块], ["paragraph"] * 3)
        self.assertEqual([项["属性"] for 项 in 块], [{"章节": "body"}] * 3)

    def test_空文本不产出块(self):
        self.assertEqual(解析Markdown块("", "简化").值["块列表"], [])

    def test_代码块行号(self):
        块 = 解析Markdown块("段落\n\n```\ncode\n```", "简化").值["块列表"]
        self.assertEqual([项["类型"] for 项 in 块], ["paragraph", "code"])
        self.assertEqual(块[1]["行起"], 3)
        self.assertEqual(块[1]["行止"], 5)


class 测试纯文本块(unittest.TestCase):
    def test_空行切段(self):
        块 = 解析纯文本块("a\nb\n\nc").值["块列表"]
        self.assertEqual([项["文本"] for 项 in 块], ["a\nb", "c"])
        self.assertEqual((块[0]["行起"], 块[0]["行止"]), (1, 2))
        self.assertEqual((块[1]["行起"], 块[1]["行止"]), (4, 4))

    def test_空文本(self):
        self.assertEqual(解析纯文本块("").值["块列表"], [])

    def test_纯文本不识别Markdown(self):
        块 = 解析纯文本块("# 标题\n\n```\ncode\n```").值["块列表"]
        self.assertEqual([项["类型"] for 项 in 块], ["paragraph", "paragraph"])


class 测试非法入参(unittest.TestCase):
    def test_文本非字符串失败(self):
        self.assertFalse(解析Markdown块(5).成功)
        self.assertFalse(解析Markdown块(None).成功)
        self.assertFalse(解析纯文本块([]).成功)

    def test_语法集非法失败(self):
        响应 = 解析Markdown块("a", "未知")
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "参数不合法")

    def test_语法集缺省为完整(self):
        self.assertTrue(解析Markdown块("a").成功)


if __name__ == "__main__":
    unittest.main()
