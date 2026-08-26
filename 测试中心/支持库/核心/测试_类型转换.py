import unittest

from 支持库.后端.数据操作支持库.类型转换 import 文本转整数, 文本转逻辑, 整数转文本, 数值转文本


class 测试类型转换(unittest.TestCase):
    def test_文本转整数(self):
        self.assertEqual(文本转整数("123").转字典()["值"], 123)
        self.assertFalse(文本转整数("12.3").成功)

    def test_边界与逻辑(self):
        self.assertEqual(整数转文本(123).值, "123")
        self.assertEqual(文本转逻辑("真").值, True)
        self.assertFalse(文本转逻辑("未知").成功)
        self.assertEqual(数值转文本(1.2, 2).值, "1.20")


if __name__ == "__main__":
    unittest.main()
