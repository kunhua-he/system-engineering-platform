import unittest

from 支持库.后端.办公文档支持库.表格公式 import (
    求值公式, 解析单元格地址, 格式化单元格地址, 格式化列字母,
    列字母转索引, 解析单元格范围, 展开单元格范围, 批量格式化单元格地址,
    批量解析单元格地址,
)


class 测试求值公式(unittest.TestCase):
    def test_非公式原样返回(self):
        self.assertEqual(求值公式("普通文本", {}).值, {"结果文本": "普通文本"})

    def test_聚合函数(self):
        表 = {"A1": "1", "A2": "2", "B1": "3", "B2": "4"}
        self.assertEqual(求值公式("=SUM(A1:B2)", 表).值["结果文本"], "10.0")
        self.assertEqual(求值公式("=AVERAGE(A1:A2)", 表).值["结果文本"], "1.5")
        self.assertEqual(求值公式("=COUNT(A1:A2)", 表).值["结果文本"], "2")
        self.assertEqual(求值公式("=MAX(A1:A2)", 表).值["结果文本"], "2.0")
        self.assertEqual(求值公式("=MIN(A1:A2)", 表).值["结果文本"], "1.0")

    def test_四则运算与单元格替换(self):
        self.assertEqual(求值公式("=1+2*3", {}).值["结果文本"], "7")
        self.assertEqual(求值公式("=A1*2+3", {"A1": "5"}).值["结果文本"], "13")

    def test_错误值沿用excel语义(self):
        self.assertEqual(求值公式("=1/0", {}).值["结果文本"], "#VALUE!")
        self.assertEqual(求值公式("=AVERAGE(A1:A2)", {}).值["结果文本"], "0.0")
        self.assertEqual(求值公式("=ABC(1)", {}).值["结果文本"], "#VALUE!")
        self.assertEqual(求值公式("=A1+B1", {"A1": "abc", "B1": "2"}).值["结果文本"], "#VALUE!")

    def test_非法入参失败(self):
        self.assertFalse(求值公式(123, {}).成功)
        self.assertFalse(求值公式("=1+1", "不是字典").成功)


class 测试单元格地址(unittest.TestCase):
    def test_解析与格式化互逆(self):
        self.assertEqual(解析单元格地址("A1").值, {"行": 1, "列": 0})
        self.assertEqual(解析单元格地址("AB12").值, {"行": 12, "列": 27})
        self.assertEqual(格式化单元格地址(3, 27).值, {"地址": "AB3"})

    def test_非法地址返回零(self):
        self.assertEqual(解析单元格地址("??").值, {"行": 0, "列": 0})

    def test_列字母与索引(self):
        self.assertEqual(格式化列字母(0).值, {"列字母": "A"})
        self.assertEqual(格式化列字母(26).值, {"列字母": "AA"})
        self.assertEqual(列字母转索引("A").值, {"索引": 0})
        self.assertEqual(列字母转索引("AA").值, {"索引": 26})

    def test_范围解析与展开(self):
        self.assertEqual(解析单元格范围("A1:B3").值,
                         {"左上行": 1, "左上列": 0, "右下行": 3, "右下列": 1})
        self.assertEqual(解析单元格范围("C2").值,
                         {"左上行": 2, "左上列": 2, "右下行": 2, "右下列": 2})
        self.assertEqual(展开单元格范围("A1:B2").值, {"地址列表": ["A1", "B1", "A2", "B2"]})


class 测试批量格式化单元格地址(unittest.TestCase):
    def test_批量与逐项一致(self):
        行列列表 = [{"行": 1, "列": 0}, {"行": 12, "列": 27}, {"行": 3, "列": 1}]
        self.assertEqual(批量格式化单元格地址(行列列表).值,
                         {"地址列表": ["A1", "AB12", "B3"]})

    def test_跨列进位(self):
        行列列表 = [{"行": 5, "列": 26}, {"行": 6, "列": 51}, {"行": 7, "列": 701}]
        self.assertEqual(批量格式化单元格地址(行列列表).值,
                         {"地址列表": ["AA5", "AZ6", "ZZ7"]})

    def test_空列表(self):
        self.assertEqual(批量格式化单元格地址([]).值, {"地址列表": []})

    def test_逐项等价(self):
        样本 = [{"行": 1, "列": 0}, {"行": 12, "列": 27}, {"行": 1, "列": -2}]
        期望 = [格式化单元格地址(项["行"], 项["列"]).值["地址"] for 项 in 样本]
        self.assertEqual(批量格式化单元格地址(样本).值["地址列表"], 期望)

    def test_非法入参失败(self):
        self.assertFalse(批量格式化单元格地址("不是列表").成功)
        self.assertFalse(批量格式化单元格地址([1, 2]).成功)
        self.assertFalse(批量格式化单元格地址([{"行": "x", "列": 0}]).成功)
        self.assertFalse(批量格式化单元格地址([{"行": True, "列": 0}]).成功)


class 测试批量解析单元格地址(unittest.TestCase):
    def test_批量与逐项一致(self):
        地址列表 = ["A1", "AB12", "B3"]
        self.assertEqual(批量解析单元格地址(地址列表).值,
                         {"解析列表": [{"行": 1, "列": 0}, {"行": 12, "列": 27},
                                       {"行": 3, "列": 1}]})

    def test_空列表(self):
        self.assertEqual(批量解析单元格地址([]).值, {"解析列表": []})

    def test_非法地址按零处理(self):
        self.assertEqual(批量解析单元格地址(["??", "A1"]).值,
                         {"解析列表": [{"行": 0, "列": 0}, {"行": 1, "列": 0}]})

    def test_逐项等价(self):
        样本 = ["A1", "AB12", "Z9", "??", "1A"]
        期望 = [解析单元格地址(项).值 for 项 in 样本]
        self.assertEqual(批量解析单元格地址(样本).值["解析列表"], 期望)

    def test_非法入参失败(self):
        self.assertFalse(批量解析单元格地址("不是列表").成功)
        self.assertFalse(批量解析单元格地址([1, 2]).成功)


if __name__ == "__main__":
    unittest.main()
