import unittest

from 公共契约.基础类型.逻辑类型 import 真, 假
from 支持库.后端.数据操作支持库.数据集合 import 展平字典, 展平结构条目, 规范化条目指纹


class 测试展平结构条目(unittest.TestCase):
    def test_嵌套结构与列表索引(self):
        结果 = 展平结构条目({"a": {"b": 1, "c": [1, {"d": 2}]}, "e": "x"})
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["条目列表"], [
            {"路径": "a.b", "值": 1, "超深": 假},
            {"路径": "a.c[0]", "值": 1, "超深": 假},
            {"路径": "a.c[1].d", "值": 2, "超深": 假},
            {"路径": "e", "值": "x", "超深": 假},
        ])
        self.assertEqual(结果.值["总条目数"], 4)
        self.assertFalse(结果.值["已截断"])

    def test_根标量与空容器(self):
        标量 = 展平结构条目(42)
        self.assertEqual(标量.值["条目列表"], [{"路径": "$", "值": 42, "超深": 假}])
        根数组 = 展平结构条目([1, [2, 3]])
        self.assertEqual([x["路径"] for x in 根数组.值["条目列表"]], ["[0]", "[1][0]", "[1][1]"])
        空 = 展平结构条目({})
        self.assertEqual(空.值, {"条目列表": [], "总条目数": 0, "已截断": 假})

    def test_深度上限产出超深标记(self):
        结果 = 展平结构条目({"a": {"b": {"c": {"d": 1}}}}, 最大深度=1)
        self.assertEqual(结果.值["条目列表"], [{"路径": "a.b", "值": "(已超最大深度)", "超深": 真}])

    def test_条目上限与截断标记(self):
        结果 = 展平结构条目({"a": 1, "b": 2}, 最大条目数=1)
        self.assertEqual(len(结果.值["条目列表"]), 1)
        self.assertEqual(结果.值["总条目数"], 2)
        self.assertTrue(结果.值["已截断"])

    def test_可定制分隔符与索引格式(self):
        结果 = 展平结构条目({"a": [1]}, 分隔符="/", 列表索引格式="<{索引}>")
        self.assertEqual(结果.值["条目列表"], [{"路径": "a<0>", "值": 1, "超深": 假}])


class 测试展平字典(unittest.TestCase):
    def test_保留扁平键与嵌套键(self):
        结果 = 展平字典({"a": {"b": 1, "c": {"d": 2}}, "e": 3})
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值["展平结果"]["a.b"], 1)
        self.assertEqual(结果.值["展平结果"]["b"], 1)
        self.assertEqual(结果.值["展平结果"]["a.c.d"], 2)
        self.assertEqual(结果.值["展平结果"]["e"], 3)

    def test_非字典入参失败(self):
        self.assertFalse(展平字典("不是字典").成功)


class 测试规范化条目指纹(unittest.TestCase):
    def test_列表形态排序(self):
        结果 = 规范化条目指纹(
            [{"action": "b", "min_role": "查看", "description": "d2"},
             {"action": "a", "min_role": "管理", "description": "d1"}],
            ["action", "min_role", "description"],
        )
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值, {"指纹": "a|管理|d1||b|查看|d2", "条目数": 2})

    def test_字典形态键作首字段(self):
        结果 = 规范化条目指纹(
            {"b": {"min_role": "查看", "description": "d2"}, "a": {}},
            ["action", "min_role", "description"],
        )
        self.assertEqual(结果.值["指纹"], "a||||b|查看|d2")

    def test_跳过非字典条目与空输入(self):
        混入 = 规范化条目指纹([{"action": "a", "min_role": "m", "description": "d"}, "x", 3],
                              ["action", "min_role", "description"])
        self.assertEqual(混入.值, {"指纹": "a|m|d", "条目数": 1})
        self.assertEqual(规范化条目指纹([], ["action"]).值, {"指纹": "", "条目数": 0})

    def test_字段顺序缺失即失败(self):
        self.assertFalse(规范化条目指纹([{"a": 1}], []).成功)
        self.assertFalse(规范化条目指纹("不是列表", ["a"]).成功)


if __name__ == "__main__":
    unittest.main()
