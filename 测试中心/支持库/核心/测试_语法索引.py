import unittest
from unittest import mock

from 支持库.后端.代码解析支持库.语法索引 import (
    批量解析语法, 解析Python语法, 解析脚本语法,
)
from 支持库.后端.代码解析支持库.语法索引.实现 import 语法索引 as 实现


class 测试Python导入(unittest.TestCase):
    def test_普通导入与from导入(self):
        值 = 解析Python语法("import os\nfrom a.b import c\n").值
        self.assertEqual(值["导入列表"], [
            {"序号": 0, "路径": "os", "导入名": "os", "行号": 1},
            {"序号": 1, "路径": "a.b", "导入名": "a.b.c", "行号": 2},
        ])

    def test_相对导入不产出(self):
        值 = 解析Python语法("from . import x\n").值
        self.assertEqual(值["导入列表"], [])

    def test_一次导入多个别名(self):
        值 = 解析Python语法("import os, sys\n").值
        self.assertEqual([条["导入名"] for 条 in 值["导入列表"]], ["os", "sys"])


class 测试Python符号(unittest.TestCase):
    def test_类与方法的名称前缀(self):
        值 = 解析Python语法(
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
            "def top():\n"
            "    pass\n"
        ).值
        self.assertEqual(
            [(条["名称"], 条["类别"], 条["行号"], 条["结束行号"]) for 条 in 值["符号列表"]],
            [("Foo", "class", 1, 3), ("Foo.bar", "function", 2, 3), ("top", "function", 4, 5)],
        )

    def test_函数体内嵌套定义不收集(self):
        值 = 解析Python语法(
            "def outer():\n"
            "    def inner():\n"
            "        pass\n"
            "    class 内类:\n"
            "        pass\n"
        ).值
        self.assertEqual([条["名称"] for 条 in 值["符号列表"]], ["outer"])

    def test_异步函数(self):
        值 = 解析Python语法("async def f():\n    pass\n").值
        self.assertEqual(值["符号列表"][0]["类别"], "function")
        self.assertEqual(值["符号列表"][0]["名称"], "f")


class 测试Python调用(unittest.TestCase):
    def test_函数内调用带所在函数(self):
        值 = 解析Python语法("def f():\n    print('a')\n").值
        self.assertEqual(值["调用列表"], [{
            "序号": 1,
            "函数名": "print", "行号": 2,
            "位置字符串": [{"序号": 0, "值": "a"}],
            "关键字字符串": [],
            "所在函数": "f",
        }])

    def test_模块级调用所在函数为空(self):
        值 = 解析Python语法("print('x')\n").值
        self.assertEqual(len(值["调用列表"]), 1)
        self.assertIsNone(值["调用列表"][0]["所在函数"])
        self.assertEqual(值["调用列表"][0]["行号"], 1)

    def test_点号调用名与关键字字符串(self):
        值 = 解析Python语法("def f():\n    a.b.c(1, 'x', key='y')\n").值
        调用 = 值["调用列表"][0]
        self.assertEqual(调用["函数名"], "a.b.c")
        self.assertEqual(调用["位置字符串"], [{"序号": 1, "值": "x"}])
        self.assertEqual(调用["关键字字符串"], [{"名称": "key", "值": "y"}])

    def test_嵌套函数体内调用归属外层函数(self):
        值 = 解析Python语法(
            "def outer():\n"
            "    def inner():\n"
            "        g()\n"
        ).值
        调用 = [条 for 条 in 值["调用列表"] if 条["函数名"] == "g"]
        self.assertEqual(len(调用), 1)
        self.assertEqual(调用[0]["所在函数"], "outer")

    def test_每次调用只产出一次(self):
        值 = 解析Python语法("def f():\n    g()\n    g()\n").值
        self.assertEqual([条["函数名"] for 条 in 值["调用列表"]], ["g", "g"])


class 测试Python类属性(unittest.TestCase):
    def test_字符串类属性(self):
        值 = 解析Python语法(
            "class T:\n"
            "    __tablename__ = 'Usr_User'\n"
        ).值
        self.assertEqual(值["类属性列表"], [
            {"序号": 1, "名称": "__tablename__", "值": "Usr_User", "行号": 2},
        ])

    def test_属性目标不是简单名字则不产出(self):
        值 = 解析Python语法(
            "class T:\n"
            "    def f(self):\n"
            "        self.__tablename__ = 'x'\n"
        ).值
        self.assertEqual(值["类属性列表"], [])

    def test_值为调用则转调用不产出属性(self):
        值 = 解析Python语法(
            "class T:\n"
            "    __tablename__ = make_name('usr_a')\n"
        ).值
        self.assertEqual(值["类属性列表"], [])
        self.assertEqual([条["函数名"] for 条 in 值["调用列表"]], ["make_name"])

    def test_非字符串值不产出(self):
        self.assertEqual(解析Python语法("class T:\n    x = 1\n").值["类属性列表"], [])


class 测试事件序号(unittest.TestCase):
    源码 = (
        "import os\n"
        "class T:\n"
        "    __tablename__ = 'usr_a'\n"
        "    def m(self):\n"
        "        g()\n"
        "print('x')\n"
    )

    def _合并(self, 值):
        汇总 = []
        for 类目 in ("导入列表", "符号列表", "类属性列表", "调用列表"):
            for 条 in 值[类目]:
                汇总.append((条["序号"], 类目, 条))
        return sorted(汇总)

    def test_跨类目单调且回放顺序正确(self):
        值 = 解析Python语法(self.源码).值
        汇总 = self._合并(值)
        self.assertEqual([条[0] for 条 in 汇总], list(range(6)))
        self.assertEqual(
            [条[1] for 条 in 汇总],
            ["导入列表", "符号列表", "类属性列表", "符号列表", "调用列表", "调用列表"],
        )
        self.assertEqual(汇总[1][2]["名称"], "T")
        self.assertEqual(汇总[3][2]["名称"], "T.m")
        self.assertEqual(汇总[4][2]["所在函数"], "T.m")
        self.assertIsNone(汇总[5][2]["所在函数"])

    def test_同文件前向引用在序号回放下可辨识(self):
        # 调用在符号之前发生：映射按序号回放时该调用查不到本文件符号
        值 = 解析Python语法("def a():\n    b()\ndef b():\n    pass\n").值
        调用 = 值["调用列表"][0]
        符号 = {条["名称"]: 条["序号"] for 条 in 值["符号列表"]}
        self.assertEqual(调用["函数名"], "b")
        self.assertLess(符号["a"], 调用["序号"])
        self.assertGreater(符号["b"], 调用["序号"])

    def test_TS事实不带序号(self):
        值 = 解析脚本语法("import x from './y'\n").值
        self.assertNotIn("序号", 值["导入列表"][0])


class 测试脚本导入与符号(unittest.TestCase):
    源码 = (
        "import { a } from './x';\n"
        "export { b } from './y';\n"
        "function foo() {}\n"
        "const bar = () => {};\n"
        "class C { m() {} }\n"
    )

    def test_导入类别与行号(self):
        值 = 解析脚本语法(self.源码).值
        self.assertEqual(值["导入列表"], [
            {"路径": "./x", "行号": 1, "类别": "import"},
            {"路径": "./y", "行号": 2, "类别": "export-from"},
        ])

    def test_符号类别(self):
        值 = 解析脚本语法(self.源码).值
        self.assertEqual(
            [(条["名称"], 条["类别"]) for 条 in 值["符号列表"]],
            [("foo", "function"), ("bar", "function"), ("C", "class"), ("C.m", "method")],
        )

    def test_解析器标记(self):
        值 = 解析脚本语法("const a = 1;\n").值
        self.assertIn(值["解析器"], ("tree-sitter", "正则降级"))

    def test_字符串列表(self):
        值 = 解析脚本语法("const q = 'SELECT * FROM usr_user';\n").值
        self.assertIn({"值": "SELECT * FROM usr_user", "行号": 1}, 值["字符串列表"])

    def test_调用表达式(self):
        值 = 解析脚本语法("platform.modules.call('knowledge', 'search');\n").值
        self.assertEqual(值["调用列表"], [{
            "函数名": "platform.modules.call",
            "行号": 1,
            "参数字符串": ["knowledge", "search"],
        }])


class 测试Vue语法集(unittest.TestCase):
    def test_逐块解析且行号自1起(self):
        源码 = (
            "<template><div/></template>\n"
            "<script lang=\"ts\">\n"
            "import x from './a'\n"
            "</script>\n"
            "<script setup>\n"
            "import y from './b'\n"
            "</script>\n"
        )
        值 = 解析脚本语法(源码, "vue").值
        self.assertEqual(值["导入列表"], [
            {"路径": "./a", "行号": 2, "类别": "import"},
            {"路径": "./b", "行号": 2, "类别": "import"},
        ])


class 测试正则降级(unittest.TestCase):
    源码 = (
        "import { a } from './x';\n"
        "import b from './y';\n"
        "platform.modules.call('knowledge', 'search');\n"
    )

    def test_降级只出导入与平台调用(self):
        with mock.patch.object(实现, "_确保TS解析器", return_value=None):
            值 = 解析脚本语法(self.源码).值
        self.assertEqual(值["解析器"], "正则降级")
        self.assertEqual(
            [(条["路径"], 条["行号"]) for 条 in 值["导入列表"]],
            [("./x", 1), ("./y", 2)],
        )
        self.assertEqual(值["调用列表"], [{
            "函数名": "platform.modules.call",
            "行号": 3,
            "参数字符串": ["knowledge", "search"],
        }])
        self.assertEqual(值["符号列表"], [])
        self.assertEqual(值["字符串列表"], [])


class 测试批量(unittest.TestCase):
    def test_严格保序(self):
        响应 = 批量解析语法([
            {"路径": "a.py", "代码文本": "import os\n"},
            {"路径": "b.ts", "代码文本": "import x from './y'\n", "语法集": "typescript"},
            {"路径": "c.vue", "代码文本": "<script>\nconst x = 1\n</script>", "语法集": "vue"},
        ])
        self.assertTrue(响应.成功)
        self.assertEqual([条["路径"] for 条 in 响应.值["结果列表"]], ["a.py", "b.ts", "c.vue"])
        self.assertEqual(响应.值["失败列表"], [])
        self.assertEqual(响应.值["结果列表"][0]["导入名"] if "导入名" in 响应.值["结果列表"][0]
                         else 响应.值["结果列表"][0]["导入列表"][0]["导入名"], "os")
        self.assertNotIn("类属性列表", 响应.值["结果列表"][1])

    def test_单文件失败隔离(self):
        响应 = 批量解析语法([
            {"路径": "bad.py", "代码文本": "def (\n"},
            {"路径": "ok.py", "代码文本": "x = 1\n"},
        ])
        self.assertTrue(响应.成功)
        self.assertEqual([条["路径"] for 条 in 响应.值["结果列表"]], ["ok.py"])
        self.assertEqual(响应.值["失败列表"][0]["路径"], "bad.py")
        self.assertEqual(响应.值["失败列表"][0]["错误码"], "语法错误")

    def test_语法集缺省按python(self):
        响应 = 批量解析语法([{"路径": "a.py", "代码文本": "import os\n"}])
        self.assertIn("类属性列表", 响应.值["结果列表"][0])


class 测试非法入参(unittest.TestCase):
    def test_Python文本非字符串(self):
        self.assertFalse(解析Python语法(5).成功)
        self.assertFalse(解析Python语法(None).成功)

    def test_脚本语法集非法(self):
        响应 = 解析脚本语法("a", "未知")
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "参数不合法")

    def test_语法错误转稳定错误码(self):
        响应 = 解析Python语法("def (\n")
        self.assertFalse(响应.成功)
        self.assertEqual(响应.错误码, "语法错误")

    def test_批量入参非法(self):
        self.assertFalse(批量解析语法("not-a-list").成功)
        self.assertFalse(批量解析语法([1, 2]).值 is None)
        响应 = 批量解析语法([1])
        self.assertEqual(响应.值["失败列表"][0]["错误码"], "参数不合法")


if __name__ == "__main__":
    unittest.main()
