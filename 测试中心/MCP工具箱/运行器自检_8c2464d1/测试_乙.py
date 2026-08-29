"""自检乙：简单通过用例（工作包并行占位）。"""
import unittest


class 通过测试(unittest.TestCase):
    def test_通过(self) -> None:
        self.assertEqual(1 + 1, 2)


if __name__ == "__main__":
    unittest.main()
